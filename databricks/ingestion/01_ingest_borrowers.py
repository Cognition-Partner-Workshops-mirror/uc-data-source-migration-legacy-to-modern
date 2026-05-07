# Databricks notebook source
# MAGIC %md
# MAGIC # Borrower Ingestion: CDW_BORR_MSTR -> borrowers
# MAGIC
# MAGIC Reads legacy borrower data from CSV/Parquet source files, applies transformations
# MAGIC per the column mappings, and writes to the Delta Lake `borrowers` table.
# MAGIC
# MAGIC **Source:** `CDW_BORR_MSTR` (all VARCHAR columns, dates as MM/DD/YYYY, amounts with commas)
# MAGIC **Target:** `loan_warehouse.borrowers` (proper types, normalized)

# COMMAND ----------

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import StructType, StructField, StringType
from common_transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_integer,
    expand_status_code,
    add_quality_flags,
    BORROWER_STATUS_MAP,
)

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_BORR_MSTR/"
SOURCE_FORMAT = "csv"  # or "parquet" depending on extract method
TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_TABLE = "loan_warehouse._quarantine_borrowers"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Read Legacy Source

# COMMAND ----------

legacy_schema = StructType([
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_MID_INIT", StringType(), True),
    StructField("BORR_SSN_ENCR", StringType(), True),
    StructField("BORR_DOB_DT", StringType(), True),
    StructField("BORR_ADDR_LN1", StringType(), True),
    StructField("BORR_ADDR_LN2", StringType(), True),
    StructField("BORR_CTY_NM", StringType(), True),
    StructField("BORR_ST_CD", StringType(), True),
    StructField("BORR_ZIP_CD", StringType(), True),
    StructField("BORR_PH_NBR", StringType(), True),
    StructField("BORR_EMAIL_ADDR", StringType(), True),
    StructField("BORR_CRDT_SCR", StringType(), True),
    StructField("BORR_EMP_STAT", StringType(), True),
    StructField("BORR_ANN_INCM", StringType(), True),
    StructField("BORR_CRET_DT", StringType(), True),
    StructField("BORR_UPDT_DT", StringType(), True),
    StructField("BORR_STAT_CD", StringType(), True),
    StructField("BORR_REC_TYP", StringType(), True),
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
# MAGIC ## 2. Add Quality Flags (pre-transform)

# COMMAND ----------

required_cols = ["BORR_ID", "BORR_FST_NM", "BORR_LST_NM"]
flagged_df = add_quality_flags(raw_df, required_cols)

quarantine_df = flagged_df.filter(F.col("_has_quality_issues") == True)
clean_df = flagged_df.filter(
    (F.col("_has_quality_issues") == False) | F.col("_has_quality_issues").isNull()
)

quarantine_count = quarantine_df.count()
if quarantine_count > 0:
    print(f"[QUARANTINE] {quarantine_count} rows have quality issues — writing to quarantine")
    quarantine_df.write.format("delta").mode("append").saveAsTable(QUARANTINE_TABLE)
else:
    print("[QUARANTINE] No rows quarantined")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Transform

# COMMAND ----------

transformed_df = clean_df.select(
    # Direct copies
    F.col("BORR_ID").alias("external_id"),
    F.trim(F.col("BORR_FST_NM")).alias("first_name"),
    F.trim(F.col("BORR_LST_NM")).alias("last_name"),
    F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
    F.col("BORR_SSN_ENCR").alias("ssn_hash"),

    # Date parsing: MM/DD/YYYY -> DATE
    parse_legacy_date("BORR_DOB_DT", "date_of_birth"),

    # Address fields (direct copy)
    F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
    F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
    F.trim(F.col("BORR_CTY_NM")).alias("city"),
    F.trim(F.col("BORR_ST_CD")).alias("state"),
    F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),
    F.trim(F.col("BORR_PH_NBR")).alias("phone"),
    F.trim(F.col("BORR_EMAIL_ADDR")).alias("email"),

    # Numeric parsing
    parse_legacy_integer("BORR_CRDT_SCR", "credit_score"),
    F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),
    parse_legacy_amount("BORR_ANN_INCM", "annual_income"),

    # Status expansion: ACT -> ACTIVE
    expand_status_code("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),

    # Timestamps
    parse_legacy_timestamp("BORR_CRET_DT", "created_at"),
    parse_legacy_timestamp("BORR_UPDT_DT", "updated_at"),
)

# Filter out credit scores outside valid FICO range (300-850)
transformed_df = transformed_df.withColumn(
    "credit_score",
    F.when(
        (F.col("credit_score") >= 300) & (F.col("credit_score") <= 850),
        F.col("credit_score")
    ).otherwise(F.lit(None))
)

print(f"[TRANSFORM] {transformed_df.count()} rows after transformation")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Write to Delta Lake

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
print(f"[RECONCILE] Source: {source_count}, Quarantined: {quarantine_count}, Target: {target_count}")

if source_count != (quarantine_count + target_count):
    print("[WARNING] Row count mismatch — investigate lost rows")
