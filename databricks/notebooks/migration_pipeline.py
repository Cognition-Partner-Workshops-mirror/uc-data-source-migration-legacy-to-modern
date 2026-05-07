# Databricks notebook source

# MAGIC %md
# MAGIC # Legacy CDW → Delta Lake Migration Pipeline
# MAGIC
# MAGIC This notebook migrates loan data from the legacy CDW (Corporate Data Warehouse) schema
# MAGIC into a modern Delta Lake architecture. The legacy system stores **all data as VARCHAR**
# MAGIC columns with cryptic abbreviated names, no foreign keys, and denormalized structures.
# MAGIC
# MAGIC **Source tables:**
# MAGIC | Legacy Table | Description |
# MAGIC |---|---|
# MAGIC | `CDW_BORR_MSTR` | Borrower master records |
# MAGIC | `CDW_LN_PROD` | Loan product definitions |
# MAGIC | `CDW_LN_ACCT` | Loan accounts (denormalized with borrower data) |
# MAGIC | `CDW_PMT_HIST` | Payment history |
# MAGIC
# MAGIC **Execution order matters** — later tables depend on FK lookups against earlier ones:
# MAGIC 1. borrowers & loan_products (no dependencies)
# MAGIC 2. loan_accounts (depends on borrowers + loan_products)
# MAGIC 3. payments (depends on loan_accounts)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC Set the base path to the landing zone where legacy data has been staged as CSV or Parquet files.
# MAGIC Each source table should be in its own sub-folder.

# COMMAND ----------

# Landing zone base path — update this to match your environment
BASE_PATH = "/mnt/landing/cdw"
FILE_FORMAT = "csv"  # "csv" or "parquet"
WRITE_MODE = "overwrite"  # "overwrite" for full reload, "append" for incremental

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 0: Create Database
# MAGIC
# MAGIC Creates the `loan_warehouse` database that will hold all migrated Delta tables.

# COMMAND ----------

