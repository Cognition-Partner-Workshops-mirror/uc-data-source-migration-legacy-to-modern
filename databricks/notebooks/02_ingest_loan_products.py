# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Notebook 02: Ingest Loan Products
# MAGIC **Source:** `CDW_LN_PROD` (Legacy Corporate Data Warehouse)
# MAGIC **Target:** `loan_warehouse.loan_products` (Delta Lake)
# MAGIC
# MAGIC This notebook reads the legacy loan product reference table and transforms it into
# MAGIC a properly typed Delta Lake table. This is a small dimension table (~5-50 rows)
# MAGIC that must be loaded **before** loan accounts (which reference products via FK).
# MAGIC
# MAGIC ### Anomalies Handled
# MAGIC | ID | Anomaly | Severity |
# MAGIC |----|---------|----------|
# MAGIC | ANO-001 | Amount strings with commas (`"1,500,000"`) → `DECIMAL` | Critical |
# MAGIC | ANO-002 | Dates in `MM/DD/YYYY` format → `DATE` | Critical |
# MAGIC | ANO-004 | Status code → boolean (`ACT` → `true`, `INA` → `false`) | High |

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Configuration

# COMMAND ----------

from datetime import datetime

SOURCE_PATH = "/mnt/legacy-cdw/CDW_LN_PROD"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"
DQ_LOG_TABLE = "loan_warehouse.data_quality_log"
RUN_ID = f"product_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

