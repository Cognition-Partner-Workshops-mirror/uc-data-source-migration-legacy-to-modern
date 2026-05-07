# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Notebook 04: Ingest Payments
# MAGIC **Source:** `CDW_PMT_HIST` (Legacy Corporate Data Warehouse)
# MAGIC **Target:** `loan_warehouse.payments` (Delta Lake)
# MAGIC
# MAGIC This notebook reads the legacy payment history table and transforms it into a
# MAGIC properly typed Delta Lake table, partitioned by `payment_year` for efficient
# MAGIC time-range queries.
# MAGIC
# MAGIC ### Prerequisites
# MAGIC - **Notebook 03** (`ingest_loan_accounts`) must have been run first — we resolve
# MAGIC   `LN_ACCT_NBR` → `loan_account_id` via FK lookup.
# MAGIC
# MAGIC ### Anomalies Handled
# MAGIC | ID | Anomaly | Severity |
# MAGIC |----|---------|----------|
# MAGIC | ANO-001 | Numeric amounts as strings with commas | Critical |
# MAGIC | ANO-002 | Dates in `MM/DD/YYYY` string format | Critical |
# MAGIC | ANO-003 | No FK constraints — orphaned loan account references | Critical |
# MAGIC | ANO-004 | Payment type/status code abbreviations | High |
# MAGIC | ANO-006 | Null values in required fields | High |
# MAGIC | ANO-008 | Payment component amounts don't sum to total | Medium |

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Configuration

# COMMAND ----------

from datetime import datetime

SOURCE_PATH = "/mnt/legacy-cdw/CDW_PMT_HIST"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
LOAN_TABLE = "loan_warehouse.loan_accounts"
DQ_LOG_TABLE = "loan_warehouse.data_quality_log"
RUN_ID = f"payment_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

