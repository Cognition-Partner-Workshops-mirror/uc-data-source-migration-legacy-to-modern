# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Notebook 01: Ingest Borrowers
# MAGIC **Source:** `CDW_BORR_MSTR` (Legacy Corporate Data Warehouse)
# MAGIC **Target:** `loan_warehouse.borrowers` (Delta Lake)
# MAGIC
# MAGIC This notebook reads the legacy borrower master table — where every column is `VARCHAR` —
# MAGIC and transforms it into a properly typed, normalized Delta Lake table.
# MAGIC
# MAGIC ### Anomalies Handled
# MAGIC | ID | Anomaly | Severity |
# MAGIC |----|---------|----------|
# MAGIC | ANO-001 | Numeric amounts stored as strings with commas (`"92,500"`) | Critical |
# MAGIC | ANO-002 | Dates in `MM/DD/YYYY` string format with no validation | Critical |
# MAGIC | ANO-004 | Status code abbreviations (`ACT`, `INA`) | High |
# MAGIC | ANO-006 | Null values in required fields | High |
# MAGIC | ANO-007 | Credit score stored as VARCHAR — range and parse risk | High |
# MAGIC | ANO-012 | Duplicate/near-duplicate borrower records | Low |

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Configuration
# MAGIC Define source paths, target tables, and the run ID for traceability.

# COMMAND ----------

from datetime import datetime

SOURCE_PATH = "/mnt/legacy-cdw/CDW_BORR_MSTR"
SOURCE_FORMAT = "csv"  # Change to "parquet" if legacy data is exported as Parquet
TARGET_TABLE = "loan_warehouse.borrowers"
DQ_LOG_TABLE = "loan_warehouse.data_quality_log"
RUN_ID = f"borrower_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