print(f"Run ID: {RUN_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Define Legacy Schema
# MAGIC The product table has 10 columns, all VARCHAR. Key fields include
# MAGIC `PROD_MIN_AMT`/`PROD_MAX_AMT` (comma-formatted amounts) and
# MAGIC `PROD_EXP_DT` (which uses `12/31/2099` as a sentinel for "no expiry").

# COMMAND ----------

from pyspark.sql.types import StructType, StructField, StringType

LEGACY_SCHEMA = StructType([
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

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Read Source Data

# COMMAND ----------

if SOURCE_FORMAT == "csv":
    source_df = (
        spark.read.schema(LEGACY_SCHEMA)
        .option("header", "true")
        .csv(SOURCE_PATH)
    )
else:
    source_df = spark.read.parquet(SOURCE_PATH)

source_count = source_df.count()
print(f"Source rows: {source_count}")
display(source_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Transform to Modern Schema
# MAGIC
# MAGIC Key transformations:
# MAGIC
# MAGIC | Legacy Column | Modern Column | Transformation |
# MAGIC |---------------|---------------|----------------|
# MAGIC | `PROD_CD` | `code` | Trim whitespace |
# MAGIC | `PROD_DESC_TXT` | `name` | Trim whitespace |
# MAGIC | `PROD_TERM_MOS` | `term_months` | Cast `VARCHAR` → `INT` |
# MAGIC | `PROD_MIN_AMT` | `min_amount` | Strip commas → `DECIMAL(12,2)` |
# MAGIC | `PROD_MAX_AMT` | `max_amount` | Strip commas → `DECIMAL(12,2)` |
# MAGIC | `PROD_STAT_CD` | `is_active` | `ACT` → `true`, anything else → `false` |
# MAGIC | `PROD_EFF_DT` | `effective_date` | Parse `MM/DD/YYYY` → `DATE` |
# MAGIC | `PROD_EXP_DT` | `expiration_date` | Parse `MM/DD/YYYY` → `DATE` (`12/31/2099` = no expiry) |

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, IntegerType

def parse_legacy_date(col_name, alias):
    return F.coalesce(
        F.to_date(F.col(col_name), "MM/dd/yyyy"),
        F.to_date(F.col(col_name), "yyyy-MM-dd"),
    ).alias(alias)

def parse_legacy_amount(col_name, alias):
    cleaned = F.regexp_replace(F.col(col_name), r"[$,\s]", "")
    return cleaned.cast(DecimalType(12, 2)).alias(alias)

transformed_df = source_df.select(
    F.trim(F.col("PROD_CD")).alias("code"),
    F.trim(F.col("PROD_DESC_TXT")).alias("name"),
    F.trim(F.col("PROD_TYP_CD")).alias("type"),
    F.col("PROD_TERM_MOS").cast(IntegerType()).alias("term_months"),
    F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
    parse_legacy_amount("PROD_MIN_AMT", "min_amount"),
    parse_legacy_amount("PROD_MAX_AMT", "max_amount"),
    # ANO-004: Convert status to boolean for simpler filtering
    F.when(
        F.upper(F.trim(F.col("PROD_STAT_CD"))) == "ACT", F.lit(True)
    ).otherwise(F.lit(False)).alias("is_active"),
    parse_legacy_date("PROD_EFF_DT", "effective_date"),
    parse_legacy_date("PROD_EXP_DT", "expiration_date"),
    F.current_timestamp().alias("_ingestion_ts"),
    F.lit("CDW").alias("_source_system"),
)

print(f"Transformed rows: {transformed_df.count()}")
display(transformed_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Detect Data Quality Anomalies
# MAGIC Check for null required fields and unparseable amount values.

# COMMAND ----------

from functools import reduce
from pyspark.sql import DataFrame

anomalies = []

# Null required fields
for col_name in ["PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD"]:
    null_records = source_df.filter(
        F.col(col_name).isNull() | (F.trim(F.col(col_name)) == "")
    ).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_LN_PROD").alias("source_table"),
        F.coalesce(F.col("PROD_CD"), F.lit("UNKNOWN")).alias("source_record_id"),
        F.lit(col_name).alias("column_name"),
        F.lit("NULL_REQUIRED").alias("anomaly_type"),
        F.lit("CRITICAL").alias("severity"),
        F.lit(f"Required field {col_name} is null/blank").alias("description"),
        F.col(col_name).alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(null_records)

# Unparseable amounts
for col_name in ["PROD_MIN_AMT", "PROD_MAX_AMT"]:
    cleaned = F.regexp_replace(F.col(col_name), r"[$,\s]", "")
    bad = source_df.filter(
        F.col(col_name).isNotNull() & cleaned.cast(DecimalType(12, 2)).isNull()
    ).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_LN_PROD").alias("source_table"),
        F.col("PROD_CD").alias("source_record_id"),
        F.lit(col_name).alias("column_name"),
        F.lit("PARSE_FAILURE").alias("anomaly_type"),
        F.lit("CRITICAL").alias("severity"),
        F.lit(f"{col_name} could not be parsed to decimal").alias("description"),
        F.col(col_name).alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(bad)

anomaly_df = reduce(DataFrame.unionByName, anomalies)
anomaly_count = anomaly_df.count()
print(f"Anomalies detected: {anomaly_count}")
if anomaly_count > 0:
    display(anomaly_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Write Anomalies to DQ Log

# COMMAND ----------

if anomaly_count > 0:
    anomaly_df.write.mode("append").saveAsTable(DQ_LOG_TABLE)
    print(f"Wrote {anomaly_count} anomaly records to {DQ_LOG_TABLE}")
else:
    print("No anomalies to write.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Write to Target Table (MERGE)
# MAGIC Idempotent upsert on `code` (legacy `PROD_CD`).

# COMMAND ----------

transformed_df.createOrReplaceTempView("products_staging")

spark.sql(f"""
    MERGE INTO {TARGET_TABLE} AS target
    USING products_staging AS source
    ON target.code = source.code
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")

target_count = spark.table(TARGET_TABLE).count()
print(f"Target rows after merge: {target_count}")
display(spark.table(TARGET_TABLE))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC | Metric | Value |
# MAGIC |--------|-------|
# MAGIC | Source rows | `{source_count}` |
# MAGIC | Target rows | `{target_count}` |
# MAGIC | Anomalies | `{anomaly_count}` |
# MAGIC
# MAGIC **Next step:** Run `03_ingest_loan_accounts` notebook.
