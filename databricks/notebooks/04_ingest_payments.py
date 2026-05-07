# Databricks notebook source

# MAGIC %md
# MAGIC # Payments Ingestion: CDW_PMT_HIST → payments
# MAGIC
# MAGIC This notebook migrates the legacy **CDW_PMT_HIST** (Payment History) table
# MAGIC into the modern **loan_warehouse.payments** Delta Lake table.
# MAGIC
# MAGIC ### Legacy Source Issues
# MAGIC - All 14 columns are VARCHAR
# MAGIC - Payment amounts stored with commas (`"1,487.02"`)
# MAGIC - Dates stored as `MM/DD/YYYY` strings
# MAGIC - Payment type codes are abbreviations (`REG`, `EXT`, `PRT`, `PRE`)
# MAGIC - Payment status codes are abbreviations (`PST`, `REV`, `NSF`, `PND`)
# MAGIC
# MAGIC ### What This Notebook Does
# MAGIC 1. Reads legacy payment data
# MAGIC 2. Resolves `LN_ACCT_NBR` → `loan_account_id` (FK to loan_accounts)
# MAGIC 3. Parses all amount strings → `DecimalType`
# MAGIC 4. Parses all date strings → `DateType` / `TimestampType`
# MAGIC 5. Expands payment type and status codes to readable labels
# MAGIC 6. Preserves legacy `PMT_SEQ_NBR` as `legacy_sequence_id` for audit trail
# MAGIC 7. Derives `payment_year` partition column
# MAGIC
# MAGIC ### Dependencies
# MAGIC - **Must run after:** `03_ingest_loan_accounts` (needed for FK resolution)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("source_path", "/mnt/legacy/cdw_pmt_hist", "Source Path")
dbutils.widgets.dropdown("source_format", "csv", ["csv", "parquet"], "Source Format")
dbutils.widgets.text("target_table", "loan_warehouse.payments", "Target Table")
dbutils.widgets.text("loan_table", "loan_warehouse.loan_accounts", "Loan Accounts Lookup Table")
dbutils.widgets.text("error_path", "/mnt/migration/errors/payments", "Error Output Path")

source_path = dbutils.widgets.get("source_path")
source_format = dbutils.widgets.get("source_format")
target_table = dbutils.widgets.get("target_table")
loan_table = dbutils.widgets.get("loan_table")
error_path = dbutils.widgets.get("error_path")

