# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Account Ingestion: CDW_LN_ACCT -> loan_accounts
# MAGIC
# MAGIC Reads legacy loan account data, normalizes (drops denormalized borrower fields),
# MAGIC resolves FK references to borrowers and loan_products, and writes to Delta Lake.
# MAGIC
# MAGIC **Dependencies:** Must run AFTER borrowers and loan_products ingestion.
# MAGIC
# MAGIC **Source:** `CDW_LN_ACCT`
# MAGIC **Target:** `loan_warehouse.loan_accounts`

# COMMAND ----------

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import StructType, StructField, StringType
from common_transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_decimal,
    parse_legacy_integer,
    expand_status_code,
    add_quality_flags,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_LN_ACCT/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_accounts"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Read Legacy Source

# COMMAND ----------

legacy_schema = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_SSN_LST4", StringType(), True),
    StructField("PROD_CD", StringType(), True),
    StructField("LN_ORIG_AMT", StringType(), True),
    StructField("LN_CURR_BAL", StringType(), True),
    StructField("LN_INT_RT", StringType(), True),
    StructField("LN_TERM_MOS", StringType(), True),
    StructField("LN_PMT_AMT", StringType(), True),
    StructField("LN_ORIG_DT", StringType(), True),
    StructField("LN_MAT_DT", StringType(), True),
    StructField("LN_1ST_PMT_DT", StringType(), True),
    StructField("LN_NXT_PMT_DT", StringType(), True),
    StructField("LN_STAT_CD", StringType(), True),
    StructField("LN_DLQ_DAYS", StringType(), True),
    StructField("LN_ESCROW_BAL", StringType(), True),
    StructField("LN_LTV_PCT", StringType(), True),
    StructField("PROP_ADDR_LN1", StringType(), True),
    StructField("PROP_CTY_NM", StringType(), True),
    StructField("PROP_ST_CD", StringType(), True),
    StructField("PROP_ZIP_CD", StringType(), True),
    StructField("PROP_TYP_CD", StringType(), True),
    StructField("PROP_APRS_VAL", StringType(), True),
    StructField("LN_CRET_DT", StringType(), True),
    StructField("LN_UPDT_DT", StringType(), True),
])

raw_df = (
    spark.read
    .format(SOURCE_FORMAT)
    .option("header", "true")
    .option("quote", "'")
    .schema(legacy_schema)
    .load(SOURCE_PATH)
)

