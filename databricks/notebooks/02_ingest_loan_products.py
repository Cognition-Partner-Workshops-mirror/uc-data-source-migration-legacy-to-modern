# Databricks notebook source

# MAGIC %md
# MAGIC # Loan Product Ingestion — CDW_LN_PROD → loan_warehouse.loan_products
# MAGIC
# MAGIC This notebook ingests the legacy **CDW_LN_PROD** (Loan Products) table into the
# MAGIC modern Delta Lake **loan_products** reference table.
# MAGIC
# MAGIC ### Legacy Table Characteristics
# MAGIC | Issue | Detail |
# MAGIC |-------|--------|
# MAGIC | All VARCHAR columns | Term months, min/max amounts stored as strings |
# MAGIC | Cryptic names | `PROD_CD`, `PROD_DESC_TXT`, `PROD_TYP_CD` |
# MAGIC | Status abbreviation | `ACT` / `INA` instead of boolean |
# MAGIC | Date format | `MM/DD/YYYY` stored as VARCHAR(10) |
# MAGIC | Amounts with commas | `"1,500,000"` stored as VARCHAR(15) |
# MAGIC
# MAGIC ### Transformation Summary
# MAGIC 1. Schema validation & quarantine of rows missing required fields
# MAGIC 2. Parse date strings → `DateType`
# MAGIC 3. Parse amount strings (strip commas) → `DecimalType`
# MAGIC 4. Parse term months string → `IntegerType`
# MAGIC 5. Convert status code to boolean (`ACT` → `true`, `INA` → `false`)
# MAGIC 6. Rename cryptic column names to readable names

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Configuration

# COMMAND ----------