print(f"Source:       {source_path} ({source_format})")
print(f"Target:       {target_table}")
print(f"Loan lookup:  {loan_table}")
print(f"Errors:       {error_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Read Legacy Source Data

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, TimestampType
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
# MAGIC ## Step 2: Load FK Lookup Table
# MAGIC
# MAGIC Resolve `LN_ACCT_NBR` (string like `"LN-2019-00142"`) to the modern
# MAGIC `loan_account_id` (BIGINT) from the already-loaded loan_accounts table.

# COMMAND ----------

loan_lookup = spark.table(loan_table).select(
    F.col("loan_account_id"),
    F.col("account_number").alias("_ln_acct_nbr"),
)
print(f"Loan account lookup rows: {loan_lookup.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Apply Column Mappings & Transformations
# MAGIC
# MAGIC | Legacy Column | → Modern Column | Transformation |
# MAGIC |---------------|-----------------|----------------|
# MAGIC | `PMT_SEQ_NBR` | `legacy_sequence_id` | Preserved for audit trail |
# MAGIC | `LN_ACCT_NBR` | `loan_account_id` | FK lookup via loan_accounts |
# MAGIC | `PMT_DT` | `payment_date` | Parse MM/DD/YYYY → DATE |
# MAGIC | `PMT_AMT` | `total_amount` | Remove commas → DECIMAL(10,2) |
# MAGIC | `PMT_PRIN_AMT` | `principal_amount` | Remove commas → DECIMAL(10,2) |
# MAGIC | `PMT_INT_AMT` | `interest_amount` | Remove commas → DECIMAL(10,2) |
# MAGIC | `PMT_ESCROW_AMT` | `escrow_amount` | Remove commas → DECIMAL(10,2) |
# MAGIC | `PMT_LATE_FEE` | `late_fee` | Remove commas → DECIMAL(10,2) |
# MAGIC | `PMT_TYP_CD` | `type` | `REG`→Regular, `EXT`→Extra, `PRT`→Partial, `PRE`→Prepayment |
# MAGIC | `PMT_STAT_CD` | `status` | `PST`→Posted, `REV`→Reversed, `NSF`→NSF, `PND`→Pending |
# MAGIC | `PMT_RECV_DT` | `received_date` | Parse MM/DD/YYYY → DATE |
# MAGIC | `PMT_PROC_DT` | `processed_date` | Parse MM/DD/YYYY → DATE |
# MAGIC | `PMT_CRET_DT` | `created_at` | Parse MM/DD/YYYY → TIMESTAMP |
# MAGIC | `PMT_UPDT_DT` | `updated_at` | Parse MM/DD/YYYY → TIMESTAMP |
# MAGIC | *(derived)* | `payment_year` | `year(payment_date)` — partition column |

# COMMAND ----------

PAYMENT_TYPE_MAP = {
    "REG": "Regular",
    "EXT": "Extra",
    "PRT": "Partial",
    "PRE": "Prepayment",
}

PAYMENT_STATUS_MAP = {
    "PST": "Posted",
    "REV": "Reversed",
    "NSF": "NSF",
    "PND": "Pending",
}


def expand_codes(col_name, mapping):
    expr = F.col(col_name)
    for code, label in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(label)).otherwise(expr)
    return expr


run_ts = datetime.utcnow().isoformat()

transformed_df = source_df.select(
    F.col("PMT_SEQ_NBR").alias("legacy_sequence_id"),
    F.col("LN_ACCT_NBR").alias("_ln_acct_nbr"),
    F.to_date(F.col("PMT_DT"), "MM/dd/yyyy").alias("payment_date"),
    F.regexp_replace(F.col("PMT_AMT"), ",", "").cast(DecimalType(10, 2)).alias("total_amount"),
    F.regexp_replace(F.col("PMT_PRIN_AMT"), ",", "").cast(DecimalType(10, 2)).alias("principal_amount"),
    F.regexp_replace(F.col("PMT_INT_AMT"), ",", "").cast(DecimalType(10, 2)).alias("interest_amount"),
    F.regexp_replace(F.col("PMT_ESCROW_AMT"), ",", "").cast(DecimalType(10, 2)).alias("escrow_amount"),
    F.regexp_replace(F.col("PMT_LATE_FEE"), ",", "").cast(DecimalType(10, 2)).alias("late_fee"),
    expand_codes("PMT_TYP_CD", PAYMENT_TYPE_MAP).alias("type"),
    expand_codes("PMT_STAT_CD", PAYMENT_STATUS_MAP).alias("status"),
    F.to_date(F.col("PMT_RECV_DT"), "MM/dd/yyyy").alias("received_date"),
    F.to_date(F.col("PMT_PROC_DT"), "MM/dd/yyyy").alias("processed_date"),
    F.to_timestamp(F.col("PMT_CRET_DT"), "MM/dd/yyyy").alias("created_at"),
    F.to_timestamp(F.col("PMT_UPDT_DT"), "MM/dd/yyyy").alias("updated_at"),
    F.lit("CDW_PMT_HIST").alias("_migration_source"),
    F.lit(run_ts).cast("timestamp").alias("_migrated_at"),
)

# Derive partition column
transformed_df = transformed_df.withColumn(
    "payment_year", F.year(F.col("payment_date"))
)

print("Schema after transformation:")
transformed_df.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Resolve Loan Account FK
# MAGIC
# MAGIC Left join with the loan_accounts lookup to resolve account numbers to IDs.
# MAGIC Unresolved FKs will show as NULL `loan_account_id` and be caught in validation.

# COMMAND ----------

transformed_df = transformed_df.join(loan_lookup, on="_ln_acct_nbr", how="left")
transformed_df = transformed_df.drop("_ln_acct_nbr")

display(transformed_df.select("legacy_sequence_id", "loan_account_id", "payment_date", "total_amount", "type", "status"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Validate Required Fields & Route Errors

# COMMAND ----------

required_cols = ["loan_account_id", "payment_date", "total_amount", "type", "status"]

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
    display(error_df.select("legacy_sequence_id", "loan_account_id", "_error_reason"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Write to Delta Lake
# MAGIC
# MAGIC Table is partitioned by `payment_year` and `status` for efficient
# MAGIC time-range queries and reconciliation filtering.

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
# MAGIC ## Step 7: Post-Load Verification

# COMMAND ----------

target_count = spark.table(target_table).count()
print(f"Target table row count: {target_count}")

assert source_count == good_count + error_count, (
    f"Row count mismatch: source={source_count} != good({good_count}) + error({error_count})"
)
print(f"✓ Row count reconciliation passed")

# Verify FK resolution and show payment breakdown
display(
    spark.sql(f"""
        SELECT
            p.legacy_sequence_id,
            la.account_number,
            p.payment_date,
            p.total_amount,
            p.principal_amount,
            p.interest_amount,
            p.type,
            p.status
        FROM {target_table} p
        JOIN {loan_table} la ON p.loan_account_id = la.loan_account_id
        ORDER BY p.payment_date DESC
    """)
)
