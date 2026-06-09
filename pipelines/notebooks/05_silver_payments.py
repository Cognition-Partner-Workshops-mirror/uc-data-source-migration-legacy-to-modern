# Databricks notebook source
# MAGIC %md
# MAGIC # 05 - Silver Layer: Payment History Transformation
# MAGIC
# MAGIC Transforms `bronze.cdw_pmt_hist` → `silver.payments`
# MAGIC
# MAGIC **Transformations applied:**
# MAGIC - Parse all amount fields (remove commas) → DecimalType
# MAGIC - Parse date fields → DateType
# MAGIC - Expand payment type codes (REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT)
# MAGIC - Expand payment status codes (PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING)
# MAGIC - Validate: payment component reconciliation, referential integrity to loan accounts

# COMMAND ----------

import sys
sys.path.insert(0, "../")

from config.pipeline_config import (
    BRONZE_CATALOG,
    BRONZE_SCHEMA,
    SILVER_CATALOG,
    SILVER_SCHEMA,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)
from utils.transformations import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    expand_status_code,
)
from utils.data_quality import (
    check_null_required_fields,
    check_date_parseable,
    check_numeric_parseable,
    check_valid_status_codes,
    check_payment_reconciliation,
    check_referential_integrity,
    log_quality_summary,
    QUALITY_ISSUE_SCHEMA,
)
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

# COMMAND ----------

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Bronze Payment History

# COMMAND ----------

bronze_payments = spark.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.cdw_pmt_hist")
bronze_accounts = spark.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.cdw_ln_acct")

print(f"Bronze payment records: {bronze_payments.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data Quality Checks
# MAGIC
# MAGIC ANO-001 (Payment Component Sum Mismatch) is explicitly checked here.

# COMMAND ----------

all_issues = spark.createDataFrame([], QUALITY_ISSUE_SCHEMA)

# Required fields
required = ["PMT_SEQ_NBR", "LN_ACCT_NBR", "PMT_DT", "PMT_AMT", "PMT_TYP_CD", "PMT_STAT_CD"]
null_issues = check_null_required_fields(
    bronze_payments, "CDW_PMT_HIST", "PMT_SEQ_NBR", required
)
all_issues = all_issues.union(null_issues)

# Date fields
date_fields = ["PMT_DT", "PMT_RECV_DT", "PMT_PROC_DT", "PMT_CRET_DT", "PMT_UPDT_DT"]
date_issues = check_date_parseable(
    bronze_payments, "CDW_PMT_HIST", "PMT_SEQ_NBR", date_fields
)
all_issues = all_issues.union(date_issues)

# Numeric fields
numeric_fields = ["PMT_AMT", "PMT_PRIN_AMT", "PMT_INT_AMT", "PMT_ESCROW_AMT", "PMT_LATE_FEE"]
numeric_issues = check_numeric_parseable(
    bronze_payments, "CDW_PMT_HIST", "PMT_SEQ_NBR", numeric_fields
)
all_issues = all_issues.union(numeric_issues)

# Status code validation
valid_types = set(PAYMENT_TYPE_MAP.keys())
type_issues = check_valid_status_codes(
    bronze_payments, "CDW_PMT_HIST", "PMT_SEQ_NBR", "PMT_TYP_CD", valid_types
)
all_issues = all_issues.union(type_issues)

valid_statuses = set(PAYMENT_STATUS_MAP.keys())
status_issues = check_valid_status_codes(
    bronze_payments, "CDW_PMT_HIST", "PMT_SEQ_NBR", "PMT_STAT_CD", valid_statuses
)
all_issues = all_issues.union(status_issues)

# ANO-001: Payment component reconciliation
# Components: principal + interest + escrow + late_fee should equal total
component_cols = ["PMT_PRIN_AMT", "PMT_INT_AMT", "PMT_ESCROW_AMT", "PMT_LATE_FEE"]
recon_issues = check_payment_reconciliation(
    bronze_payments, "CDW_PMT_HIST", "PMT_SEQ_NBR", "PMT_AMT", component_cols
)
all_issues = all_issues.union(recon_issues)

# Referential integrity: LN_ACCT_NBR must exist in CDW_LN_ACCT
ref_issues = check_referential_integrity(
    bronze_payments, bronze_accounts,
    "CDW_PMT_HIST", "PMT_SEQ_NBR", "LN_ACCT_NBR", "LN_ACCT_NBR"
)
all_issues = all_issues.union(ref_issues)

log_quality_summary(all_issues, "Silver Payments - Pre-Transform")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Apply Transformations

# COMMAND ----------

silver_payments = bronze_payments.select(
    # Keep legacy payment ID for traceability
    F.trim(F.col("PMT_SEQ_NBR")).alias("legacy_payment_id"),

    # Foreign key (resolved to BIGINT in gold layer)
    F.trim(F.col("LN_ACCT_NBR")).alias("loan_account_number"),

    # Date fields
    parse_legacy_date(F.col("PMT_DT")).alias("payment_date"),

    # Amount fields: remove commas → decimal
    parse_legacy_amount(F.col("PMT_AMT")).alias("total_amount"),
    parse_legacy_amount(F.col("PMT_PRIN_AMT")).alias("principal_amount"),
    parse_legacy_amount(F.col("PMT_INT_AMT")).alias("interest_amount"),
    parse_legacy_amount(F.col("PMT_ESCROW_AMT")).alias("escrow_amount"),
    parse_legacy_amount(F.col("PMT_LATE_FEE")).alias("late_fee"),

    # Status expansion
    expand_status_code(F.col("PMT_TYP_CD"), PAYMENT_TYPE_MAP).alias("type"),
    expand_status_code(F.col("PMT_STAT_CD"), PAYMENT_STATUS_MAP).alias("status"),

    # Additional dates
    parse_legacy_date(F.col("PMT_RECV_DT")).alias("received_date"),
    parse_legacy_date(F.col("PMT_PROC_DT")).alias("processed_date"),

    # Audit timestamps
    parse_legacy_timestamp(F.col("PMT_CRET_DT")).alias("created_at"),
    parse_legacy_timestamp(F.col("PMT_UPDT_DT")).alias("updated_at"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Silver Payments

# COMMAND ----------

target_table = f"{SILVER_CATALOG}.{SILVER_SCHEMA}.payments"

(
    silver_payments.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(target_table)
)

row_count = spark.table(target_table).count()
print(f"Silver payments written: {row_count} rows → {target_table}")
silver_payments.printSchema()
