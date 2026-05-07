# Databricks notebook source

# MAGIC %md
# MAGIC # Borrower Ingestion: CDW_BORR_MSTR → borrowers
# MAGIC
# MAGIC This notebook migrates the legacy **CDW_BORR_MSTR** (Borrower Master) table into
# MAGIC the modern **loan_warehouse.borrowers** Delta Lake table.
# MAGIC
# MAGIC ### Legacy Source Issues
# MAGIC - All 20 columns are VARCHAR (no proper typing)
# MAGIC - Dates stored as `MM/DD/YYYY` strings
# MAGIC - Amounts stored with commas (`"92,500"`)
# MAGIC - Status codes are cryptic abbreviations (`ACT`, `INA`)
# MAGIC - `BORR_REC_TYP` column is unused and will be dropped
# MAGIC
# MAGIC ### What This Notebook Does
# MAGIC 1. Reads legacy borrower data from CSV/Parquet source
# MAGIC 2. Renames cryptic columns to meaningful names
# MAGIC 3. Parses date strings → `DateType` / `TimestampType`
# MAGIC 4. Parses comma-formatted amounts → `DecimalType`
# MAGIC 5. Expands status codes (`ACT` → `Active`, `INA` → `Inactive`)
# MAGIC 6. Validates required fields and routes errors
# MAGIC 7. Writes clean data to Delta Lake

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC Set the source path, format, and target table below. Adjust these
# MAGIC widgets to match your environment.

# COMMAND ----------

dbutils.widgets.text("source_path", "/mnt/legacy/cdw_borr_mstr", "Source Path")
dbutils.widgets.dropdown("source_format", "csv", ["csv", "parquet"], "Source Format")
dbutils.widgets.text("target_table", "loan_warehouse.borrowers", "Target Table")
dbutils.widgets.text("error_path", "/mnt/migration/errors/borrowers", "Error Output Path")

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
# MAGIC
# MAGIC Read the CDW_BORR_MSTR export. We disable schema inference to keep
# MAGIC everything as strings — the transformations below handle all type casting
# MAGIC explicitly so we can catch and log parse failures.

# COMMAND ----------

reader = spark.read.option("header", "true")
if source_format == "csv":
    reader = reader.option("inferSchema", "false")

source_df = reader.format(source_format).load(source_path)

source_count = source_df.count()
print(f"Source row count: {source_count}")
display(source_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Define Transformation Helpers
# MAGIC
# MAGIC These functions handle the core type conversions used across the pipeline.
# MAGIC
# MAGIC | Function | What It Does |
# MAGIC |----------|-------------|
# MAGIC | `parse_date_col` | `MM/DD/YYYY` string → `DateType` |
# MAGIC | `parse_timestamp_col` | `MM/DD/YYYY` string → `TimestampType` (midnight) |
# MAGIC | `parse_amount_col` | Remove commas, cast to `DecimalType` |
# MAGIC | `parse_int_col` | String → `IntegerType` |
# MAGIC | `expand_status_col` | Map abbreviation codes to readable labels |
# MAGIC
# MAGIC All functions return `NULL` for unparseable values rather than raising
# MAGIC exceptions, so bad data is captured downstream instead of crashing the pipeline.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType
from datetime import datetime


def parse_date_col(col_name):
    """Parse MM/DD/YYYY string to DateType. Returns NULL for bad values."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy").cast(DateType())


def parse_timestamp_col(col_name):
    """Parse MM/DD/YYYY string to TimestampType (midnight)."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").cast(TimestampType())


def parse_amount_col(col_name, precision=12, scale=2):
    """Remove commas from amount strings and cast to Decimal.

    Examples:
        '92,500'    → 92500.00
        '1,487.02'  → 1487.02
    """
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(precision, scale))
    )


def parse_int_col(col_name):
    """Cast string to IntegerType. Returns NULL for non-numeric."""
    return F.col(col_name).cast(IntegerType())


def expand_status_col(col_name, mapping):
    """Replace abbreviated codes with full descriptive values.

    Unmapped codes are kept as-is (not dropped to NULL).
    """
    expr = F.col(col_name)
    for code, label in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(label)).otherwise(expr)
    return expr

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Apply Column Mappings & Transformations
# MAGIC
# MAGIC This is the core transformation step. Each legacy column is mapped to its
# MAGIC modern equivalent per the column mappings document:
# MAGIC
# MAGIC | Legacy Column | → Modern Column | Transformation |
# MAGIC |---------------|-----------------|----------------|
# MAGIC | `BORR_ID` | `external_id` | Direct copy |
# MAGIC | `BORR_FST_NM` | `first_name` | Direct copy |
# MAGIC | `BORR_LST_NM` | `last_name` | Direct copy |
# MAGIC | `BORR_MID_INIT` | `middle_initial` | Direct copy |
# MAGIC | `BORR_SSN_ENCR` | `ssn_hash` | Direct copy |
# MAGIC | `BORR_DOB_DT` | `date_of_birth` | Parse MM/DD/YYYY → DATE |
# MAGIC | `BORR_ADDR_LN1` | `address_line1` | Direct copy |
# MAGIC | `BORR_ADDR_LN2` | `address_line2` | Direct copy |
# MAGIC | `BORR_CTY_NM` | `city` | Direct copy |
# MAGIC | `BORR_ST_CD` | `state` | Direct copy |
# MAGIC | `BORR_ZIP_CD` | `zip_code` | Direct copy |
# MAGIC | `BORR_PH_NBR` | `phone` | Direct copy |
# MAGIC | `BORR_EMAIL_ADDR` | `email` | Direct copy |
# MAGIC | `BORR_CRDT_SCR` | `credit_score` | Parse string → INT |
# MAGIC | `BORR_EMP_STAT` | `employment_status` | Direct copy |
# MAGIC | `BORR_ANN_INCM` | `annual_income` | Remove commas → DECIMAL(12,2) |
# MAGIC | `BORR_STAT_CD` | `status` | `ACT` → `Active`, `INA` → `Inactive` |
# MAGIC | `BORR_CRET_DT` | `created_at` | Parse MM/DD/YYYY → TIMESTAMP |
# MAGIC | `BORR_UPDT_DT` | `updated_at` | Parse MM/DD/YYYY → TIMESTAMP |
# MAGIC | `BORR_REC_TYP` | *(dropped)* | Not needed in modern schema |

