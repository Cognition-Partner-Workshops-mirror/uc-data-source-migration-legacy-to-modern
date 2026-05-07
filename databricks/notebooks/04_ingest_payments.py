# Databricks notebook source

# MAGIC %md
# MAGIC # Payment Ingestion — CDW_PMT_HIST → loan_warehouse.payments
# MAGIC
# MAGIC This notebook ingests the legacy **CDW_PMT_HIST** (Payment History) table into the
# MAGIC modern Delta Lake **payments** fact table.
# MAGIC
# MAGIC ### Legacy Table Characteristics
# MAGIC | Issue | Detail |
# MAGIC |-------|--------|
# MAGIC | All VARCHAR columns | Payment amounts, dates all stored as strings |
# MAGIC | Cryptic names | `PMT_SEQ_NBR`, `PMT_PRIN_AMT`, `PMT_ESCROW_AMT` |
# MAGIC | Payment type codes | `REG`/`EXT`/`PRT`/`PRE` |
# MAGIC | Payment status codes | `PST`/`REV`/`NSF`/`PND` |
# MAGIC | No FK constraints | `LN_ACCT_NBR` has no enforced relationship |
# MAGIC
# MAGIC ### Transformation Summary
# MAGIC 1. Schema validation & quarantine
# MAGIC 2. Resolve `LN_ACCT_NBR` → `loan_account_key` FK
# MAGIC 3. Parse 5 date columns
# MAGIC 4. Parse 5 amount columns (strip commas → `DecimalType`)
# MAGIC 5. Expand payment type and status codes
# MAGIC 6. Derive `payment_year` partition column

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Configuration

# COMMAND ----------

dbutils.widgets.text("source_path", "/mnt/legacy-extract/cdw_pmt_hist/", "Source Path")
dbutils.widgets.dropdown("file_format", "csv", ["csv", "parquet"], "File Format")
dbutils.widgets.text("target_table", "loan_warehouse.payments", "Target Table")
dbutils.widgets.text("loan_table", "loan_warehouse.loan_accounts", "Loan Accounts Table")
dbutils.widgets.text("quarantine_path", "/mnt/quarantine/payments/", "Quarantine Path")

source_path = dbutils.widgets.get("source_path")
file_format = dbutils.widgets.get("file_format")
target_table = dbutils.widgets.get("target_table")
loan_table = dbutils.widgets.get("loan_table")
quarantine_path = dbutils.widgets.get("quarantine_path")