spark.sql("""
    CREATE DATABASE IF NOT EXISTS loan_warehouse
    COMMENT 'Modern loan data warehouse migrated from legacy CDW schema'
    LOCATION '/mnt/delta/loan_warehouse'
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Shared Transformation Utilities
# MAGIC
# MAGIC These helper functions handle the five core transformation patterns used throughout:
# MAGIC
# MAGIC 1. **Date parsing**: Legacy dates are stored as `VARCHAR(10)` strings in `MM/DD/YYYY` format.
# MAGIC    We use `to_date()` with the format pattern `"MM/dd/yyyy"`. Unparseable values become `NULL`
# MAGIC    rather than throwing exceptions.
# MAGIC
# MAGIC 2. **Amount parsing**: Legacy amounts contain commas (e.g. `"285,000"`, `"271,432.56"`).
# MAGIC    We strip commas with `regexp_replace` then cast to `DecimalType`.
# MAGIC
# MAGIC 3. **Integer parsing**: Simple `.cast(IntegerType())` on string columns. Non-numeric values
# MAGIC    become `NULL`.
# MAGIC
# MAGIC 4. **Status code expansion**: Short codes like `ACT`, `CLO`, `DFT` are mapped to readable
# MAGIC    values (`ACTIVE`, `CLOSED`, `DEFAULT`) using a `create_map` lookup. Unknown codes get
# MAGIC    a `_UNKNOWN` suffix so they surface in quality checks rather than being silently dropped.
# MAGIC
# MAGIC 5. **Denormalization removal**: Redundant borrower columns in loan accounts are dropped
# MAGIC    in favor of FK references to the normalized borrower table.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, IntegerType

# ---------------------------------------------------------------------------
# Date / timestamp parsing
# ---------------------------------------------------------------------------

def parse_date(col):
    """Parse a legacy MM/DD/YYYY string into a Spark DateType."""
    return F.to_date(F.trim(col), "MM/dd/yyyy")


def parse_timestamp(col):
    """Parse a legacy MM/DD/YYYY string into a Spark TimestampType (midnight)."""
    return F.to_timestamp(F.trim(col), "MM/dd/yyyy")


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def parse_amount(col, precision=12, scale=2):
    """Remove commas from a string amount and cast to DecimalType.

    Example: "285,000" → 285000.00, "271,432.56" → 271432.56
    """
    return F.regexp_replace(F.trim(col), ",", "").cast(DecimalType(precision, scale))


def parse_int(col):
    """Cast a string column to IntegerType, returning null for non-numeric values."""
    return F.trim(col).cast(IntegerType())


def parse_rate(col, precision=5, scale=3):
    """Parse a string rate (e.g. '5.250') to DecimalType(5,3)."""
    return F.trim(col).cast(DecimalType(precision, scale))


def parse_percent(col, precision=5, scale=2):
    """Parse a string percentage (e.g. '82.5') to DecimalType(5,2)."""
    return F.trim(col).cast(DecimalType(precision, scale))


# ---------------------------------------------------------------------------
# Status / code expansion maps
# ---------------------------------------------------------------------------

LOAN_STATUS_MAP = {"ACT": "ACTIVE", "CLO": "CLOSED", "DFT": "DEFAULT", "FRB": "FORBEARANCE"}
BORROWER_STATUS_MAP = {"ACT": "ACTIVE", "INA": "INACTIVE"}
PRODUCT_STATUS_MAP = {"ACT": True, "INA": False}
PAYMENT_TYPE_MAP = {"REG": "REGULAR", "EXT": "EXTRA", "PRT": "PARTIAL", "PRE": "PREPAYMENT"}
PAYMENT_STATUS_MAP = {"PST": "POSTED", "REV": "REVERSED", "NSF": "NSF", "PND": "PENDING"}
PROPERTY_TYPE_MAP = {"SFR": "Single Family", "CND": "Condominium", "MFR": "Multi-Family", "TWN": "Townhouse"}


def expand_status(col, mapping):
    """Map abbreviated codes to expanded values. Unknown codes get '_UNKNOWN' suffix."""
    spark_map = F.create_map(*[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))])
    expr = F.coalesce(spark_map[F.upper(F.trim(col))], F.concat(F.upper(F.trim(col)), F.lit("_UNKNOWN")))
    return F.when(col.isNull(), F.lit(None)).otherwise(expr)


def expand_status_to_bool(col, mapping):
    """Map abbreviated codes to boolean values (for product active/inactive)."""
    spark_map = F.create_map(*[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))])
    return F.when(col.isNull(), F.lit(None)).otherwise(spark_map[F.upper(F.trim(col))])


print("Transformation utilities loaded.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Ingest Borrowers
# MAGIC
# MAGIC **Source:** `CDW_BORR_MSTR` → **Target:** `loan_warehouse.borrowers`
# MAGIC
# MAGIC ### Transformations applied:
# MAGIC - **Column renames**: `BORR_FST_NM` → `first_name`, `BORR_LST_NM` → `last_name`, etc.
# MAGIC - **Date parsing**: `BORR_DOB_DT` (MM/DD/YYYY string) → `date_of_birth` (DATE)
# MAGIC - **Timestamp parsing**: `BORR_CRET_DT`, `BORR_UPDT_DT` → `created_at`, `updated_at` (TIMESTAMP)
# MAGIC - **Amount parsing**: `BORR_ANN_INCM` ("92,500") → `annual_income` (DECIMAL)
# MAGIC - **Integer parsing**: `BORR_CRDT_SCR` ("745") → `credit_score` (INT)
# MAGIC - **Status expansion**: `BORR_STAT_CD` (ACT/INA) → `status` (ACTIVE/INACTIVE)
# MAGIC - **Dropped columns**: `BORR_REC_TYP` (record type indicator not needed in modern schema)
# MAGIC - **Quarantine**: Records missing `BORR_ID`, `BORR_FST_NM`, or `BORR_LST_NM` are quarantined
# MAGIC
# MAGIC **Partitioned by:** `state` (supports regional compliance and servicing queries)

# COMMAND ----------

# Read legacy borrower data
borrower_source_path = f"{BASE_PATH}/cdw_borr_mstr/"
if FILE_FORMAT == "parquet":
    raw_borrowers = spark.read.parquet(borrower_source_path)
else:
    raw_borrowers = spark.read.option("header", "true").option("inferSchema", "false").csv(borrower_source_path)

borrower_source_count = raw_borrowers.count()
print(f"Read {borrower_source_count} borrower records from source")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Quarantine invalid borrower records
# MAGIC
# MAGIC Records missing critical fields are separated into a quarantine table.
# MAGIC This ensures we never silently drop records — they are preserved for investigation.

# COMMAND ----------

borrower_quarantine_condition = (
    F.col("BORR_ID").isNull()
    | F.col("BORR_FST_NM").isNull()
    | F.col("BORR_LST_NM").isNull()
)

quarantined_borrowers = raw_borrowers.filter(borrower_quarantine_condition)
quarantine_count = quarantined_borrowers.count()
if quarantine_count > 0:
    print(f"⚠ Quarantining {quarantine_count} borrower records with null required fields")
    quarantined_borrowers.write.mode("append").format("delta").saveAsTable("loan_warehouse._quarantine_borrowers")
else:
    print("No borrower records quarantined")

clean_borrowers = raw_borrowers.filter(~borrower_quarantine_condition)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Apply borrower transformations
# MAGIC
# MAGIC Each column is renamed from its cryptic legacy name to a meaningful modern name,
# MAGIC and type conversions are applied. A temporary `_raw_dob` column is carried through
# MAGIC to detect date-parsing failures (where the source had a value but `to_date` returned NULL).

# COMMAND ----------

transformed_borrowers = clean_borrowers.select(
    F.col("BORR_ID").alias("external_id"),
    F.trim(F.col("BORR_FST_NM")).alias("first_name"),
    F.trim(F.col("BORR_LST_NM")).alias("last_name"),
    F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
    F.col("BORR_SSN_ENCR").alias("ssn_hash"),
    parse_date(F.col("BORR_DOB_DT")).alias("date_of_birth"),
    F.col("BORR_DOB_DT").alias("_raw_dob"),
    F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
    F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
    F.trim(F.col("BORR_CTY_NM")).alias("city"),
    F.trim(F.col("BORR_ST_CD")).alias("state"),
    F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),
    F.trim(F.col("BORR_PH_NBR")).alias("phone"),
    F.trim(F.col("BORR_EMAIL_ADDR")).alias("email"),
    parse_int(F.col("BORR_CRDT_SCR")).alias("credit_score"),
    F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),
    parse_amount(F.col("BORR_ANN_INCM")).alias("annual_income"),
    expand_status(F.col("BORR_STAT_CD"), BORROWER_STATUS_MAP).alias("status"),
    parse_timestamp(F.col("BORR_CRET_DT")).alias("created_at"),
    parse_timestamp(F.col("BORR_UPDT_DT")).alias("updated_at"),
    F.lit("CDW_BORR_MSTR").alias("_migration_src"),
    F.current_timestamp().alias("_migrated_at"),
)

# Check for date-parsing failures
date_failures = transformed_borrowers.filter(
    F.col("date_of_birth").isNull() & F.col("_raw_dob").isNotNull()
).count()
if date_failures > 0:
    print(f"⚠ {date_failures} records where BORR_DOB_DT could not be parsed to DATE")

# Drop the temporary column and write
transformed_borrowers = transformed_borrowers.drop("_raw_dob")
borrower_target_count = transformed_borrowers.count()
print(f"Transformed {borrower_target_count} borrower records")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Write borrowers to Delta Lake

# COMMAND ----------

transformed_borrowers.write.format("delta").mode(WRITE_MODE).partitionBy("state").saveAsTable("loan_warehouse.borrowers")
print(f"✓ Wrote {borrower_target_count} records to loan_warehouse.borrowers")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Ingest Loan Products
# MAGIC
# MAGIC **Source:** `CDW_LN_PROD` → **Target:** `loan_warehouse.loan_products`
# MAGIC
# MAGIC ### Transformations applied:
# MAGIC - **Column renames**: `PROD_CD` → `code`, `PROD_DESC_TXT` → `name`, etc.
# MAGIC - **Integer parsing**: `PROD_TERM_MOS` ("360") → `term_months` (INT)
# MAGIC - **Amount parsing**: `PROD_MIN_AMT`/`PROD_MAX_AMT` → `min_amount`/`max_amount` (DECIMAL)
# MAGIC - **Status to boolean**: `PROD_STAT_CD` (ACT/INA) → `is_active` (BOOLEAN true/false)
# MAGIC - **Date parsing**: `PROD_EFF_DT`, `PROD_EXP_DT` → `effective_date`, `expiration_date` (DATE)
# MAGIC
# MAGIC **No partitioning** — this is a small reference table.

# COMMAND ----------

# Read legacy loan product data
product_source_path = f"{BASE_PATH}/cdw_ln_prod/"
if FILE_FORMAT == "parquet":
    raw_products = spark.read.parquet(product_source_path)
else:
    raw_products = spark.read.option("header", "true").option("inferSchema", "false").csv(product_source_path)

product_source_count = raw_products.count()
print(f"Read {product_source_count} loan product records from source")

# COMMAND ----------

# Quarantine records missing required fields
product_quarantine_condition = F.col("PROD_CD").isNull() | F.col("PROD_DESC_TXT").isNull()

quarantined_products = raw_products.filter(product_quarantine_condition)
q_count = quarantined_products.count()
if q_count > 0:
    print(f"⚠ Quarantining {q_count} loan product records")
    quarantined_products.write.mode("append").format("delta").saveAsTable("loan_warehouse._quarantine_loan_products")
else:
    print("No loan product records quarantined")

clean_products = raw_products.filter(~product_quarantine_condition)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Apply loan product transformations
# MAGIC
# MAGIC Note the **boolean conversion** for `PROD_STAT_CD`: instead of expanding to a string,
# MAGIC we convert `ACT` → `true` and `INA` → `false` since the modern schema uses a boolean
# MAGIC `is_active` flag.

# COMMAND ----------

transformed_products = clean_products.select(
    F.trim(F.col("PROD_CD")).alias("code"),
    F.trim(F.col("PROD_DESC_TXT")).alias("name"),
    F.trim(F.col("PROD_TYP_CD")).alias("type"),
    parse_int(F.col("PROD_TERM_MOS")).alias("term_months"),
    F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
    parse_amount(F.col("PROD_MIN_AMT")).alias("min_amount"),
    parse_amount(F.col("PROD_MAX_AMT")).alias("max_amount"),
    expand_status_to_bool(F.col("PROD_STAT_CD"), PRODUCT_STATUS_MAP).alias("is_active"),
    parse_date(F.col("PROD_EFF_DT")).alias("effective_date"),
    parse_date(F.col("PROD_EXP_DT")).alias("expiration_date"),
    F.lit("CDW_LN_PROD").alias("_migration_src"),
    F.current_timestamp().alias("_migrated_at"),
)

product_target_count = transformed_products.count()
print(f"Transformed {product_target_count} loan product records")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Write loan products to Delta Lake

# COMMAND ----------

transformed_products.write.format("delta").mode(WRITE_MODE).saveAsTable("loan_warehouse.loan_products")
print(f"✓ Wrote {product_target_count} records to loan_warehouse.loan_products")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Ingest Loan Accounts
# MAGIC
# MAGIC **Source:** `CDW_LN_ACCT` → **Target:** `loan_warehouse.loan_accounts`
# MAGIC
# MAGIC This is the most complex transformation because it involves:
# MAGIC
# MAGIC ### Key transformations:
# MAGIC - **Denormalization removal**: The legacy table embeds borrower columns
# MAGIC   (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) redundantly. These are **dropped**
# MAGIC   in favor of a `borrower_id` FK to the normalized `borrowers` table.
# MAGIC - **FK resolution**: `BORR_ID` (string) → `borrower_id` (BIGINT) via lookup against
# MAGIC   `borrowers.external_id`. Similarly `PROD_CD` → `product_id` via `loan_products.code`.
# MAGIC   Uses **left joins** so unresolved FKs become NULL rather than dropping records.
# MAGIC - **Status expansion**: `LN_STAT_CD` (ACT/CLO/DFT/FRB) → full status names
# MAGIC - **Property type expansion**: `PROP_TYP_CD` (SFR/CND/MFR/TWN) → readable names
# MAGIC - **Multiple amount fields**: `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, etc.
# MAGIC - **Derived column**: `origination_year` extracted from `origination_date` for partitioning
# MAGIC
# MAGIC **Partitioned by:** `status` (most queries filter active vs. closed/defaulted loans)
# MAGIC
# MAGIC **⚠ Dependency:** Requires `borrowers` and `loan_products` tables to be populated first.

# COMMAND ----------

# Read legacy loan account data
loan_source_path = f"{BASE_PATH}/cdw_ln_acct/"
if FILE_FORMAT == "parquet":
    raw_loans = spark.read.parquet(loan_source_path)
else:
    raw_loans = spark.read.option("header", "true").option("inferSchema", "false").csv(loan_source_path)

loan_source_count = raw_loans.count()
print(f"Read {loan_source_count} loan account records from source")

# COMMAND ----------

# Quarantine records missing required fields
loan_quarantine_condition = (
    F.col("LN_ACCT_NBR").isNull()
    | F.col("BORR_ID").isNull()
    | F.col("PROD_CD").isNull()
)

quarantined_loans = raw_loans.filter(loan_quarantine_condition)
q_count = quarantined_loans.count()
if q_count > 0:
    print(f"⚠ Quarantining {q_count} loan account records")
    quarantined_loans.write.mode("append").format("delta").saveAsTable("loan_warehouse._quarantine_loan_accounts")
else:
    print("No loan account records quarantined")

clean_loans = raw_loans.filter(~loan_quarantine_condition)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Resolve foreign keys
# MAGIC
# MAGIC The legacy schema uses string-based identifiers (`BORR_ID = "B-10001"`, `PROD_CD = "FXD30"`).
# MAGIC The modern schema uses auto-generated BIGINT surrogate keys. We resolve them via left joins
# MAGIC against the previously loaded dimension tables.
# MAGIC
# MAGIC **Left joins** are used intentionally: if a borrower or product can't be resolved, the FK
# MAGIC becomes NULL rather than dropping the loan record. The data quality framework will flag
# MAGIC these as referential integrity violations.

# COMMAND ----------

# Resolve borrower FK: legacy BORR_ID → modern borrowers.id
borrower_lookup = spark.table("loan_warehouse.borrowers").select(
    F.col("id").alias("_borrower_id"),
    F.col("external_id").alias("_borr_ext_id"),
)

# Resolve product FK: legacy PROD_CD → modern loan_products.id
product_lookup = spark.table("loan_warehouse.loan_products").select(
    F.col("id").alias("_product_id"),
    F.col("code").alias("_prod_code"),
)

joined_loans = (
    clean_loans
    .join(borrower_lookup, clean_loans["BORR_ID"] == borrower_lookup["_borr_ext_id"], "left")
    .join(product_lookup, clean_loans["PROD_CD"] == product_lookup["_prod_code"], "left")
)

# Log unresolved FKs
unresolved_borr = joined_loans.filter(F.col("_borrower_id").isNull()).count()
unresolved_prod = joined_loans.filter(F.col("_product_id").isNull()).count()
if unresolved_borr > 0:
    print(f"⚠ {unresolved_borr} loan accounts with unresolved borrower FK")
if unresolved_prod > 0:
    print(f"⚠ {unresolved_prod} loan accounts with unresolved product FK")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Apply loan account transformations
# MAGIC
# MAGIC This select drops the denormalized borrower fields (`BORR_FST_NM`, `BORR_LST_NM`,
# MAGIC `BORR_SSN_LST4`) and replaces them with the resolved `borrower_id` FK. The
# MAGIC `origination_year` column is derived from `origination_date` for use as a partition key.

# COMMAND ----------

origination_date_col = parse_date(F.col("LN_ORIG_DT"))

transformed_loans = joined_loans.select(
    F.col("LN_ACCT_NBR").alias("account_number"),
    F.col("_borrower_id").alias("borrower_id"),
    F.col("_product_id").alias("product_id"),
    parse_amount(F.col("LN_ORIG_AMT")).alias("original_amount"),
    parse_amount(F.col("LN_CURR_BAL")).alias("current_balance"),
    parse_rate(F.col("LN_INT_RT")).alias("interest_rate"),
    parse_int(F.col("LN_TERM_MOS")).alias("term_months"),
    parse_amount(F.col("LN_PMT_AMT"), 10, 2).alias("monthly_payment"),
    origination_date_col.alias("origination_date"),
    parse_date(F.col("LN_MAT_DT")).alias("maturity_date"),
    parse_date(F.col("LN_1ST_PMT_DT")).alias("first_payment_date"),
    parse_date(F.col("LN_NXT_PMT_DT")).alias("next_payment_date"),
    expand_status(F.col("LN_STAT_CD"), LOAN_STATUS_MAP).alias("status"),
    parse_int(F.col("LN_DLQ_DAYS")).alias("delinquency_days"),
    parse_amount(F.col("LN_ESCROW_BAL"), 10, 2).alias("escrow_balance"),
    parse_percent(F.col("LN_LTV_PCT")).alias("ltv_percent"),
    F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
    F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
    F.trim(F.col("PROP_ST_CD")).alias("property_state"),
    F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
    expand_status(F.col("PROP_TYP_CD"), PROPERTY_TYPE_MAP).alias("property_type"),
    parse_amount(F.col("PROP_APRS_VAL")).alias("appraised_value"),
    parse_timestamp(F.col("LN_CRET_DT")).alias("created_at"),
    parse_timestamp(F.col("LN_UPDT_DT")).alias("updated_at"),
    F.year(origination_date_col).alias("origination_year"),
    F.lit("CDW_LN_ACCT").alias("_migration_src"),
    F.current_timestamp().alias("_migrated_at"),
)

loan_target_count = transformed_loans.count()
print(f"Transformed {loan_target_count} loan account records")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Write loan accounts to Delta Lake

# COMMAND ----------

transformed_loans.write.format("delta").mode(WRITE_MODE).partitionBy("status").saveAsTable("loan_warehouse.loan_accounts")
print(f"✓ Wrote {loan_target_count} records to loan_warehouse.loan_accounts")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Ingest Payments
# MAGIC
# MAGIC **Source:** `CDW_PMT_HIST` → **Target:** `loan_warehouse.payments`
# MAGIC
# MAGIC ### Transformations applied:
# MAGIC - **FK resolution**: `LN_ACCT_NBR` (string) → `loan_account_id` (BIGINT) via lookup
# MAGIC   against `loan_accounts.account_number`
# MAGIC - **Multiple amount fields**: `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`,
# MAGIC   `PMT_LATE_FEE` — all parsed from comma-formatted strings to DECIMAL
# MAGIC - **Payment type expansion**: `PMT_TYP_CD` (REG/EXT/PRT/PRE) → REGULAR/EXTRA/PARTIAL/PREPAYMENT
# MAGIC - **Payment status expansion**: `PMT_STAT_CD` (PST/REV/NSF/PND) → POSTED/REVERSED/NSF/PENDING
# MAGIC - **Multiple date fields**: `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT` parsed to DATE
# MAGIC - **Derived column**: `payment_year` extracted from `payment_date` for partitioning
# MAGIC
# MAGIC **Partitioned by:** `payment_year` (supports time-range queries for servicing and audit)
# MAGIC
# MAGIC **⚠ Dependency:** Requires `loan_accounts` table to be populated first.

# COMMAND ----------

# Read legacy payment data
payment_source_path = f"{BASE_PATH}/cdw_pmt_hist/"
if FILE_FORMAT == "parquet":
    raw_payments = spark.read.parquet(payment_source_path)
else:
    raw_payments = spark.read.option("header", "true").option("inferSchema", "false").csv(payment_source_path)

payment_source_count = raw_payments.count()
print(f"Read {payment_source_count} payment records from source")

# COMMAND ----------

# Quarantine records missing required fields
payment_quarantine_condition = (
    F.col("PMT_SEQ_NBR").isNull()
    | F.col("LN_ACCT_NBR").isNull()
    | F.col("PMT_DT").isNull()
)

quarantined_payments = raw_payments.filter(payment_quarantine_condition)
q_count = quarantined_payments.count()
if q_count > 0:
    print(f"⚠ Quarantining {q_count} payment records")
    quarantined_payments.write.mode("append").format("delta").saveAsTable("loan_warehouse._quarantine_payments")
else:
    print("No payment records quarantined")

clean_payments = raw_payments.filter(~payment_quarantine_condition)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Resolve loan account FK and apply payment transformations

# COMMAND ----------

# Resolve loan account FK: legacy LN_ACCT_NBR → modern loan_accounts.id
loan_account_lookup = spark.table("loan_warehouse.loan_accounts").select(
    F.col("id").alias("_loan_account_id"),
    F.col("account_number").alias("_ln_acct_nbr"),
)

joined_payments = clean_payments.join(
    loan_account_lookup,
    clean_payments["LN_ACCT_NBR"] == loan_account_lookup["_ln_acct_nbr"],
    "left",
)

unresolved = joined_payments.filter(F.col("_loan_account_id").isNull()).count()
if unresolved > 0:
    print(f"⚠ {unresolved} payment records with unresolved loan account FK")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Apply payment transformations
# MAGIC
# MAGIC All five monetary fields are parsed from comma-formatted strings to DECIMAL(10,2).
# MAGIC Both the payment type and status codes are expanded to readable values.

# COMMAND ----------

payment_date_col = parse_date(F.col("PMT_DT"))

transformed_payments = joined_payments.select(
    F.col("PMT_SEQ_NBR").alias("legacy_payment_id"),
    F.col("_loan_account_id").alias("loan_account_id"),
    payment_date_col.alias("payment_date"),
    parse_amount(F.col("PMT_AMT"), 10, 2).alias("total_amount"),
    parse_amount(F.col("PMT_PRIN_AMT"), 10, 2).alias("principal_amount"),
    parse_amount(F.col("PMT_INT_AMT"), 10, 2).alias("interest_amount"),
    parse_amount(F.col("PMT_ESCROW_AMT"), 10, 2).alias("escrow_amount"),
    parse_amount(F.col("PMT_LATE_FEE"), 10, 2).alias("late_fee"),
    expand_status(F.col("PMT_TYP_CD"), PAYMENT_TYPE_MAP).alias("type"),
    expand_status(F.col("PMT_STAT_CD"), PAYMENT_STATUS_MAP).alias("status"),
    parse_date(F.col("PMT_RECV_DT")).alias("received_date"),
    parse_date(F.col("PMT_PROC_DT")).alias("processed_date"),
    parse_timestamp(F.col("PMT_CRET_DT")).alias("created_at"),
    parse_timestamp(F.col("PMT_UPDT_DT")).alias("updated_at"),
    F.year(payment_date_col).alias("payment_year"),
    F.lit("CDW_PMT_HIST").alias("_migration_src"),
    F.current_timestamp().alias("_migrated_at"),
)

payment_target_count = transformed_payments.count()
print(f"Transformed {payment_target_count} payment records")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Write payments to Delta Lake

# COMMAND ----------

transformed_payments.write.format("delta").mode(WRITE_MODE).partitionBy("payment_year").saveAsTable("loan_warehouse.payments")
print(f"✓ Wrote {payment_target_count} records to loan_warehouse.payments")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Data Quality Checks
# MAGIC
# MAGIC After ingestion, we run a comprehensive set of quality checks:
# MAGIC 1. **Row count reconciliation** — source rows = target rows + quarantined rows
# MAGIC 2. **Null checks on required fields** — no NULLs in critical columns
# MAGIC 3. **Referential integrity** — all FK references resolve correctly
# MAGIC 4. **Business rule validation** — domain-specific rules for loan data

# COMMAND ----------

pipeline_results = {
    "borrowers": {"source_count": borrower_source_count, "target_count": borrower_target_count},
    "loan_products": {"source_count": product_source_count, "target_count": product_target_count},
    "loan_accounts": {"source_count": loan_source_count, "target_count": loan_target_count},
    "payments": {"source_count": payment_source_count, "target_count": payment_target_count},
}

quality_results = []

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5.1 Row Count Reconciliation
# MAGIC
# MAGIC Verifies that every source record is accounted for: either loaded into the target table
# MAGIC or quarantined. A mismatch indicates records were silently lost.

# COMMAND ----------

print("=" * 60)
print("ROW COUNT RECONCILIATION")
print("=" * 60)
for table_name, counts in pipeline_results.items():
    src = counts["source_count"]
    tgt = counts["target_count"]
    quarantined = src - tgt
    passed = (tgt + quarantined) == src
    status = "PASS" if passed else "FAIL"
    quality_results.append({"category": "Row Count", "check": f"{table_name}", "passed": passed})
    print(f"  [{status}] {table_name}: source={src}, target={tgt}, quarantined={quarantined}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5.2 Null Checks on Required Fields
# MAGIC
# MAGIC These columns must never be NULL in the target tables. NULLs here indicate
# MAGIC either a transformation bug or a data issue that should have been quarantined.

# COMMAND ----------

print("=" * 60)
print("NULL CHECKS ON REQUIRED FIELDS")
print("=" * 60)

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_warehouse.loan_products": ["code", "name", "type"],
    "loan_warehouse.loan_accounts": ["account_number", "borrower_id", "product_id", "status"],
    "loan_warehouse.payments": ["loan_account_id", "payment_date", "status"],
}

for table, columns in REQUIRED_FIELDS.items():
    df = spark.table(table)
    total = df.count()
    for col_name in columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        passed = null_count == 0
        status = "PASS" if passed else "FAIL"
        quality_results.append({"category": "Null Check", "check": f"{table}.{col_name}", "passed": passed})
        print(f"  [{status}] {table}.{col_name}: {null_count} nulls / {total} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5.3 Referential Integrity
# MAGIC
# MAGIC Verifies that every FK in child tables points to a valid record in the parent table.
# MAGIC Uses `left_anti` joins to find orphan rows (child records with no matching parent).
# MAGIC Note: Delta Lake PK/FK constraints are informational only — this is the actual enforcement.

# COMMAND ----------

print("=" * 60)
print("REFERENTIAL INTEGRITY")
print("=" * 60)

ri_checks = [
    ("loan_accounts → borrowers", "loan_warehouse.loan_accounts", "borrower_id", "loan_warehouse.borrowers", "id"),
    ("loan_accounts → loan_products", "loan_warehouse.loan_accounts", "product_id", "loan_warehouse.loan_products", "id"),
    ("payments → loan_accounts", "loan_warehouse.payments", "loan_account_id", "loan_warehouse.loan_accounts", "id"),
]

for label, child_tbl, child_col, parent_tbl, parent_col in ri_checks:
    child_df = spark.table(child_tbl)
    parent_df = spark.table(parent_tbl)
    orphans = (
        child_df.join(parent_df, child_df[child_col] == parent_df[parent_col], "left_anti")
        .filter(F.col(child_col).isNotNull())
        .count()
    )
    total = child_df.count()
    passed = orphans == 0
    status = "PASS" if passed else "FAIL"
    quality_results.append({"category": "Referential Integrity", "check": label, "passed": passed})
    print(f"  [{status}] {label}: {orphans} orphans / {total} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5.4 Business Rule Validation
# MAGIC
# MAGIC Domain-specific rules that should hold true for correctly migrated loan data:
# MAGIC - Active loans must have a positive balance
# MAGIC - Closed loans must have a maturity date
# MAGIC - Interest rates must be within [0, 100]
# MAGIC - Delinquency days must be non-negative
# MAGIC - Posted payments must have a positive amount
# MAGIC - Origination date must precede maturity date
# MAGIC - LTV percent must be within [0, 200]

# COMMAND ----------

print("=" * 60)
print("BUSINESS RULE VALIDATION")
print("=" * 60)

loans = spark.table("loan_warehouse.loan_accounts")
payments = spark.table("loan_warehouse.payments")

rules = []

# Rule 1: Active loans balance > 0
violations = loans.filter((F.col("status") == "ACTIVE") & (F.col("current_balance").isNotNull()) & (F.col("current_balance") <= 0)).count()
rules.append(("Active loans balance > 0", violations == 0, violations))

# Rule 2: Closed loans have maturity_date
violations = loans.filter((F.col("status") == "CLOSED") & F.col("maturity_date").isNull()).count()
rules.append(("Closed loans have maturity_date", violations == 0, violations))

# Rule 3: Interest rate in [0, 100]
violations = loans.filter((F.col("interest_rate").isNotNull()) & ((F.col("interest_rate") < 0) | (F.col("interest_rate") > 100))).count()
rules.append(("Interest rate in [0, 100]", violations == 0, violations))

# Rule 4: Delinquency days >= 0
violations = loans.filter((F.col("delinquency_days").isNotNull()) & (F.col("delinquency_days") < 0)).count()
rules.append(("Delinquency days >= 0", violations == 0, violations))

# Rule 5: Posted payments amount > 0
violations = payments.filter((F.col("status") == "POSTED") & (F.col("total_amount").isNotNull()) & (F.col("total_amount") <= 0)).count()
rules.append(("Posted payments amount > 0", violations == 0, violations))

# Rule 6: Origination before maturity
violations = loans.filter((F.col("origination_date").isNotNull()) & (F.col("maturity_date").isNotNull()) & (F.col("origination_date") >= F.col("maturity_date"))).count()
rules.append(("Origination before maturity", violations == 0, violations))

# Rule 7: LTV in [0, 200]
violations = loans.filter((F.col("ltv_percent").isNotNull()) & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))).count()
rules.append(("LTV in [0, 200]", violations == 0, violations))

for rule_name, passed, violation_count in rules:
    status = "PASS" if passed else "FAIL"
    quality_results.append({"category": "Business Rule", "check": rule_name, "passed": passed})
    print(f"  [{status}] {rule_name}: {violation_count} violations")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC Final migration summary with overall pass/fail status.

# COMMAND ----------

total_checks = len(quality_results)
passed_checks = sum(1 for r in quality_results if r["passed"])
failed_checks = total_checks - passed_checks

print("=" * 60)
print("MIGRATION SUMMARY")
print("=" * 60)
print()
for table_name, counts in pipeline_results.items():
    print(f"  {table_name:20s}  source={counts['source_count']:>6d}  target={counts['target_count']:>6d}")
print()
print(f"  Quality checks: {passed_checks}/{total_checks} passed, {failed_checks} failed")
print()
if failed_checks == 0:
    print("  ✓ ALL CHECKS PASSED — migration complete")
else:
    print(f"  ✗ {failed_checks} CHECK(S) FAILED — review results above")
    for r in quality_results:
        if not r["passed"]:
            print(f"    - [{r['category']}] {r['check']}")