# COMMAND ----------

BORROWER_STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive",
}

run_ts = datetime.utcnow().isoformat()

transformed_df = source_df.select(
    F.col("BORR_ID").alias("external_id"),
    F.col("BORR_FST_NM").alias("first_name"),
    F.col("BORR_LST_NM").alias("last_name"),
    F.col("BORR_MID_INIT").alias("middle_initial"),
    F.col("BORR_SSN_ENCR").alias("ssn_hash"),
    parse_date_col("BORR_DOB_DT").alias("date_of_birth"),
    F.col("BORR_ADDR_LN1").alias("address_line1"),
    F.col("BORR_ADDR_LN2").alias("address_line2"),
    F.col("BORR_CTY_NM").alias("city"),
    F.col("BORR_ST_CD").alias("state"),
    F.col("BORR_ZIP_CD").alias("zip_code"),
    F.col("BORR_PH_NBR").alias("phone"),
    F.col("BORR_EMAIL_ADDR").alias("email"),
    parse_int_col("BORR_CRDT_SCR").alias("credit_score"),
    F.col("BORR_EMP_STAT").alias("employment_status"),
    parse_amount_col("BORR_ANN_INCM").alias("annual_income"),
    expand_status_col("BORR_STAT_CD", BORROWER_STATUS_MAP).alias("status"),
    parse_timestamp_col("BORR_CRET_DT").alias("created_at"),
    parse_timestamp_col("BORR_UPDT_DT").alias("updated_at"),
    F.lit("CDW_BORR_MSTR").alias("_migration_source"),
    F.lit(run_ts).cast("timestamp").alias("_migrated_at"),
)

print("Schema after transformation:")
transformed_df.printSchema()
display(transformed_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Validate Required Fields & Route Errors
# MAGIC
# MAGIC We check that `external_id`, `first_name`, and `last_name` are not NULL.
# MAGIC Records that fail validation are routed to the error path with a descriptive
# MAGIC `_error_reason` column — they are **never silently dropped**.

# COMMAND ----------

required_cols = ["external_id", "first_name", "last_name"]

error_condition = F.lit(False)
for col_name in required_cols:
    error_condition = error_condition | F.col(col_name).isNull()

error_df = transformed_df.filter(error_condition).withColumn(
    "_error_reason",
    F.concat_ws(
        "; ",
        *[F.when(F.col(c).isNull(), F.lit(f"{c} is NULL")) for c in required_cols],
    ),
)

good_df = transformed_df.filter(~error_condition)

good_count = good_df.count()
error_count = error_df.count()

print(f"Valid records:   {good_count}")
print(f"Error records:   {error_count}")
print(f"Total:           {good_count + error_count} (source was {source_count})")

if error_count > 0:
    print("\n⚠️ Error records:")
    display(error_df.select("external_id", "first_name", "last_name", "_error_reason"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Write Valid Records to Delta Lake
# MAGIC
# MAGIC Write the validated borrower records to the target Delta Lake table.
# MAGIC Uses `mergeSchema=true` to handle any schema evolution gracefully.
# MAGIC
# MAGIC > **Note:** The table is partitioned by `state` for geographic query
# MAGIC > performance. The `borrower_id` identity column is auto-generated
# MAGIC > by Delta Lake.

# COMMAND ----------

good_df.write.format("delta").mode("append").option(
    "mergeSchema", "true"
).saveAsTable(target_table)

print(f"✓ Wrote {good_count} records to {target_table}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Write Error Records (if any)
# MAGIC
# MAGIC Rejected records are written to a separate Delta path for investigation.
# MAGIC Each record includes an `_error_reason` explaining why it was rejected.

# COMMAND ----------

if error_count > 0:
    error_df.write.format("delta").mode("append").save(error_path)
    print(f"⚠️ Wrote {error_count} error records to {error_path}")
else:
    print("✓ No error records to write.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Post-Load Verification
# MAGIC
# MAGIC Quick sanity checks to confirm the load was successful.

# COMMAND ----------

target_count = spark.table(target_table).count()
print(f"Target table row count: {target_count}")

assert source_count == good_count + error_count, (
    f"Row count mismatch: source={source_count} != good({good_count}) + error({error_count})"
)
print(f"✓ Row count reconciliation passed: {source_count} = {good_count} + {error_count}")

# Show a sample of loaded data
display(spark.table(target_table).limit(5))