print(f"Source:     {source_path}")
print(f"Target:     {target_table}")
print(f"Loan table: {loan_table}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — Read Source Data

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
display(raw_df.limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — Schema Validation

# COMMAND ----------

EXPECTED_COLUMNS = [
    "PMT_SEQ_NBR", "LN_ACCT_NBR", "PMT_DT", "PMT_AMT", "PMT_PRIN_AMT",
    "PMT_INT_AMT", "PMT_ESCROW_AMT", "PMT_LATE_FEE", "PMT_TYP_CD",
    "PMT_STAT_CD", "PMT_RECV_DT", "PMT_PROC_DT", "PMT_CRET_DT", "PMT_UPDT_DT",
]

missing = set(EXPECTED_COLUMNS) - set(raw_df.columns)
if missing:
    raise ValueError(f"Source is missing expected columns: {sorted(missing)}")
print("Schema validation passed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Quarantine Bad Rows
# MAGIC Required: `PMT_SEQ_NBR`, `LN_ACCT_NBR`, `PMT_DT`, `PMT_AMT`.

# COMMAND ----------

from pyspark.sql import functions as F

REQUIRED_FIELDS = ["PMT_SEQ_NBR", "LN_ACCT_NBR", "PMT_DT", "PMT_AMT"]

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
# MAGIC ## Step 5 — Resolve Loan Account Foreign Key
# MAGIC Look up `LN_ACCT_NBR` (e.g. `"LN-2019-00142"`) in the already-loaded
# MAGIC `loan_accounts` Delta table to get the surrogate `loan_account_key`.
# MAGIC Unmatched rows are logged but not dropped.

# COMMAND ----------

loans = spark.table(loan_table).select(
    F.col("loan_account_key"),
    F.col("account_number").alias("_ln_acct_nbr"),
)
good_df = good_df.join(loans, good_df["LN_ACCT_NBR"] == loans["_ln_acct_nbr"], "left")

unmatched = good_df.filter(F.col("loan_account_key").isNull()).count()
print(f"Unmatched loan account numbers: {unmatched}")

good_df = good_df.drop("_ln_acct_nbr")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6 — Parse Date Columns
# MAGIC Five date columns from `MM/DD/YYYY` strings:
# MAGIC
# MAGIC | Legacy | Modern | Type |
# MAGIC |--------|--------|------|
# MAGIC | `PMT_DT` | `payment_date` | DATE |
# MAGIC | `PMT_RECV_DT` | `received_date` | DATE |
# MAGIC | `PMT_PROC_DT` | `processed_date` | DATE |
# MAGIC | `PMT_CRET_DT` | `created_at` | TIMESTAMP |
# MAGIC | `PMT_UPDT_DT` | `updated_at` | TIMESTAMP |

# COMMAND ----------

from pyspark.sql.types import DateType, TimestampType

date_cols = [
    ("PMT_DT", "payment_date", DateType()),
    ("PMT_RECV_DT", "received_date", DateType()),
    ("PMT_PROC_DT", "processed_date", DateType()),
]

for src, tgt, dtype in date_cols:
    good_df = good_df.withColumn(f"_raw_{tgt}", F.col(src))
    good_df = good_df.withColumn(tgt, F.to_date(F.col(src), "MM/dd/yyyy").cast(dtype))

ts_cols = [("PMT_CRET_DT", "created_at"), ("PMT_UPDT_DT", "updated_at")]
for src, tgt in ts_cols:
    good_df = good_df.withColumn(f"_raw_{tgt}", F.col(src))
    good_df = good_df.withColumn(tgt, F.to_timestamp(F.col(src), "MM/dd/yyyy").cast(TimestampType()))

display(good_df.select("PMT_DT", "payment_date", "PMT_RECV_DT", "received_date").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7 — Parse Amount Columns
# MAGIC Five amount columns with commas stripped and cast to `DecimalType(10,2)`:
# MAGIC
# MAGIC | Legacy | Modern |
# MAGIC |--------|--------|
# MAGIC | `PMT_AMT` | `total_amount` |
# MAGIC | `PMT_PRIN_AMT` | `principal_amount` |
# MAGIC | `PMT_INT_AMT` | `interest_amount` |
# MAGIC | `PMT_ESCROW_AMT` | `escrow_amount` |
# MAGIC | `PMT_LATE_FEE` | `late_fee` |

# COMMAND ----------

from pyspark.sql.types import DecimalType

amount_cols = [
    ("PMT_AMT", "total_amount"),
    ("PMT_PRIN_AMT", "principal_amount"),
    ("PMT_INT_AMT", "interest_amount"),
    ("PMT_ESCROW_AMT", "escrow_amount"),
    ("PMT_LATE_FEE", "late_fee"),
]

for src, tgt in amount_cols:
    good_df = good_df.withColumn(f"_raw_{tgt}", F.col(src))
    good_df = good_df.withColumn(
        tgt,
        F.regexp_replace(F.col(src), ",", "").cast(DecimalType(10, 2)),
    )

display(good_df.select("PMT_AMT", "total_amount", "PMT_PRIN_AMT", "principal_amount").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8 — Expand Payment Type & Status Codes
# MAGIC
# MAGIC **Payment Type:**
# MAGIC | Code | Expanded |
# MAGIC |------|----------|
# MAGIC | `REG` | `REGULAR` |
# MAGIC | `EXT` | `EXTRA` |
# MAGIC | `PRT` | `PARTIAL` |
# MAGIC | `PRE` | `PREPAYMENT` |
# MAGIC
# MAGIC **Payment Status:**
# MAGIC | Code | Expanded |
# MAGIC |------|----------|
# MAGIC | `PST` | `POSTED` |
# MAGIC | `REV` | `REVERSED` |
# MAGIC | `NSF` | `NSF` |
# MAGIC | `PND` | `PENDING` |

# COMMAND ----------

PAYMENT_TYPE_MAP = {"REG": "REGULAR", "EXT": "EXTRA", "PRT": "PARTIAL", "PRE": "PREPAYMENT"}
PAYMENT_STATUS_MAP = {"PST": "POSTED", "REV": "REVERSED", "NSF": "NSF", "PND": "PENDING"}

for col_name, mapping, target_col in [
    ("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
    ("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
]:
    map_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])
    good_df = good_df.withColumn(
        target_col,
        F.coalesce(map_expr[F.upper(F.col(col_name))], F.col(col_name)),
    )

display(good_df.select("PMT_TYP_CD", "type", "PMT_STAT_CD", "status").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9 — Derive Payment Year, Add Audit Columns & Write
# MAGIC The `payment_year` column is derived from `payment_date` and used as the
# MAGIC partition key. This optimizes time-range queries (e.g. "all payments in 2025")
# MAGIC and supports data lifecycle policies (e.g. archive payments older than 7 years).

# COMMAND ----------

good_df = good_df.withColumn("payment_year", F.year(F.col("payment_date")))
good_df = good_df.withColumnRenamed("PMT_SEQ_NBR", "legacy_payment_id")

good_df = (
    good_df
    .withColumn("_ingestion_ts", F.current_timestamp())
    .withColumn("_source_system", F.lit("CDW_PMT_HIST"))
)

FINAL_COLUMNS = [
    "legacy_payment_id", "loan_account_key",
    "payment_date", "total_amount", "principal_amount",
    "interest_amount", "escrow_amount", "late_fee",
    "type", "status",
    "received_date", "processed_date", "payment_year",
    "created_at", "updated_at",
    "_ingestion_ts", "_source_system",
]

final_df = good_df.select(*FINAL_COLUMNS)
display(final_df.limit(5))

# COMMAND ----------

final_df.write.format("delta").mode("overwrite").partitionBy("payment_year").saveAsTable(target_table)
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
# MAGIC | Unmatched loan FKs | `{unmatched}` |
# MAGIC | Target table | `loan_warehouse.payments` |
# MAGIC | Partition column | `payment_year` |
