# Databricks notebook source

# MAGIC %md
# MAGIC # Borrower Ingestion — CDW_BORR_MSTR → loan_warehouse.borrowers
# MAGIC
# MAGIC This notebook ingests the legacy **CDW_BORR_MSTR** (Borrower Master) table into the
# MAGIC modern Delta Lake **borrowers** dimension table.
# MAGIC
# MAGIC ### Legacy Table Characteristics
# MAGIC | Issue | Detail |
# MAGIC |-------|--------|
# MAGIC | All VARCHAR columns | Dates, numbers, and codes stored as plain strings |
# MAGIC | Cryptic names | `BORR_FST_NM`, `BORR_CRDT_SCR`, `BORR_ANN_INCM` |
# MAGIC | Status abbreviations | `ACT` → Active, `INA` → Inactive |
# MAGIC | Date format | `MM/DD/YYYY` stored as VARCHAR(10) |
# MAGIC | Amounts with commas | `"92,500"` stored as VARCHAR(15) |
# MAGIC
# MAGIC ### Transformation Summary
# MAGIC 1. Schema validation & quarantine of rows missing required fields
# MAGIC 2. Parse date strings (`MM/DD/YYYY`) → `DateType` / `TimestampType`
# MAGIC 3. Parse amount strings (strip commas) → `DecimalType`
# MAGIC 4. Parse credit score string → `IntegerType`
# MAGIC 5. Expand status codes (`ACT` → `ACTIVE`, `INA` → `INACTIVE`)
# MAGIC 6. Drop `BORR_REC_TYP` (not needed in modern schema)
# MAGIC 7. Add ingestion audit columns (`_ingestion_ts`, `_source_system`)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Configuration
# MAGIC Set the source file path, target table, and file format. Adjust these
# MAGIC widgets when running in different environments.

# COMMAND ----------

dbutils.widgets.text("source_path", "/mnt/legacy-extract/cdw_borr_mstr/", "Source Path")
dbutils.widgets.dropdown("file_format", "csv", ["csv", "parquet"], "File Format")
dbutils.widgets.text("target_table", "loan_warehouse.borrowers", "Target Table")
dbutils.widgets.text("quarantine_path", "/mnt/quarantine/borrowers/", "Quarantine Path")

source_path = dbutils.widgets.get("source_path")
file_format = dbutils.widgets.get("file_format")
target_table = dbutils.widgets.get("target_table")
quarantine_path = dbutils.widgets.get("quarantine_path")

