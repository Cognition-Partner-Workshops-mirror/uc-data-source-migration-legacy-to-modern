# Databricks notebook source
# MAGIC %md
# MAGIC # 04 - Silver Layer: Loan Account Transformation
# MAGIC
# MAGIC Transforms `bronze.cdw_ln_acct` → `silver.loan_accounts`
# MAGIC
# MAGIC **Transformations applied:**
# MAGIC - Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
# MAGIC - Parse all amount fields (remove commas) → DecimalType
# MAGIC - Parse interest rate → DecimalType(5,3)
# MAGIC - Parse term months, delinquency days → IntegerType
# MAGIC - Parse all date fields → DateType
# MAGIC - Expand loan status codes (ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE, DLQ→DELINQUENT)
# MAGIC - Expand property type codes (SFR→Single Family, CND→Condominium, etc.)
# MAGIC - Validate: delinquency/status consistency, referential integrity to borrowers and products

# COMMAND ----------

import sys
sys.path.insert(0, "../")

from config.pipeline_config import (
    BRONZE_CATALOG,
    BRONZE_SCHEMA,
    SILVER_CATALOG,
    SILVER_SCHEMA,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)
from utils.transformations import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_integer,
    parse_legacy_rate,
    parse_legacy_percent,
    expand_status_code,
)
from utils.data_quality import (
    check_null_required_fields,
    check_date_parseable,
    check_numeric_parseable,
    check_valid_status_codes,
    check_delinquency_status_consistency,
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
# MAGIC ## Read Bronze Data

# COMMAND ----------

bronze_accounts = spark.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.cdw_ln_acct")
bronze_borrowers = spark.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.cdw_borr_mstr")
bronze_products = spark.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.cdw_ln_prod")

print(f"Bronze loan account records: {bronze_accounts.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data Quality Checks

# COMMAND ----------

all_issues = spark.createDataFrame([], QUALITY_ISSUE_SCHEMA)

# Required fields
required = ["LN_ACCT_NBR", "BORR_ID", "PROD_CD", "LN_ORIG_AMT", "LN_CURR_BAL",
            "LN_INT_RT", "LN_TERM_MOS", "LN_PMT_AMT", "LN_ORIG_DT", "LN_MAT_DT"]
null_issues = check_null_required_fields(
    bronze_accounts, "CDW_LN_ACCT", "LN_ACCT_NBR", required
)
all_issues = all_issues.union(null_issues)

# Date fields
date_fields = ["LN_ORIG_DT", "LN_MAT_DT", "LN_1ST_PMT_DT", "LN_NXT_PMT_DT",
               "LN_CRET_DT", "LN_UPDT_DT"]
date_issues = check_date_parseable(
    bronze_accounts, "CDW_LN_ACCT", "LN_ACCT_NBR", date_fields
)
all_issues = all_issues.union(date_issues)

# Numeric fields
numeric_fields = ["LN_ORIG_AMT", "LN_CURR_BAL", "LN_PMT_AMT", "LN_ESCROW_BAL", "PROP_APRS_VAL"]
numeric_issues = check_numeric_parseable(
    bronze_accounts, "CDW_LN_ACCT", "LN_ACCT_NBR", numeric_fields
)
all_issues = all_issues.union(numeric_issues)

# Status code validation
valid_loan_statuses = set(LOAN_STATUS_MAP.keys())
status_issues = check_valid_status_codes(
    bronze_accounts, "CDW_LN_ACCT", "LN_ACCT_NBR", "LN_STAT_CD", valid_loan_statuses
)
all_issues = all_issues.union(status_issues)

# ANO-003: Delinquency/status consistency
dlq_issues = check_delinquency_status_consistency(
    bronze_accounts, "CDW_LN_ACCT", "LN_ACCT_NBR", "LN_DLQ_DAYS", "LN_STAT_CD"
)
all_issues = all_issues.union(dlq_issues)

# Referential integrity: BORR_ID must exist in CDW_BORR_MSTR
borr_ref_issues = check_referential_integrity(
    bronze_accounts, bronze_borrowers,
    "CDW_LN_ACCT", "LN_ACCT_NBR", "BORR_ID", "BORR_ID"
)
all_issues = all_issues.union(borr_ref_issues)

# Referential integrity: PROD_CD must exist in CDW_LN_PROD
prod_ref_issues = check_referential_integrity(
    bronze_accounts, bronze_products,
    "CDW_LN_ACCT", "LN_ACCT_NBR", "PROD_CD", "PROD_CD"
)
all_issues = all_issues.union(prod_ref_issues)

log_quality_summary(all_issues, "Silver Loan Accounts - Pre-Transform")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Apply Transformations
# MAGIC
# MAGIC Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
# MAGIC are dropped — the modern schema uses foreign key to borrowers table instead.

# COMMAND ----------

silver_accounts = bronze_accounts.select(
    # Account identifier
    F.trim(F.col("LN_ACCT_NBR")).alias("account_number"),

    # Foreign keys (kept as string for now; resolved to BIGINT in gold layer)
    F.trim(F.col("BORR_ID")).alias("borrower_external_id"),
    F.trim(F.col("PROD_CD")).alias("product_code"),

    # Amount fields: remove commas → decimal
    parse_legacy_amount(F.col("LN_ORIG_AMT")).alias("original_amount"),
    parse_legacy_amount(F.col("LN_CURR_BAL")).alias("current_balance"),
    parse_legacy_rate(F.col("LN_INT_RT")).alias("interest_rate"),
    parse_legacy_integer(F.col("LN_TERM_MOS")).alias("term_months"),
    parse_legacy_amount(F.col("LN_PMT_AMT")).alias("monthly_payment"),

    # Date fields: MM/DD/YYYY → DateType
    parse_legacy_date(F.col("LN_ORIG_DT")).alias("origination_date"),
    parse_legacy_date(F.col("LN_MAT_DT")).alias("maturity_date"),
    parse_legacy_date(F.col("LN_1ST_PMT_DT")).alias("first_payment_date"),
    parse_legacy_date(F.col("LN_NXT_PMT_DT")).alias("next_payment_date"),

    # Status expansion: ACT → ACTIVE, CLO → CLOSED, etc.
    expand_status_code(F.col("LN_STAT_CD"), LOAN_STATUS_MAP).alias("status"),

    # Delinquency and escrow
    parse_legacy_integer(F.col("LN_DLQ_DAYS")).alias("delinquency_days"),
    parse_legacy_amount(F.col("LN_ESCROW_BAL")).alias("escrow_balance"),
    parse_legacy_percent(F.col("LN_LTV_PCT")).alias("ltv_percent"),

    # Property fields
    F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
    F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
    F.trim(F.col("PROP_ST_CD")).alias("property_state"),
    F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
    expand_status_code(F.col("PROP_TYP_CD"), PROPERTY_TYPE_MAP).alias("property_type"),
    parse_legacy_amount(F.col("PROP_APRS_VAL")).alias("appraised_value"),

    # Audit timestamps
    parse_legacy_timestamp(F.col("LN_CRET_DT")).alias("created_at"),
    parse_legacy_timestamp(F.col("LN_UPDT_DT")).alias("updated_at"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Silver Loan Accounts

# COMMAND ----------

target_table = f"{SILVER_CATALOG}.{SILVER_SCHEMA}.loan_accounts"

(
    silver_accounts.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(target_table)
)

row_count = spark.table(target_table).count()
print(f"Silver loan_accounts written: {row_count} rows → {target_table}")
silver_accounts.printSchema()