dbutils.widgets.text("source_path", "/mnt/legacy-extract/cdw_ln_prod/", "Source Path")
dbutils.widgets.dropdown("file_format", "csv", ["csv", "parquet"], "File Format")
dbutils.widgets.text("target_table", "loan_warehouse.loan_products", "Target Table")
dbutils.widgets.text("quarantine_path", "/mnt/quarantine/loan_products/", "Quarantine Path")

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
# MAGIC The legacy `CDW_LN_PROD` table is a small reference table (typically < 100 rows).
# MAGIC All columns arrive as strings.

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
display(raw_df.limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — Schema Validation
# MAGIC Ensure all expected columns from CDW_LN_PROD are present.

# COMMAND ----------

EXPECTED_COLUMNS = [
    "PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD", "PROD_TERM_MOS",
    "PROD_RT_TYP", "PROD_MIN_AMT", "PROD_MAX_AMT", "PROD_STAT_CD",
    "PROD_EFF_DT", "PROD_EXP_DT",
]

missing = set(EXPECTED_COLUMNS) - set(raw_df.columns)
if missing:
    raise ValueError(f"Source is missing expected columns: {sorted(missing)}")

print("Schema validation passed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Quarantine Bad Rows
# MAGIC Required fields: `PROD_CD`, `PROD_DESC_TXT`, `PROD_TYP_CD`.
# MAGIC Rows missing any of these are quarantined.

# COMMAND ----------

from pyspark.sql import functions as F

REQUIRED_FIELDS = ["PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD"]

condition = F.lit(True)
for col_name in REQUIRED_FIELDS:
    condition = condition & F.col(col_name).isNotNull() & (F.trim(F.col(col_name)) != "")

good_df = raw_df.filter(condition)
quarantine_df = raw_df.filter(~condition)

good_count = good_df.count()
quarantine_count = quarantine_df.count()
print(f"Good rows:        {good_count}")
print(f"Quarantined rows: {quarantine_count}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5 — Parse Date Columns
# MAGIC Convert `MM/DD/YYYY` strings to proper `DateType`:
# MAGIC - `PROD_EFF_DT` → `effective_date`
# MAGIC - `PROD_EXP_DT` → `expiration_date`

# COMMAND ----------

from pyspark.sql.types import DateType

good_df = good_df.withColumn("_raw_effective_date", F.col("PROD_EFF_DT"))
good_df = good_df.withColumn("effective_date", F.to_date(F.col("PROD_EFF_DT"), "MM/dd/yyyy").cast(DateType()))

good_df = good_df.withColumn("_raw_expiration_date", F.col("PROD_EXP_DT"))
good_df = good_df.withColumn("expiration_date", F.to_date(F.col("PROD_EXP_DT"), "MM/dd/yyyy").cast(DateType()))

display(good_df.select("PROD_EFF_DT", "effective_date", "PROD_EXP_DT", "expiration_date").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6 — Parse Numeric Columns
# MAGIC - `PROD_TERM_MOS` → `term_months` (`IntegerType`) — e.g. `"360"` → `360`
# MAGIC - `PROD_MIN_AMT` → `min_amount` (`DecimalType(12,2)`) — e.g. `"50,000"` → `50000.00`
# MAGIC - `PROD_MAX_AMT` → `max_amount` (`DecimalType(12,2)`) — e.g. `"1,500,000"` → `1500000.00`

# COMMAND ----------

from pyspark.sql.types import DecimalType, IntegerType

good_df = good_df.withColumn("_raw_term_months", F.col("PROD_TERM_MOS"))
good_df = good_df.withColumn("term_months", F.col("PROD_TERM_MOS").cast(IntegerType()))

good_df = good_df.withColumn("_raw_min_amount", F.col("PROD_MIN_AMT"))
good_df = good_df.withColumn(
    "min_amount",
    F.regexp_replace(F.col("PROD_MIN_AMT"), ",", "").cast(DecimalType(12, 2)),
)

good_df = good_df.withColumn("_raw_max_amount", F.col("PROD_MAX_AMT"))
good_df = good_df.withColumn(
    "max_amount",
    F.regexp_replace(F.col("PROD_MAX_AMT"), ",", "").cast(DecimalType(12, 2)),
)

display(good_df.select("PROD_TERM_MOS", "term_months", "PROD_MIN_AMT", "min_amount", "PROD_MAX_AMT", "max_amount").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7 — Convert Status Code to Boolean
# MAGIC Unlike other tables where status codes expand to strings, loan products
# MAGIC use a boolean `is_active` flag:
# MAGIC
# MAGIC | Legacy Code | Modern Value |
# MAGIC |-------------|-------------|
# MAGIC | `ACT` | `true` |
# MAGIC | `INA` | `false` |

# COMMAND ----------

PRODUCT_STATUS_MAP = {"ACT": "True", "INA": "False"}
map_expr = F.create_map([F.lit(x) for kv in PRODUCT_STATUS_MAP.items() for x in kv])

good_df = good_df.withColumn(
    "is_active",
    F.when(map_expr[F.upper(F.col("PROD_STAT_CD"))] == "True", F.lit(True))
    .when(map_expr[F.upper(F.col("PROD_STAT_CD"))] == "False", F.lit(False))
    .otherwise(F.lit(None).cast("boolean")),
)

display(good_df.select("PROD_STAT_CD", "is_active").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8 — Rename Direct-Copy Columns
# MAGIC | Legacy | Modern |
# MAGIC |--------|--------|
# MAGIC | `PROD_CD` | `code` |
# MAGIC | `PROD_DESC_TXT` | `name` |
# MAGIC | `PROD_TYP_CD` | `type` |
# MAGIC | `PROD_RT_TYP` | `rate_type` |

# COMMAND ----------

good_df = (
    good_df
    .withColumnRenamed("PROD_CD", "code")
    .withColumnRenamed("PROD_DESC_TXT", "name")
    .withColumnRenamed("PROD_TYP_CD", "type")
    .withColumnRenamed("PROD_RT_TYP", "rate_type")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9 — Add Ingestion Audit Columns & Write

# COMMAND ----------

good_df = (
    good_df
    .withColumn("_ingestion_ts", F.current_timestamp())
    .withColumn("_source_system", F.lit("CDW_LN_PROD"))
)

FINAL_COLUMNS = [
    "code", "name", "type", "term_months", "rate_type",
    "min_amount", "max_amount", "is_active",
    "effective_date", "expiration_date",
    "_ingestion_ts", "_source_system",
]

final_df = good_df.select(*FINAL_COLUMNS)
display(final_df.limit(10))

# COMMAND ----------

final_df.write.format("delta").mode("overwrite").saveAsTable(target_table)
print(f"Wrote {final_df.count()} rows to {target_table}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10 — Persist Quarantined Rows

# COMMAND ----------

if quarantine_count > 0:
    quarantine_df.write.format("delta").mode("overwrite").save(quarantine_path)
    print(f"Wrote {quarantine_count} quarantined rows to {quarantine_path}")
else:
    print("No quarantined rows.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC | Metric | Value |
# MAGIC |--------|-------|
# MAGIC | Source rows | see output above |
# MAGIC | Loaded rows | `{good_count}` |
# MAGIC | Quarantined rows | `{quarantine_count}` |
# MAGIC | Target table | `loan_warehouse.loan_products` |
# MAGIC | Partitioning | None (small reference table) |
