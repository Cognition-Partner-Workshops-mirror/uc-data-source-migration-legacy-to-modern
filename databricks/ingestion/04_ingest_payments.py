# Databricks notebook source
# MAGIC %md
# MAGIC # Payment Ingestion: CDW_PMT_HIST -> payments
# MAGIC
# MAGIC Reads legacy payment history, resolves loan_account FK, and writes to Delta Lake.
# MAGIC
# MAGIC **Dependencies:** Must run AFTER loan_accounts ingestion.
# MAGIC
# MAGIC **Source:** `CDW_PMT_HIST`
# MAGIC **Target:** `loan_warehouse.payments`

# COMMAND ----------

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import StructType, StructField, StringType
from common_transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    expand_status_code,
    add_quality_flags,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_PMT_HIST/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_TABLE = "loan_warehouse._quarantine_payments"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Read Legacy Source

# COMMAND ----------

legacy_schema = StructType([
    StructField("PMT_SEQ_NBR", StringType(), True),
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("PMT_DT", StringType(), True),
    StructField("PMT_AMT", StringType(), True),
    StructField("PMT_PRIN_AMT", StringType(), True),
    StructField("PMT_INT_AMT", StringType(), True),
    StructField("PMT_ESCROW_AMT", StringType(), True),
    StructField("PMT_LATE_FEE", StringType(), True),
    StructField("PMT_TYP_CD", StringType(), True),
    StructField("PMT_STAT_CD", StringType(), True),
    StructField("PMT_RECV_DT", StringType(), True),
    StructField("PMT_PROC_DT", StringType(), True),
    StructField("PMT_CRET_DT", StringType(), True),
    StructField("PMT_UPDT_DT", StringType(), True),
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

required_cols = ["PMT_SEQ_NBR", "LN_ACCT_NBR", "PMT_DT", "PMT_AMT", "PMT_TYP_CD", "PMT_STAT_CD"]
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
# MAGIC ## 3. Resolve Loan Account FK

# COMMAND ----------

loan_lookup = (
    spark.table("loan_warehouse.loan_accounts")
    .select(
        F.col("id").alias("loan_account_id"),
        F.col("account_number").alias("_ln_acct_nbr"),
    )
)

joined_df = clean_df.join(
    loan_lookup,
    clean_df["LN_ACCT_NBR"] == loan_lookup["_ln_acct_nbr"],
    "left",
)

orphan_count = joined_df.filter(F.col("loan_account_id").isNull()).count()
if orphan_count > 0:
    print(f"[WARNING] {orphan_count} payments reference non-existent loan accounts")
    orphan_df = joined_df.filter(F.col("loan_account_id").isNull())
    orphan_df.write.format("delta").mode("append").saveAsTable(QUARANTINE_TABLE)

resolved_df = joined_df.filter(F.col("loan_account_id").isNotNull())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Transform

# COMMAND ----------

transformed_df = resolved_df.select(
    F.col("PMT_SEQ_NBR").alias("legacy_payment_id"),
    F.col("loan_account_id"),

    # Date parsing
    parse_legacy_date("PMT_DT", "payment_date"),

    # Amount parsing
    parse_legacy_amount("PMT_AMT", "total_amount"),
    parse_legacy_amount("PMT_PRIN_AMT", "principal_amount"),
    parse_legacy_amount("PMT_INT_AMT", "interest_amount"),
    parse_legacy_amount("PMT_ESCROW_AMT", "escrow_amount"),
    parse_legacy_amount("PMT_LATE_FEE", "late_fee"),

    # Status code expansion
    expand_status_code("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
    expand_status_code("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),

    # Additional dates
    parse_legacy_date("PMT_RECV_DT", "received_date"),
    parse_legacy_date("PMT_PROC_DT", "processed_date"),

    # Timestamps
    parse_legacy_timestamp("PMT_CRET_DT", "created_at"),
    parse_legacy_timestamp("PMT_UPDT_DT", "updated_at"),
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
print(f"[WRITE] Wrote {target_count} rows to {TARGET_TABLE}")
print(f"[RECONCILE] Source: {source_count}, Quarantined: {quarantine_count}, FK Orphans: {orphan_count}, Target: {target_count}")
