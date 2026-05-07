# Databricks notebook source

# MAGIC %md
# MAGIC # Loan Products Ingestion: CDW_LN_PROD → loan_products
# MAGIC
# MAGIC This notebook migrates the legacy **CDW_LN_PROD** (Loan Products) reference
# MAGIC table into the modern **loan_warehouse.loan_products** Delta Lake table.
# MAGIC
# MAGIC ### Legacy Source Issues
# MAGIC - All 10 columns are VARCHAR
# MAGIC - Term months stored as string (`"360"`)
# MAGIC - Min/max amounts stored with commas (`"50,000"`)
# MAGIC - Status is an abbreviation (`ACT`) instead of a boolean
# MAGIC - Dates stored as `MM/DD/YYYY` strings
# MAGIC
# MAGIC ### What This Notebook Does
# MAGIC 1. Reads legacy product data from CSV/Parquet
# MAGIC 2. Renames cryptic columns to meaningful names
# MAGIC 3. Parses term months string → `IntegerType`
# MAGIC 4. Parses comma-formatted amounts → `DecimalType`
# MAGIC 5. Converts status code to boolean (`ACT` → `true`, `INA` → `false`)
# MAGIC 6. Parses date strings → `DateType`
# MAGIC 7. Validates required fields and writes to Delta Lake
# MAGIC
# MAGIC ### Dependencies
# MAGIC - None (reference table, no FK dependencies)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("source_path", "/mnt/legacy/cdw_ln_prod", "Source Path")
dbutils.widgets.dropdown("source_format", "csv", ["csv", "parquet"], "Source Format")
dbutils.widgets.text("target_table", "loan_warehouse.loan_products", "Target Table")
dbutils.widgets.text("error_path", "/mnt/migration/errors/loan_products", "Error Output Path")

source_path = dbutils.widgets.get("source_path")
source_format = dbutils.widgets.get("source_format")
target_table = dbutils.widgets.get("target_table")
error_path = dbutils.widgets.get("error_path")

print(f"Source:  {source_path} ({source_format})")
print(f"Target:  {target_table}")
print(f"Errors:  {error_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Read Legacy Source Data

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType
from datetime import datetime

reader = spark.read.option("header", "true")
if source_format == "csv":
    reader = reader.option("inferSchema", "false")

source_df = reader.format(source_format).load(source_path)
source_count = source_df.count()
print(f"Source row count: {source_count}")
display(source_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Apply Column Mappings & Transformations
# MAGIC
# MAGIC | Legacy Column | → Modern Column | Transformation |
# MAGIC |---------------|-----------------|----------------|
# MAGIC | `PROD_CD` | `code` | Direct copy |
# MAGIC | `PROD_DESC_TXT` | `name` | Direct copy |
# MAGIC | `PROD_TYP_CD` | `type` | Direct copy (FXD, ARM, FHA, VA) |
# MAGIC | `PROD_TERM_MOS` | `term_months` | Parse string → INT |
# MAGIC | `PROD_RT_TYP` | `rate_type` | Direct copy (FIXED, VARIABLE) |
# MAGIC | `PROD_MIN_AMT` | `min_amount` | Remove commas → DECIMAL(12,2) |
# MAGIC | `PROD_MAX_AMT` | `max_amount` | Remove commas → DECIMAL(12,2) |
# MAGIC | `PROD_STAT_CD` | `is_active` | `ACT` → `true`, `INA` → `false` |
# MAGIC | `PROD_EFF_DT` | `effective_date` | Parse MM/DD/YYYY → DATE |
# MAGIC | `PROD_EXP_DT` | `expiration_date` | Parse MM/DD/YYYY → DATE |
# MAGIC
# MAGIC **Key decision:** The legacy `PROD_STAT_CD` (a string code) is converted to a
# MAGIC proper boolean `is_active` column — this is cleaner for downstream queries
# MAGIC and avoids the need to know legacy codes.

# COMMAND ----------

PRODUCT_STATUS_MAP = {"ACT": True, "INA": False}

is_active_expr = F.lit(None).cast("boolean")
for code, val in PRODUCT_STATUS_MAP.items():
    is_active_expr = F.when(F.col("PROD_STAT_CD") == code, F.lit(val)).otherwise(is_active_expr)

run_ts = datetime.utcnow().isoformat()

transformed_df = source_df.select(
    F.col("PROD_CD").alias("code"),
    F.col("PROD_DESC_TXT").alias("name"),
    F.col("PROD_TYP_CD").alias("type"),
    F.col("PROD_TERM_MOS").cast(IntegerType()).alias("term_months"),
    F.col("PROD_RT_TYP").alias("rate_type"),
    F.regexp_replace(F.col("PROD_MIN_AMT"), ",", "").cast(DecimalType(12, 2)).alias("min_amount"),
    F.regexp_replace(F.col("PROD_MAX_AMT"), ",", "").cast(DecimalType(12, 2)).alias("max_amount"),
    is_active_expr.alias("is_active"),
    F.to_date(F.col("PROD_EFF_DT"), "MM/dd/yyyy").alias("effective_date"),
    F.to_date(F.col("PROD_EXP_DT"), "MM/dd/yyyy").alias("expiration_date"),
    F.lit("CDW_LN_PROD").alias("_migration_source"),
    F.lit(run_ts).cast("timestamp").alias("_migrated_at"),
)

print("Schema after transformation:")
transformed_df.printSchema()
display(transformed_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Validate Required Fields & Route Errors
# MAGIC
# MAGIC Required fields: `code`, `name`, `type`, `term_months`, `rate_type`

# COMMAND ----------

required_cols = ["code", "name", "type", "term_months", "rate_type"]

error_condition = F.lit(False)
for col_name in required_cols:
    error_condition = error_condition | F.col(col_name).isNull()

error_df = transformed_df.filter(error_condition).withColumn(
    "_error_reason",
    F.concat_ws("; ", *[F.when(F.col(c).isNull(), F.lit(f"{c} is NULL")) for c in required_cols]),
)
good_df = transformed_df.filter(~error_condition)

good_count = good_df.count()
error_count = error_df.count()

print(f"Valid records:   {good_count}")
print(f"Error records:   {error_count}")

if error_count > 0:
    print("\n⚠️ Error records:")
    display(error_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Write to Delta Lake
# MAGIC
# MAGIC Loan products is a small reference table (typically < 100 rows), so no
# MAGIC partitioning is applied.

# COMMAND ----------

good_df.write.format("delta").mode("append").option(
    "mergeSchema", "true"
).saveAsTable(target_table)

print(f"✓ Wrote {good_count} records to {target_table}")

if error_count > 0:
    error_df.write.format("delta").mode("append").save(error_path)
    print(f"⚠️ Wrote {error_count} error records to {error_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Post-Load Verification

# COMMAND ----------

target_count = spark.table(target_table).count()
print(f"Target table row count: {target_count}")

assert source_count == good_count + error_count, (
    f"Row count mismatch: source={source_count} != good({good_count}) + error({error_count})"
)
print(f"✓ Row count reconciliation passed")

display(spark.table(target_table))