source_count = raw_df.count()
print(f"[INGEST] Read {source_count} rows from {SOURCE_PATH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Quality Flags

# COMMAND ----------

required_cols = [
    "LN_ACCT_NBR", "BORR_ID", "PROD_CD", "LN_ORIG_AMT",
    "LN_CURR_BAL", "LN_INT_RT", "LN_TERM_MOS", "LN_PMT_AMT",
    "LN_ORIG_DT", "LN_MAT_DT",
]
flagged_df = add_quality_flags(raw_df, required_cols)

quarantine_df = flagged_df.filter(F.col("_has_quality_issues") == True)
clean_df = flagged_df.filter(
    (F.col("_has_quality_issues") == False) | F.col("_has_quality_issues").isNull()
)

quarantine_count = quarantine_df.count()
if quarantine_count > 0:
    print(f"[QUARANTINE] {quarantine_count} rows quarantined")
    quarantine_df.write.format("delta").mode("append").saveAsTable(QUARANTINE_TABLE)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Resolve Foreign Keys
# MAGIC
# MAGIC Replace legacy string IDs with modern auto-increment BIGINT IDs:
# MAGIC - `BORR_ID` (e.g. 'B-10001') -> `borrower_id` (BIGINT FK to borrowers.id)
# MAGIC - `PROD_CD` (e.g. 'FXD30') -> `product_id` (BIGINT FK to loan_products.id)

# COMMAND ----------

# Load lookup tables
borrower_lookup = (
    spark.table("loan_warehouse.borrowers")
    .select(
        F.col("id").alias("borrower_id"),
        F.col("external_id").alias("_borr_ext_id"),
    )
)

product_lookup = (
    spark.table("loan_warehouse.loan_products")
    .select(
        F.col("id").alias("product_id"),
        F.col("code").alias("_prod_cd"),
    )
)

# Join to resolve FKs
joined_df = (
    clean_df
    .join(borrower_lookup, clean_df["BORR_ID"] == borrower_lookup["_borr_ext_id"], "left")
    .join(product_lookup, clean_df["PROD_CD"] == product_lookup["_prod_cd"], "left")
)

# Check for orphaned records (FK resolution failures)
orphan_borrowers = joined_df.filter(F.col("borrower_id").isNull()).count()
orphan_products = joined_df.filter(F.col("product_id").isNull()).count()

if orphan_borrowers > 0:
    print(f"[WARNING] {orphan_borrowers} loan accounts reference non-existent borrowers")
if orphan_products > 0:
    print(f"[WARNING] {orphan_products} loan accounts reference non-existent products")

# Route orphans to quarantine
fk_orphans = joined_df.filter(
    F.col("borrower_id").isNull() | F.col("product_id").isNull()
)
if fk_orphans.count() > 0:
    fk_orphans.write.format("delta").mode("append").saveAsTable(QUARANTINE_TABLE)

resolved_df = joined_df.filter(
    F.col("borrower_id").isNotNull() & F.col("product_id").isNotNull()
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Transform
# MAGIC
# MAGIC Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
# MAGIC and apply type conversions per column_mappings.md.

# COMMAND ----------

transformed_df = resolved_df.select(
    F.col("LN_ACCT_NBR").alias("account_number"),
    F.col("borrower_id"),
    F.col("product_id"),

    # Amount parsing: remove commas, cast to decimal
    parse_legacy_amount("LN_ORIG_AMT", "original_amount"),
    parse_legacy_amount("LN_CURR_BAL", "current_balance"),
    parse_legacy_decimal("LN_INT_RT", 5, 3, "interest_rate"),
    parse_legacy_integer("LN_TERM_MOS", "term_months"),
    parse_legacy_amount("LN_PMT_AMT", "monthly_payment"),

    # Date parsing
    parse_legacy_date("LN_ORIG_DT", "origination_date"),
    parse_legacy_date("LN_MAT_DT", "maturity_date"),
    parse_legacy_date("LN_1ST_PMT_DT", "first_payment_date"),
    parse_legacy_date("LN_NXT_PMT_DT", "next_payment_date"),

    # Status expansion
    expand_status_code("LN_STAT_CD", LOAN_STATUS_MAP, "status"),

    # Numeric fields
    parse_legacy_integer("LN_DLQ_DAYS", "delinquency_days"),
    parse_legacy_amount("LN_ESCROW_BAL", "escrow_balance"),
    parse_legacy_decimal("LN_LTV_PCT", 5, 2, "ltv_percent"),

    # Property fields
    F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
    F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
    F.trim(F.col("PROP_ST_CD")).alias("property_state"),
    F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
    expand_status_code("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
    parse_legacy_amount("PROP_APRS_VAL", "appraised_value"),

    # Timestamps
    parse_legacy_timestamp("LN_CRET_DT", "created_at"),
    parse_legacy_timestamp("LN_UPDT_DT", "updated_at"),
)

print(f"[TRANSFORM] {transformed_df.count()} rows after transformation")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Write to Delta Lake

# COMMAND ----------

(
    transformed_df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(TARGET_TABLE)
)

target_count = spark.table(TARGET_TABLE).count()
fk_orphan_count = fk_orphans.count() if fk_orphans is not None else 0
print(f"[WRITE] Wrote {target_count} rows to {TARGET_TABLE}")
print(f"[RECONCILE] Source: {source_count}, Quarantined: {quarantine_count}, FK Orphans: {fk_orphan_count}, Target: {target_count}")