print(f"Run ID: {RUN_ID}")
print(f"Source: {SOURCE_PATH} ({SOURCE_FORMAT})")
print(f"Target: {TARGET_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Define Legacy Schema
# MAGIC The legacy `CDW_BORR_MSTR` table stores **every column as VARCHAR**.
# MAGIC We define the schema explicitly to avoid Spark's type inference (which could
# MAGIC misinterpret comma-formatted numbers or date strings).

# COMMAND ----------

from pyspark.sql.types import StructType, StructField, StringType

LEGACY_SCHEMA = StructType([
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

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Read Source Data
# MAGIC Read the legacy CSV (or Parquet) with our explicit schema. We preview a few rows
# MAGIC to visually inspect the raw data before transformation.

# COMMAND ----------

if SOURCE_FORMAT == "csv":
    source_df = (
        spark.read
        .schema(LEGACY_SCHEMA)
        .option("header", "true")
        .option("quote", '"')
        .csv(SOURCE_PATH)
    )
else:
    source_df = spark.read.parquet(SOURCE_PATH)

source_count = source_df.count()
print(f"Source rows: {source_count}")
display(source_df.limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Define Transformation Helpers
# MAGIC These reusable functions handle the core type conversions:
# MAGIC
# MAGIC - **`parse_legacy_date`**: Converts `MM/DD/YYYY` strings to Spark `DateType`.
# MAGIC   Falls back to ISO format (`YYYY-MM-DD`) for records that may have been migrated.
# MAGIC   Returns `null` (not dropped) on failure so the record is preserved.
# MAGIC
# MAGIC - **`parse_legacy_amount`**: Strips `$`, commas, and whitespace from amount strings
# MAGIC   like `"92,500"` or `"$1,487.02"`, then casts to `DECIMAL(12,2)`.
# MAGIC
# MAGIC - **`expand_status`**: Maps abbreviations to human-readable values using a lookup map.
# MAGIC   Unrecognized codes pass through as uppercase (logged later as anomalies).

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, IntegerType

def parse_legacy_date(col_name, alias):
    """ANO-002: Parse date strings with MM/dd/yyyy primary, yyyy-MM-dd fallback."""
    return F.coalesce(
        F.to_date(F.col(col_name), "MM/dd/yyyy"),
        F.to_date(F.col(col_name), "yyyy-MM-dd"),
    ).alias(alias)

def parse_legacy_amount(col_name, alias):
    """ANO-001: Strip $, commas, whitespace and cast to DECIMAL."""
    cleaned = F.regexp_replace(F.col(col_name), r"[$,\s]", "")
    return cleaned.cast(DecimalType(12, 2)).alias(alias)

def expand_status(col_name, mapping, alias):
    """ANO-004: Expand status abbreviations via a lookup map."""
    mapping_expr = F.create_map(
        *[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    upper_col = F.upper(F.trim(F.col(col_name)))
    return F.coalesce(mapping_expr[upper_col], upper_col).alias(alias)

STATUS_MAP = {"ACT": "ACTIVE", "INA": "INACTIVE"}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Apply Transformations
# MAGIC Transform every column from its legacy VARCHAR representation to the modern typed schema:
# MAGIC
# MAGIC | Legacy Column | Modern Column | Transformation |
# MAGIC |---------------|---------------|----------------|
# MAGIC | `BORR_ID` | `external_id` | Direct copy |
# MAGIC | `BORR_FST_NM` | `first_name` | Trim whitespace |
# MAGIC | `BORR_DOB_DT` | `date_of_birth` | Parse `MM/DD/YYYY` → `DATE` |
# MAGIC | `BORR_ANN_INCM` | `annual_income` | Strip commas → `DECIMAL(12,2)` |
# MAGIC | `BORR_CRDT_SCR` | `credit_score` | Cast to `INT`, validate 300-850 |
# MAGIC | `BORR_STAT_CD` | `status` | `ACT` → `ACTIVE`, `INA` → `INACTIVE` |
# MAGIC | `BORR_CRET_DT` | `created_at` | Parse → `TIMESTAMP` |
# MAGIC | `BORR_REC_TYP` | *(dropped)* | Not needed in modern schema |

# COMMAND ----------

transformed_df = source_df.select(
    F.col("BORR_ID").alias("external_id"),
    F.trim(F.col("BORR_FST_NM")).alias("first_name"),
    F.trim(F.col("BORR_LST_NM")).alias("last_name"),
    F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
    F.col("BORR_SSN_ENCR").alias("ssn_hash"),
    parse_legacy_date("BORR_DOB_DT", "date_of_birth"),
    F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
    F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
    F.trim(F.col("BORR_CTY_NM")).alias("city"),
    F.trim(F.col("BORR_ST_CD")).alias("state"),
    F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),
    F.trim(F.col("BORR_PH_NBR")).alias("phone"),
    F.trim(F.col("BORR_EMAIL_ADDR")).alias("email"),
    # ANO-007: Cast credit score to INT; out-of-range values kept but flagged
    F.col("BORR_CRDT_SCR").cast(IntegerType()).alias("credit_score"),
    F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),
    parse_legacy_amount("BORR_ANN_INCM", "annual_income"),
    expand_status("BORR_STAT_CD", STATUS_MAP, "status"),
    F.coalesce(
        F.to_timestamp(F.col("BORR_CRET_DT"), "MM/dd/yyyy"),
        F.to_timestamp(F.col("BORR_CRET_DT"), "yyyy-MM-dd"),
        F.current_timestamp()
    ).alias("created_at"),
    F.coalesce(
        F.to_timestamp(F.col("BORR_UPDT_DT"), "MM/dd/yyyy"),
        F.to_timestamp(F.col("BORR_UPDT_DT"), "yyyy-MM-dd"),
        F.current_timestamp()
    ).alias("updated_at"),
    F.current_timestamp().alias("_ingestion_ts"),
    F.lit("CDW").alias("_source_system"),
)

print(f"Transformed rows: {transformed_df.count()}")
display(transformed_df.limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Detect Data Quality Anomalies
# MAGIC Before writing to the target, we scan for known anomalies and log them to
# MAGIC `loan_warehouse.data_quality_log`. This ensures we have a complete audit trail
# MAGIC of every data quality issue — nothing is silently dropped.
# MAGIC
# MAGIC ### Checks performed:
# MAGIC 1. **ANO-006**: Null/blank values in required fields (`BORR_ID`, `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_ENCR`)
# MAGIC 2. **ANO-002**: Dates that cannot be parsed by either `MM/dd/yyyy` or `yyyy-MM-dd`
# MAGIC 3. **ANO-007**: Credit scores that are non-numeric or outside the valid 300-850 range
# MAGIC 4. **ANO-001**: Annual income values that cannot be parsed to `DECIMAL`
# MAGIC 5. **ANO-012**: Duplicate borrowers (same first name + last name + date of birth)

# COMMAND ----------

from functools import reduce
from pyspark.sql import DataFrame

anomalies = []

# --- ANO-006: Null required fields ---
null_checks = {
    "BORR_ID": "external_id",
    "BORR_FST_NM": "first_name",
    "BORR_LST_NM": "last_name",
    "BORR_SSN_ENCR": "ssn_hash",
}
for legacy_col, modern_col in null_checks.items():
    null_records = source_df.filter(
        F.col(legacy_col).isNull() | (F.trim(F.col(legacy_col)) == "")
    ).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_BORR_MSTR").alias("source_table"),
        F.coalesce(F.col("BORR_ID"), F.lit("UNKNOWN")).alias("source_record_id"),
        F.lit(legacy_col).alias("column_name"),
        F.lit("NULL_REQUIRED").alias("anomaly_type"),
        F.lit("CRITICAL").alias("severity"),
        F.lit(f"Required field {legacy_col} is null/blank").alias("description"),
        F.col(legacy_col).alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(null_records)

# --- ANO-002: Unparseable dates ---
date_cols = ["BORR_DOB_DT", "BORR_CRET_DT", "BORR_UPDT_DT"]
for col_name in date_cols:
    bad_dates = source_df.filter(
        F.col(col_name).isNotNull()
        & F.to_date(F.col(col_name), "MM/dd/yyyy").isNull()
        & F.to_date(F.col(col_name), "yyyy-MM-dd").isNull()
    ).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_BORR_MSTR").alias("source_table"),
        F.col("BORR_ID").alias("source_record_id"),
        F.lit(col_name).alias("column_name"),
        F.lit("PARSE_FAILURE").alias("anomaly_type"),
        F.lit("HIGH").alias("severity"),
        F.lit(f"Date value in {col_name} could not be parsed").alias("description"),
        F.col(col_name).alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(bad_dates)

# --- ANO-007: Credit score out of range ---
score_col = F.col("BORR_CRDT_SCR").cast(IntegerType())
bad_scores = source_df.filter(
    F.col("BORR_CRDT_SCR").isNotNull()
    & (score_col.isNull() | ~score_col.between(300, 850))
).select(
    F.lit(RUN_ID).alias("run_id"),
    F.lit("CDW_BORR_MSTR").alias("source_table"),
    F.col("BORR_ID").alias("source_record_id"),
    F.lit("BORR_CRDT_SCR").alias("column_name"),
    F.lit("BUSINESS_RULE").alias("anomaly_type"),
    F.lit("HIGH").alias("severity"),
    F.lit("Credit score is non-numeric or outside 300-850 range").alias("description"),
    F.col("BORR_CRDT_SCR").alias("original_value"),
    F.lit(None).cast(StringType()).alias("corrected_value"),
    F.current_timestamp().alias("detected_at"),
)
anomalies.append(bad_scores)

# --- ANO-001: Unparseable amounts ---
cleaned_income = F.regexp_replace(F.col("BORR_ANN_INCM"), r"[$,\s]", "")
bad_amounts = source_df.filter(
    F.col("BORR_ANN_INCM").isNotNull()
    & cleaned_income.cast(DecimalType(12, 2)).isNull()
).select(
    F.lit(RUN_ID).alias("run_id"),
    F.lit("CDW_BORR_MSTR").alias("source_table"),
    F.col("BORR_ID").alias("source_record_id"),
    F.lit("BORR_ANN_INCM").alias("column_name"),
    F.lit("PARSE_FAILURE").alias("anomaly_type"),
    F.lit("CRITICAL").alias("severity"),
    F.lit("Annual income value could not be parsed to decimal").alias("description"),
    F.col("BORR_ANN_INCM").alias("original_value"),
    F.lit(None).cast(StringType()).alias("corrected_value"),
    F.current_timestamp().alias("detected_at"),
)
anomalies.append(bad_amounts)

# --- ANO-012: Duplicate detection (same name + DOB) ---
dupes = (
    source_df
    .groupBy(
        F.upper(F.trim(F.col("BORR_FST_NM"))),
        F.upper(F.trim(F.col("BORR_LST_NM"))),
        F.col("BORR_DOB_DT")
    )
    .agg(F.count("*").alias("cnt"), F.collect_list("BORR_ID").alias("ids"))
    .filter(F.col("cnt") > 1)
)
if dupes.count() > 0:
    dupe_records = dupes.select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_BORR_MSTR").alias("source_table"),
        F.concat_ws(",", F.col("ids")).alias("source_record_id"),
        F.lit("BORR_FST_NM+BORR_LST_NM+BORR_DOB_DT").alias("column_name"),
        F.lit("DUPLICATE").alias("anomaly_type"),
        F.lit("LOW").alias("severity"),
        F.lit("Potential duplicate borrowers detected").alias("description"),
        F.concat_ws(",", F.col("ids")).alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(dupe_records)

# Union all anomalies
anomaly_df = reduce(DataFrame.unionByName, anomalies)
anomaly_count = anomaly_df.count()
print(f"Anomalies detected: {anomaly_count}")
if anomaly_count > 0:
    display(anomaly_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Write Anomalies to Data Quality Log
# MAGIC Append all detected anomalies to the centralized `data_quality_log` table
# MAGIC for post-migration review and audit.

# COMMAND ----------

if anomaly_count > 0:
    anomaly_df.write.mode("append").saveAsTable(DQ_LOG_TABLE)
    print(f"Wrote {anomaly_count} anomaly records to {DQ_LOG_TABLE}")
else:
    print("No anomalies to write.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8: Write to Target Table (MERGE)
# MAGIC Use `MERGE INTO` for idempotent writes — re-running this notebook updates
# MAGIC existing records and inserts new ones. The merge key is `external_id`
# MAGIC (the legacy `BORR_ID`).

# COMMAND ----------

transformed_df.createOrReplaceTempView("borrowers_staging")

spark.sql(f"""
    MERGE INTO {TARGET_TABLE} AS target
    USING borrowers_staging AS source
    ON target.external_id = source.external_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")

target_count = spark.table(TARGET_TABLE).count()
print(f"Target rows after merge: {target_count}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9: Verify Results
# MAGIC Quick sanity checks: compare source vs target counts, preview the target table,
# MAGIC and summarize any type conversion issues.

# COMMAND ----------

print(f"Source count: {source_count}")
print(f"Target count: {target_count}")
print(f"Anomalies:    {anomaly_count}")

if source_count == target_count:
    print("ROW COUNT CHECK: PASS")
elif target_count > source_count:
    print(f"ROW COUNT CHECK: WARN — target has {target_count - source_count} extra rows (prior run data?)")
else:
    print(f"ROW COUNT CHECK: FAIL — missing {source_count - target_count} rows")

display(spark.table(TARGET_TABLE).limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC | Metric | Value |
# MAGIC |--------|-------|
# MAGIC | Source rows | `{source_count}` |
# MAGIC | Target rows | `{target_count}` |
# MAGIC | Anomalies detected | `{anomaly_count}` |
# MAGIC
# MAGIC **Next step:** Run `02_ingest_loan_products` notebook.
