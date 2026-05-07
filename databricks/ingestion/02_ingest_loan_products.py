# Databricks notebook source
# MAGIC %md
# MAGIC # Loan Product Ingestion: CDW_LN_PROD -> loan_products
# MAGIC
# MAGIC Reads legacy loan product data, transforms types and status codes,
# MAGIC and writes to the Delta Lake `loan_products` table.
# MAGIC
# MAGIC **Source:** `CDW_LN_PROD`
# MAGIC **Target:** `loan_warehouse.loan_products`

# COMMAND ----------

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import StructType, StructField, StringType
from common_transforms import (
    parse_legacy_date,
    parse_legacy_amount,
    parse_legacy_integer,
    expand_product_status,
    add_quality_flags,
)

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_LN_PROD/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_products"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Read Legacy Source

# COMMAND ----------

legacy_schema = StructType([
    StructField("PROD_CD", StringType(), True),
    StructField("PROD_DESC_TXT", StringType(), True),
    StructField("PROD_TYP_CD", StringType(), True),
    StructField("PROD_TERM_MOS", StringType(), True),
    StructField("PROD_RT_TYP", StringType(), True),
    StructField("PROD_MIN_AMT", StringType(), True),
    StructField("PROD_MAX_AMT", StringType(), True),
    StructField("PROD_STAT_CD", StringType(), True),
    StructField("PROD_EFF_DT", StringType(), True),
    StructField("PROD_EXP_DT", StringType(), True),
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

required_cols = ["PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD", "PROD_TERM_MOS", "PROD_RT_TYP"]
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
# MAGIC ## 3. Transform

# COMMAND ----------

transformed_df = clean_df.select(
    F.trim(F.col("PROD_CD")).alias("code"),
    F.trim(F.col("PROD_DESC_TXT")).alias("name"),
    F.trim(F.col("PROD_TYP_CD")).alias("type"),
    parse_legacy_integer("PROD_TERM_MOS", "term_months"),
    F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
    parse_legacy_amount("PROD_MIN_AMT", "min_amount"),
    parse_legacy_amount("PROD_MAX_AMT", "max_amount"),
    expand_product_status("PROD_STAT_CD", "is_active"),
    parse_legacy_date("PROD_EFF_DT", "effective_date"),
    parse_legacy_date("PROD_EXP_DT", "expiration_date"),
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