print(f"Run ID: {RUN_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Define Legacy Schema
# MAGIC The payment history table has 14 columns — all VARCHAR. Key patterns:
# MAGIC - 5 amount columns that contain commas (`PMT_AMT`, `PMT_PRIN_AMT`, etc.)
# MAGIC - 4 date columns in `MM/DD/YYYY` format
# MAGIC - 2 code columns (`PMT_TYP_CD`, `PMT_STAT_CD`) with abbreviations

# COMMAND ----------

from pyspark.sql.types import StructType, StructField, StringType

LEGACY_SCHEMA = StructType([
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

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Read Source Data

# COMMAND ----------

if SOURCE_FORMAT == "csv":
    source_df = (
        spark.read.schema(LEGACY_SCHEMA)
        .option("header", "true").csv(SOURCE_PATH)
    )
else:
    source_df = spark.read.parquet(SOURCE_PATH)

source_count = source_df.count()
print(f"Source rows: {source_count}")
display(source_df.limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Define Transformation Helpers
# MAGIC Same parsing functions as previous notebooks, plus payment-specific code maps.
# MAGIC
# MAGIC **Payment Type Codes:**
# MAGIC | Code | Expanded |
# MAGIC |------|----------|
# MAGIC | REG | REGULAR |
# MAGIC | EXT | EXTRA |
# MAGIC | PRT | PARTIAL |
# MAGIC | PRE | PREPAYMENT |
# MAGIC
# MAGIC **Payment Status Codes:**
# MAGIC | Code | Expanded |
# MAGIC |------|----------|
# MAGIC | PST | POSTED |
# MAGIC | REV | REVERSED |
# MAGIC | NSF | NSF (Non-Sufficient Funds) |
# MAGIC | PND | PENDING |

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
    return cleaned.cast(DecimalType(10, 2)).alias(alias)

def expand_status(col_name, mapping, alias):
    mapping_expr = F.create_map(
        *[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    upper_col = F.upper(F.trim(F.col(col_name)))
    return F.coalesce(mapping_expr[upper_col], upper_col).alias(alias)

PAYMENT_TYPE_MAP = {
    "REG": "REGULAR", "EXT": "EXTRA", "PRT": "PARTIAL", "PRE": "PREPAYMENT"
}
PAYMENT_STATUS_MAP = {
    "PST": "POSTED", "REV": "REVERSED", "NSF": "NSF", "PND": "PENDING"
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Resolve Foreign Keys
# MAGIC Look up `loan_account_id` from the loan accounts table using the legacy
# MAGIC `LN_ACCT_NBR` as the join key. Orphaned payments (referencing non-existent
# MAGIC loan accounts) will get `NULL` for `loan_account_id`.

# COMMAND ----------

loans = spark.table(LOAN_TABLE).select(
    F.col("loan_account_id"), F.col("account_number").alias("ln_acct_nbr")
)
print(f"Loan accounts available for FK resolution: {loans.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Apply Transformations
# MAGIC
# MAGIC | Legacy Column | Modern Column | Transformation |
# MAGIC |---------------|---------------|----------------|
# MAGIC | `PMT_SEQ_NBR` | `legacy_sequence_nbr` | Direct copy for traceability |
# MAGIC | `LN_ACCT_NBR` | `loan_account_id` | FK lookup → `BIGINT` |
# MAGIC | `PMT_DT` | `payment_date` | Parse `MM/DD/YYYY` → `DATE` |
# MAGIC | `PMT_AMT` | `total_amount` | Strip commas → `DECIMAL(10,2)` |
# MAGIC | `PMT_PRIN_AMT` | `principal_amount` | Strip commas → `DECIMAL(10,2)` |
# MAGIC | `PMT_INT_AMT` | `interest_amount` | Strip commas → `DECIMAL(10,2)` |
# MAGIC | `PMT_ESCROW_AMT` | `escrow_amount` | Strip commas → `DECIMAL(10,2)` |
# MAGIC | `PMT_LATE_FEE` | `late_fee` | Strip commas → `DECIMAL(10,2)` |
# MAGIC | `PMT_TYP_CD` | `type` | `REG` → `REGULAR`, etc. |
# MAGIC | `PMT_STAT_CD` | `status` | `PST` → `POSTED`, etc. |
# MAGIC | *(derived)* | `payment_year` | `YEAR(payment_date)` — partition key |

# COMMAND ----------

transformed_df = (
    source_df
    .join(loans, source_df["LN_ACCT_NBR"] == loans["ln_acct_nbr"], "left")
    .select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),
        F.col("loan_account_id"),
        parse_legacy_date("PMT_DT", "payment_date"),
        parse_legacy_amount("PMT_AMT", "total_amount"),
        parse_legacy_amount("PMT_PRIN_AMT", "principal_amount"),
        parse_legacy_amount("PMT_INT_AMT", "interest_amount"),
        parse_legacy_amount("PMT_ESCROW_AMT", "escrow_amount"),
        parse_legacy_amount("PMT_LATE_FEE", "late_fee"),
        expand_status("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        expand_status("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
        parse_legacy_date("PMT_RECV_DT", "received_date"),
        parse_legacy_date("PMT_PROC_DT", "processed_date"),
        F.coalesce(
            F.to_timestamp(F.col("PMT_CRET_DT"), "MM/dd/yyyy"),
            F.to_timestamp(F.col("PMT_CRET_DT"), "yyyy-MM-dd"),
            F.current_timestamp()
        ).alias("created_at"),
        F.coalesce(
            F.to_timestamp(F.col("PMT_UPDT_DT"), "MM/dd/yyyy"),
            F.to_timestamp(F.col("PMT_UPDT_DT"), "yyyy-MM-dd"),
            F.current_timestamp()
        ).alias("updated_at"),
        # Derive partition key from payment date
        F.year(
            F.coalesce(
                F.to_date(F.col("PMT_DT"), "MM/dd/yyyy"),
                F.to_date(F.col("PMT_DT"), "yyyy-MM-dd"),
            )
        ).alias("payment_year"),
        F.current_timestamp().alias("_ingestion_ts"),
        F.lit("CDW").alias("_source_system"),
    )
)

print(f"Transformed rows: {transformed_df.count()}")
display(transformed_df.limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Detect Data Quality Anomalies
# MAGIC
# MAGIC ### Checks:
# MAGIC 1. **ANO-003 — Orphaned loan references:** Payments where `LN_ACCT_NBR` doesn't match any loan account
# MAGIC 2. **ANO-008 — Payment reconciliation:** Component amounts (principal + interest + escrow + late fee) should equal the total amount. A delta > $0.02 is flagged.
# MAGIC 3. **ANO-006 — Null required fields:** `PMT_SEQ_NBR`, `LN_ACCT_NBR`, `PMT_AMT`, `PMT_STAT_CD`

# COMMAND ----------

from functools import reduce
from pyspark.sql import DataFrame

anomalies = []

# --- ANO-003: Orphaned loan account references ---
loan_accts = spark.table(LOAN_TABLE).select(
    F.col("account_number").alias("valid_ln_acct")
)
orphan_loans = (
    source_df
    .join(loan_accts, source_df["LN_ACCT_NBR"] == loan_accts["valid_ln_acct"], "left_anti")
    .filter(F.col("LN_ACCT_NBR").isNotNull())
    .select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_PMT_HIST").alias("source_table"),
        F.col("PMT_SEQ_NBR").alias("source_record_id"),
        F.lit("LN_ACCT_NBR").alias("column_name"),
        F.lit("FK_VIOLATION").alias("anomaly_type"),
        F.lit("CRITICAL").alias("severity"),
        F.concat(F.lit("Loan account "), F.col("LN_ACCT_NBR"),
                 F.lit(" not found in loan_accounts")).alias("description"),
        F.col("LN_ACCT_NBR").alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
)
anomalies.append(orphan_loans)

# COMMAND ----------

# MAGIC %md
# MAGIC ### ANO-008: Payment Reconciliation Check
# MAGIC For each payment, verify: `PMT_AMT ≈ PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`
# MAGIC
# MAGIC We allow a $0.02 tolerance for floating-point rounding. In the legacy seed data,
# MAGIC payments for loan `LN-2019-00142` have a consistent $400 discrepancy where the
# MAGIC escrow component appears to be double-counted.

# COMMAND ----------

amt = lambda c: F.coalesce(
    F.regexp_replace(F.col(c), r"[$,\s]", "").cast(DecimalType(10, 2)),
    F.lit(0).cast(DecimalType(10, 2))
)
recon_df = source_df.withColumn(
    "component_sum",
    amt("PMT_PRIN_AMT") + amt("PMT_INT_AMT") + amt("PMT_ESCROW_AMT") + amt("PMT_LATE_FEE")
).withColumn(
    "total_parsed", amt("PMT_AMT")
).withColumn(
    "delta", F.abs(F.col("component_sum") - F.col("total_parsed"))
)

bad_recon = recon_df.filter(F.col("delta") > 0.02).select(
    F.lit(RUN_ID).alias("run_id"),
    F.lit("CDW_PMT_HIST").alias("source_table"),
    F.col("PMT_SEQ_NBR").alias("source_record_id"),
    F.lit("PMT_AMT").alias("column_name"),
    F.lit("BUSINESS_RULE").alias("anomaly_type"),
    F.lit("MEDIUM").alias("severity"),
    F.concat(
        F.lit("Component sum="), F.col("component_sum"),
        F.lit(" vs total="), F.col("total_parsed"),
        F.lit(" delta="), F.round(F.col("delta"), 2)
    ).alias("description"),
    F.col("PMT_AMT").alias("original_value"),
    F.col("component_sum").cast(StringType()).alias("corrected_value"),
    F.current_timestamp().alias("detected_at"),
)
anomalies.append(bad_recon)

# --- ANO-006: Null required fields ---
for col_name in ["PMT_SEQ_NBR", "LN_ACCT_NBR", "PMT_AMT", "PMT_STAT_CD"]:
    null_records = source_df.filter(
        F.col(col_name).isNull() | (F.trim(F.col(col_name)) == "")
    ).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_PMT_HIST").alias("source_table"),
        F.coalesce(F.col("PMT_SEQ_NBR"), F.lit("UNKNOWN")).alias("source_record_id"),
        F.lit(col_name).alias("column_name"),
        F.lit("NULL_REQUIRED").alias("anomaly_type"),
        F.lit("CRITICAL").alias("severity"),
        F.lit(f"Required field {col_name} is null/blank").alias("description"),
        F.col(col_name).alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(null_records)

anomaly_df = reduce(DataFrame.unionByName, anomalies)
anomaly_count = anomaly_df.count()
print(f"Anomalies detected: {anomaly_count}")
if anomaly_count > 0:
    display(anomaly_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8: Write Anomalies to DQ Log

# COMMAND ----------

if anomaly_count > 0:
    anomaly_df.write.mode("append").saveAsTable(DQ_LOG_TABLE)
    print(f"Wrote {anomaly_count} anomaly records to {DQ_LOG_TABLE}")
else:
    print("No anomalies to write.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9: Write to Target Table (MERGE)
# MAGIC Idempotent upsert on `legacy_sequence_nbr` (legacy `PMT_SEQ_NBR`).
# MAGIC The target table is partitioned by `payment_year` for efficient time-range queries.

# COMMAND ----------

transformed_df.createOrReplaceTempView("payments_staging")

spark.sql(f"""
    MERGE INTO {TARGET_TABLE} AS target
    USING payments_staging AS source
    ON target.legacy_sequence_nbr = source.legacy_sequence_nbr
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")

target_count = spark.table(TARGET_TABLE).count()
print(f"Target rows after merge: {target_count}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10: Verify Results

# COMMAND ----------

# FK resolution check
null_loan_fk = spark.table(TARGET_TABLE).filter(F.col("loan_account_id").isNull()).count()
print(f"Payments with NULL loan_account_id (orphaned): {null_loan_fk}")

# Partition distribution
print("\nPayments by year:")
display(
    spark.table(TARGET_TABLE)
    .groupBy("payment_year")
    .count()
    .orderBy("payment_year")
)

# Status distribution
print("\nPayments by status:")
display(
    spark.table(TARGET_TABLE)
    .groupBy("status")
    .count()
    .orderBy(F.desc("count"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC | Metric | Value |
# MAGIC |--------|-------|
# MAGIC | Source rows | `{source_count}` |
# MAGIC | Target rows | `{target_count}` |
# MAGIC | Anomalies | `{anomaly_count}` |
# MAGIC | Orphaned loan FKs | `{null_loan_fk}` |
# MAGIC
# MAGIC **Next step:** Run `05_data_quality_checks` notebook to validate all tables.

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Pipeline Complete
# MAGIC All four ingestion notebooks have been run. The full execution order was:
# MAGIC
# MAGIC 1. `01_ingest_borrowers` — Dimension table
# MAGIC 2. `02_ingest_loan_products` — Dimension table
# MAGIC 3. `03_ingest_loan_accounts` — Fact table (depends on 1 & 2)
# MAGIC 4. `04_ingest_payments` — Fact table (depends on 3)
# MAGIC
# MAGIC Run the data quality checks notebook next to generate the final validation report.