print(f"Source:     {source_path}")
print(f"Format:     {file_format}")
print(f"Target:     {target_table}")
print(f"Quarantine: {quarantine_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — Read Source Data
# MAGIC Read the legacy CSV/Parquet extract. All columns arrive as strings because
# MAGIC the legacy warehouse stored everything as VARCHAR.

# COMMAND ----------

if file_format == "parquet":
    raw_df = spark.read.parquet(source_path)
else:
    raw_df = (
        spark.read
        .option("header", "true")
        .option("inferSchema", "false")
        .csv(source_path)
    )

print(f"Source row count: {raw_df.count()}")
raw_df.printSchema()
display(raw_df.limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — Schema Validation
# MAGIC Verify that all expected legacy columns are present. If the extract is
# MAGIC missing columns the pipeline fails fast rather than producing corrupt data.

# COMMAND ----------

EXPECTED_COLUMNS = [
    "BORR_ID", "BORR_FST_NM", "BORR_LST_NM", "BORR_MID_INIT",
    "BORR_SSN_ENCR", "BORR_DOB_DT", "BORR_ADDR_LN1", "BORR_ADDR_LN2",
    "BORR_CTY_NM", "BORR_ST_CD", "BORR_ZIP_CD", "BORR_PH_NBR",
    "BORR_EMAIL_ADDR", "BORR_CRDT_SCR", "BORR_EMP_STAT", "BORR_ANN_INCM",
    "BORR_CRET_DT", "BORR_UPDT_DT", "BORR_STAT_CD", "BORR_REC_TYP",
]

missing = set(EXPECTED_COLUMNS) - set(raw_df.columns)
if missing:
    raise ValueError(f"Source is missing expected columns: {sorted(missing)}")

print("Schema validation passed — all expected columns present.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Quarantine Bad Rows
# MAGIC Rows missing **required** fields (`BORR_ID`, `BORR_FST_NM`, `BORR_LST_NM`)
# MAGIC are separated into a quarantine DataFrame. They are persisted for review
# MAGIC rather than silently dropped.

# COMMAND ----------

from pyspark.sql import functions as F

REQUIRED_FIELDS = ["BORR_ID", "BORR_FST_NM", "BORR_LST_NM"]

condition = F.lit(True)
for col_name in REQUIRED_FIELDS:
    condition = condition & F.col(col_name).isNotNull() & (F.trim(F.col(col_name)) != "")

good_df = raw_df.filter(condition)
quarantine_df = raw_df.filter(~condition)

good_count = good_df.count()
quarantine_count = quarantine_df.count()
print(f"Good rows:        {good_count}")
print(f"Quarantined rows: {quarantine_count}")

if quarantine_count > 0:
    display(quarantine_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5 — Parse Date Columns
# MAGIC The legacy system stores dates as `MM/DD/YYYY` strings. We convert:
# MAGIC - `BORR_DOB_DT` → `date_of_birth` (`DateType`)
# MAGIC - `BORR_CRET_DT` → `created_at` (`TimestampType`)
# MAGIC - `BORR_UPDT_DT` → `updated_at` (`TimestampType`)
# MAGIC
# MAGIC Malformed values become `NULL`; the raw string is preserved in `_raw_*`
# MAGIC columns for auditability.

# COMMAND ----------

from pyspark.sql.types import DateType, TimestampType

# date_of_birth
good_df = good_df.withColumn("_raw_date_of_birth", F.col("BORR_DOB_DT"))
good_df = good_df.withColumn("date_of_birth", F.to_date(F.col("BORR_DOB_DT"), "MM/dd/yyyy").cast(DateType()))

# created_at
good_df = good_df.withColumn("_raw_created_at", F.col("BORR_CRET_DT"))
good_df = good_df.withColumn("created_at", F.to_timestamp(F.col("BORR_CRET_DT"), "MM/dd/yyyy").cast(TimestampType()))

# updated_at
good_df = good_df.withColumn("_raw_updated_at", F.col("BORR_UPDT_DT"))
good_df = good_df.withColumn("updated_at", F.to_timestamp(F.col("BORR_UPDT_DT"), "MM/dd/yyyy").cast(TimestampType()))

# Show a sample to verify parsing
display(good_df.select("BORR_DOB_DT", "date_of_birth", "BORR_CRET_DT", "created_at").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6 — Parse Numeric Columns
# MAGIC Legacy amounts are stored with commas (e.g. `"92,500"`). We strip commas
# MAGIC and cast to the appropriate numeric type:
# MAGIC - `BORR_CRDT_SCR` → `credit_score` (`IntegerType`)
# MAGIC - `BORR_ANN_INCM` → `annual_income` (`DecimalType(12,2)`)

# COMMAND ----------

from pyspark.sql.types import DecimalType, IntegerType

# credit_score (string → integer)
good_df = good_df.withColumn("_raw_credit_score", F.col("BORR_CRDT_SCR"))
good_df = good_df.withColumn("credit_score", F.col("BORR_CRDT_SCR").cast(IntegerType()))

# annual_income (string with commas → decimal)
good_df = good_df.withColumn("_raw_annual_income", F.col("BORR_ANN_INCM"))
good_df = good_df.withColumn(
    "annual_income",
    F.regexp_replace(F.col("BORR_ANN_INCM"), ",", "").cast(DecimalType(12, 2)),
)

display(good_df.select("BORR_CRDT_SCR", "credit_score", "BORR_ANN_INCM", "annual_income").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7 — Expand Status Codes
# MAGIC The legacy `BORR_STAT_CD` uses abbreviations. We expand them to readable
# MAGIC values using a mapping dictionary:
# MAGIC
# MAGIC | Legacy Code | Modern Value |
# MAGIC |-------------|-------------|
# MAGIC | `ACT` | `ACTIVE` |
# MAGIC | `INA` | `INACTIVE` |
# MAGIC
# MAGIC Unrecognised codes are preserved as-is and flagged.

# COMMAND ----------

BORROWER_STATUS_MAP = {"ACT": "ACTIVE", "INA": "INACTIVE"}

map_expr = F.create_map([F.lit(x) for kv in BORROWER_STATUS_MAP.items() for x in kv])
good_df = good_df.withColumn(
    "status",
    F.coalesce(map_expr[F.upper(F.col("BORR_STAT_CD"))], F.col("BORR_STAT_CD")),
)
good_df = good_df.withColumn(
    "_unmapped_status",
    F.when(map_expr[F.upper(F.col("BORR_STAT_CD"))].isNull() & F.col("BORR_STAT_CD").isNotNull(), F.lit(True))
    .otherwise(F.lit(False)),
)

unmapped_count = good_df.filter(F.col("_unmapped_status") == True).count()  # noqa: E712
print(f"Rows with unmapped status codes: {unmapped_count}")
display(good_df.select("BORR_STAT_CD", "status", "_unmapped_status").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8 — Rename Direct-Copy Columns
# MAGIC Columns that need no type conversion are simply renamed from their cryptic
# MAGIC legacy names to clear modern names per the column mapping specification.
# MAGIC
# MAGIC | Legacy | Modern |
# MAGIC |--------|--------|
# MAGIC | `BORR_FST_NM` | `first_name` |
# MAGIC | `BORR_LST_NM` | `last_name` |
# MAGIC | `BORR_MID_INIT` | `middle_initial` |
# MAGIC | `BORR_SSN_ENCR` | `ssn_hash` |
# MAGIC | `BORR_ADDR_LN1` | `address_line1` |
# MAGIC | `BORR_ADDR_LN2` | `address_line2` |
# MAGIC | `BORR_CTY_NM` | `city` |
# MAGIC | `BORR_ST_CD` | `state` |
# MAGIC | `BORR_ZIP_CD` | `zip_code` |
# MAGIC | `BORR_PH_NBR` | `phone` |
# MAGIC | `BORR_EMAIL_ADDR` | `email` |
# MAGIC | `BORR_EMP_STAT` | `employment_status` |
# MAGIC
# MAGIC `BORR_REC_TYP` is **dropped** — it is not needed in the modern schema.

# COMMAND ----------

good_df = (
    good_df
    .withColumnRenamed("BORR_ID", "external_id")
    .withColumnRenamed("BORR_FST_NM", "first_name")
    .withColumnRenamed("BORR_LST_NM", "last_name")
    .withColumnRenamed("BORR_MID_INIT", "middle_initial")
    .withColumnRenamed("BORR_SSN_ENCR", "ssn_hash")
    .withColumnRenamed("BORR_ADDR_LN1", "address_line1")
    .withColumnRenamed("BORR_ADDR_LN2", "address_line2")
    .withColumnRenamed("BORR_CTY_NM", "city")
    .withColumnRenamed("BORR_ST_CD", "state")
    .withColumnRenamed("BORR_ZIP_CD", "zip_code")
    .withColumnRenamed("BORR_PH_NBR", "phone")
    .withColumnRenamed("BORR_EMAIL_ADDR", "email")
    .withColumnRenamed("BORR_EMP_STAT", "employment_status")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9 — Add Ingestion Audit Columns
# MAGIC Every record gets two audit columns so downstream consumers know when and
# MAGIC from where each row was loaded:
# MAGIC - `_ingestion_ts` — timestamp of this pipeline run
# MAGIC - `_source_system` — fixed value `CDW_BORR_MSTR`

# COMMAND ----------

good_df = (
    good_df
    .withColumn("_ingestion_ts", F.current_timestamp())
    .withColumn("_source_system", F.lit("CDW_BORR_MSTR"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10 — Select Final Column Set & Write to Delta
# MAGIC We select only the target columns (dropping raw audit columns and legacy
# MAGIC names) and write to the Delta table, partitioned by `state`.

# COMMAND ----------

FINAL_COLUMNS = [
    "external_id", "first_name", "last_name", "middle_initial",
    "ssn_hash", "date_of_birth", "address_line1", "address_line2",
    "city", "state", "zip_code", "phone", "email", "credit_score",
    "employment_status", "annual_income", "status",
    "created_at", "updated_at",
    "_ingestion_ts", "_source_system",
]

final_df = good_df.select(*FINAL_COLUMNS)
display(final_df.limit(5))

# COMMAND ----------

final_df.write.format("delta").mode("overwrite").partitionBy("state").saveAsTable(target_table)
print(f"Wrote {final_df.count()} rows to {target_table}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 11 — Persist Quarantined Rows
# MAGIC Rows that failed required-field validation are written to the quarantine
# MAGIC path for manual review. They are **never silently dropped**.

# COMMAND ----------

if quarantine_count > 0:
    quarantine_df.write.format("delta").mode("overwrite").save(quarantine_path)
    print(f"Wrote {quarantine_count} quarantined rows to {quarantine_path}")
else:
    print("No quarantined rows — all source rows passed validation.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC | Metric | Value |
# MAGIC |--------|-------|
# MAGIC | Source rows | `{raw_df.count()}` |
# MAGIC | Loaded rows | `{good_count}` |
# MAGIC | Quarantined rows | `{quarantine_count}` |
# MAGIC | Target table | `loan_warehouse.borrowers` |
# MAGIC | Partition column | `state` |
