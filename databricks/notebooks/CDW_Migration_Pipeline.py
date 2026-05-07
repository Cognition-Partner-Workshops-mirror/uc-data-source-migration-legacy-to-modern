# Databricks notebook source

# MAGIC %md
# MAGIC # CDW Legacy-to-Modern Migration Pipeline
# MAGIC
# MAGIC This notebook migrates loan management data from the legacy CDW (Core Data Warehouse)
# MAGIC all-VARCHAR schema into a modern, typed Delta Lake schema.
# MAGIC
# MAGIC ## Legacy Schema Issues
# MAGIC - **All-VARCHAR columns** — dates, amounts, and integers stored as strings
# MAGIC - **Cryptic column names** — `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`
# MAGIC - **Denormalized data** — borrower fields embedded directly in loan account rows
# MAGIC - **Status code abbreviations** — `ACT`, `CLO`, `DFT`, `FRB` instead of full names
# MAGIC - **No foreign keys** — no referential integrity enforcement
# MAGIC
# MAGIC ## Pipeline Steps
# MAGIC 1. Configure parameters and shared transforms
# MAGIC 2. Create the target Delta Lake schema and tables
# MAGIC 3. Ingest **borrowers** (`CDW_BORR_MSTR`)
# MAGIC 4. Ingest **loan products** (`CDW_LN_PROD`)
# MAGIC 5. Ingest **loan accounts** (`CDW_LN_ACCT`) — with FK resolution and denorm removal
# MAGIC 6. Ingest **payments** (`CDW_PMT_HIST`) — with FK resolution
# MAGIC 7. Run data quality checks

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 0: Parameters
# MAGIC
# MAGIC Set the base path to your legacy data exports and the target catalog/schema.
# MAGIC Adjust these widgets for your environment.

# COMMAND ----------

dbutils.widgets.text("source_base_path", "dbfs:/mnt/legacy/", "Source Base Path")
dbutils.widgets.dropdown("source_format", "csv", ["csv", "parquet"], "Source Format")
dbutils.widgets.text("target_catalog", "loan_migration", "Target Catalog")
dbutils.widgets.text("target_schema", "loan_warehouse", "Target Schema")

SOURCE_BASE = dbutils.widgets.get("source_base_path").rstrip("/")
SOURCE_FMT  = dbutils.widgets.get("source_format")
CATALOG     = dbutils.widgets.get("target_catalog")
SCHEMA      = dbutils.widgets.get("target_schema")

print(f"Source: {SOURCE_BASE} ({SOURCE_FMT})")
print(f"Target: {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Shared Transformation Helpers
# MAGIC
# MAGIC These functions handle the four core transformation patterns found across all legacy tables:
# MAGIC
# MAGIC | Pattern | Example | Function |
# MAGIC |---------|---------|----------|
# MAGIC | **Date parsing** | `"03/15/1978"` → `DATE` | `parse_date()` / `parse_timestamp()` |
# MAGIC | **Amount parsing** | `"285,000"` → `DECIMAL(12,2)` | `parse_amount()` |
# MAGIC | **Integer parsing** | `"745"` → `INT` | `parse_int()` |
# MAGIC | **Status expansion** | `"ACT"` → `"ACTIVE"` | `expand_status()` |
# MAGIC
# MAGIC Unknown status codes are preserved as `"UNKNOWN:<code>"` rather than silently dropped,
# MAGIC so the data quality framework can detect and report them.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType, DecimalType, IntegerType, StringType, StructField, StructType,
)

# ── Date parsing ──────────────────────────────────────────────────────────
# Legacy dates are stored as MM/DD/YYYY strings.
# to_date with the format pattern converts them; nulls/malformed values → NULL.

def parse_date(col_name):
    """Convert MM/DD/YYYY string → DateType."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy")

def parse_timestamp(col_name):
    """Convert MM/DD/YYYY string → TimestampType (midnight)."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy")

# ── Numeric parsing ──────────────────────────────────────────────────────
# Amounts like "285,000" and "1,487.02" use commas as thousands separators.
# We strip commas then cast to DECIMAL.

def parse_amount(col_name, precision=12, scale=2):
    """Strip commas and cast to DecimalType."""
    return F.regexp_replace(F.col(col_name), ",", "").cast(DecimalType(precision, scale))

def parse_int(col_name):
    """Cast string → IntegerType."""
    return F.col(col_name).cast(IntegerType())

def parse_rate(col_name, precision=5, scale=3):
    """Cast rate string like '4.750' → DecimalType(5,3)."""
    return F.col(col_name).cast(DecimalType(precision, scale))

def parse_percent(col_name, precision=5, scale=2):
    """Cast percent string like '82.5' → DecimalType(5,2)."""
    return F.col(col_name).cast(DecimalType(precision, scale))

# ── Status code expansion ─────────────────────────────────────────────────
# Each domain uses short abbreviations. We build a CASE expression from a
# mapping dict. Unknown codes get prefixed with "UNKNOWN:" for traceability.

def expand_status(col_name, mapping, alias=None):
    """Map short codes → full descriptions via CASE WHEN."""
    expr = F.col(col_name)
    case_expr = F.when(expr.isNull(), F.lit(None))
    for code, label in mapping.items():
        case_expr = case_expr.when(expr == code, F.lit(label))
    case_expr = case_expr.otherwise(F.concat(F.lit("UNKNOWN:"), expr))
    return case_expr.alias(alias or col_name)

def expand_product_active(col_name):
    """Convert product status code → boolean is_active flag."""
    expr = F.col(col_name)
    return (
        F.when(expr == "ACT", F.lit(True))
        .when(expr == "INA", F.lit(False))
        .otherwise(F.lit(None))
        .alias("is_active")
    )

# ── Status code mappings ──────────────────────────────────────────────────

LOAN_STATUS_MAP = {"ACT": "ACTIVE", "CLO": "CLOSED", "DFT": "DEFAULT", "FRB": "FORBEARANCE"}
BORROWER_STATUS_MAP = {"ACT": "ACTIVE", "INA": "INACTIVE"}
PAYMENT_TYPE_MAP = {"REG": "REGULAR", "EXT": "EXTRA", "PRT": "PARTIAL", "PRE": "PREPAYMENT"}
PAYMENT_STATUS_MAP = {"PST": "POSTED", "REV": "REVERSED", "NSF": "NSF", "PND": "PENDING"}
PROPERTY_TYPE_MAP = {"SFR": "Single Family", "CND": "Condominium", "MFR": "Multi-Family", "TWN": "Townhouse"}

print("Transformation helpers loaded.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Create Target Delta Lake Schema & Tables
# MAGIC
# MAGIC We create a Unity Catalog schema and four Delta tables with:
# MAGIC - **Proper Spark SQL types** (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP)
# MAGIC - **Identity columns** for surrogate primary keys
# MAGIC - **Foreign key constraints** for referential integrity
# MAGIC - **Partitioning** optimized for common query patterns:
# MAGIC   - `borrowers` → partitioned by `state` (regional compliance queries)
# MAGIC   - `loan_accounts` → partitioned by `status` (portfolio segmentation)
# MAGIC   - `payments` → partitioned by `payment_year` (time-range analytics)
# MAGIC   - `loan_products` → no partitioning (small reference table)

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
spark.sql(f"USE SCHEMA {SCHEMA}")
print(f"Using {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2a: Borrowers table
# MAGIC
# MAGIC Source: `CDW_BORR_MSTR` — the borrower master table with 20 VARCHAR columns.
# MAGIC Partitioned by `state` for regional compliance and analytics queries.

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.borrowers (
    borrower_id       BIGINT GENERATED ALWAYS AS IDENTITY,
    external_id       STRING NOT NULL,
    first_name        STRING NOT NULL,
    last_name         STRING NOT NULL,
    middle_initial    STRING,
    ssn_hash          STRING,
    date_of_birth     DATE,
    address_line1     STRING,
    address_line2     STRING,
    city              STRING,
    state             STRING,
    zip_code          STRING,
    phone             STRING,
    email             STRING,
    credit_score      INT,
    employment_status STRING,
    annual_income     DECIMAL(12,2),
    status            STRING NOT NULL DEFAULT 'ACTIVE',
    created_at        TIMESTAMP,
    updated_at        TIMESTAMP,
    _load_ts          TIMESTAMP DEFAULT current_timestamp(),
    _source_system    STRING DEFAULT 'CDW_BORR_MSTR'
) USING DELTA
PARTITIONED BY (state)
TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true', 'delta.autoOptimize.autoCompact' = 'true')
""")
print("borrowers table created.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2b: Loan Products table
# MAGIC
# MAGIC Source: `CDW_LN_PROD` — small reference table defining available loan products.
# MAGIC No partitioning needed given low cardinality (<100 rows).

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.loan_products (
    product_id      BIGINT GENERATED ALWAYS AS IDENTITY,
    code            STRING NOT NULL,
    name            STRING NOT NULL,
    type            STRING NOT NULL,
    term_months     INT    NOT NULL,
    rate_type       STRING NOT NULL,
    min_amount      DECIMAL(12,2),
    max_amount      DECIMAL(12,2),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    effective_date  DATE,
    expiration_date DATE,
    _load_ts        TIMESTAMP DEFAULT current_timestamp(),
    _source_system  STRING DEFAULT 'CDW_LN_PROD'
) USING DELTA
TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true', 'delta.autoOptimize.autoCompact' = 'true')
""")
print("loan_products table created.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2c: Loan Accounts table
# MAGIC
# MAGIC Source: `CDW_LN_ACCT` — the denormalized loan table with 27 columns including
# MAGIC embedded borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`).
# MAGIC
# MAGIC In the modern schema, the denormalized borrower columns are **dropped** and
# MAGIC replaced by a `borrower_id` FK. The `product_id` FK replaces `PROD_CD`.
# MAGIC
# MAGIC Partitioned by `status` (ACTIVE/CLOSED/DEFAULT/FORBEARANCE) for portfolio
# MAGIC segmentation queries.

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.loan_accounts (
    loan_account_id    BIGINT GENERATED ALWAYS AS IDENTITY,
    account_number     STRING NOT NULL,
    borrower_id        BIGINT NOT NULL,
    product_id         BIGINT NOT NULL,
    original_amount    DECIMAL(12,2) NOT NULL,
    current_balance    DECIMAL(12,2) NOT NULL,
    interest_rate      DECIMAL(5,3)  NOT NULL,
    term_months        INT           NOT NULL,
    monthly_payment    DECIMAL(10,2) NOT NULL,
    origination_date   DATE          NOT NULL,
    maturity_date      DATE          NOT NULL,
    first_payment_date DATE,
    next_payment_date  DATE,
    status             STRING NOT NULL DEFAULT 'ACTIVE',
    delinquency_days   INT    DEFAULT 0,
    escrow_balance     DECIMAL(10,2) DEFAULT 0,
    ltv_percent        DECIMAL(5,2),
    property_address   STRING,
    property_city      STRING,
    property_state     STRING,
    property_zip       STRING,
    property_type      STRING,
    appraised_value    DECIMAL(12,2),
    created_at         TIMESTAMP,
    updated_at         TIMESTAMP,
    _load_ts           TIMESTAMP DEFAULT current_timestamp(),
    _source_system     STRING DEFAULT 'CDW_LN_ACCT'
) USING DELTA
PARTITIONED BY (status)
TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true', 'delta.autoOptimize.autoCompact' = 'true')
""")
print("loan_accounts table created.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2d: Payments table
# MAGIC
# MAGIC Source: `CDW_PMT_HIST` — payment history with 14 VARCHAR columns.
# MAGIC Preserves the original `PMT_SEQ_NBR` as `legacy_sequence_nbr` for audit traceability.
# MAGIC Partitioned by `payment_year` for time-range queries.

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.payments (
    payment_id          BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING,
    loan_account_id     BIGINT NOT NULL,
    payment_date        DATE   NOT NULL,
    total_amount        DECIMAL(10,2) NOT NULL,
    principal_amount    DECIMAL(10,2),
    interest_amount     DECIMAL(10,2),
    escrow_amount       DECIMAL(10,2),
    late_fee            DECIMAL(10,2) DEFAULT 0,
    type                STRING NOT NULL,
    status              STRING NOT NULL,
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    payment_year        INT,
    _load_ts            TIMESTAMP DEFAULT current_timestamp(),
    _source_system      STRING DEFAULT 'CDW_PMT_HIST'
) USING DELTA
PARTITIONED BY (payment_year)
TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true', 'delta.autoOptimize.autoCompact' = 'true')
""")
print("payments table created.")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Step 3: Ingest Borrowers (`CDW_BORR_MSTR`)
# MAGIC
# MAGIC ### Transformations applied:
# MAGIC | Legacy Column | Modern Column | Transformation |
# MAGIC |---|---|---|
# MAGIC | `BORR_DOB_DT` | `date_of_birth` | Parse `MM/DD/YYYY` → DATE |
# MAGIC | `BORR_CRDT_SCR` | `credit_score` | Cast VARCHAR → INT |
# MAGIC | `BORR_ANN_INCM` | `annual_income` | Strip commas → DECIMAL(12,2) |
# MAGIC | `BORR_CRET_DT` / `BORR_UPDT_DT` | `created_at` / `updated_at` | Parse → TIMESTAMP |
# MAGIC | `BORR_STAT_CD` | `status` | Expand: `ACT`→`ACTIVE`, `INA`→`INACTIVE` |
# MAGIC | `BORR_REC_TYP` | *(dropped)* | Internal record type; no business meaning |
# MAGIC
# MAGIC All other columns are direct copies with human-readable names.
# MAGIC Rows with null `external_id` or `first_name` are flagged but **not dropped**.

# COMMAND ----------

BORR_SCHEMA = StructType([
    StructField("BORR_ID", StringType()),         StructField("BORR_FST_NM", StringType()),
    StructField("BORR_LST_NM", StringType()),     StructField("BORR_MID_INIT", StringType()),
    StructField("BORR_SSN_ENCR", StringType()),   StructField("BORR_DOB_DT", StringType()),
    StructField("BORR_ADDR_LN1", StringType()),   StructField("BORR_ADDR_LN2", StringType()),
    StructField("BORR_CTY_NM", StringType()),     StructField("BORR_ST_CD", StringType()),
    StructField("BORR_ZIP_CD", StringType()),     StructField("BORR_PH_NBR", StringType()),
    StructField("BORR_EMAIL_ADDR", StringType()), StructField("BORR_CRDT_SCR", StringType()),
    StructField("BORR_EMP_STAT", StringType()),   StructField("BORR_ANN_INCM", StringType()),
    StructField("BORR_CRET_DT", StringType()),    StructField("BORR_UPDT_DT", StringType()),
    StructField("BORR_STAT_CD", StringType()),    StructField("BORR_REC_TYP", StringType()),
])

# Read the legacy source data
raw_borrowers = (
    spark.read.schema(BORR_SCHEMA)
    .option("header", "true")
    .format(SOURCE_FMT)
    .load(f"{SOURCE_BASE}/cdw_borr_mstr/")
)
print(f"Read {raw_borrowers.count()} raw borrower records")
raw_borrowers.show(5, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Apply borrower transformations
# MAGIC
# MAGIC - **Trim whitespace** on name fields to handle any padding from legacy extracts
# MAGIC - **Parse dates** from `MM/DD/YYYY` strings to proper DATE/TIMESTAMP types
# MAGIC - **Parse amounts** by stripping commas then casting to DECIMAL
# MAGIC - **Expand status codes** using the CASE-based `expand_status` helper
# MAGIC - **Drop `BORR_REC_TYP`** — an internal legacy field with no modern equivalent

# COMMAND ----------

borrowers_df = raw_borrowers.select(
    F.col("BORR_ID").alias("external_id"),
    F.trim(F.col("BORR_FST_NM")).alias("first_name"),
    F.trim(F.col("BORR_LST_NM")).alias("last_name"),
    F.col("BORR_MID_INIT").alias("middle_initial"),
    F.col("BORR_SSN_ENCR").alias("ssn_hash"),
    parse_date("BORR_DOB_DT").alias("date_of_birth"),
    F.col("BORR_ADDR_LN1").alias("address_line1"),
    F.col("BORR_ADDR_LN2").alias("address_line2"),
    F.col("BORR_CTY_NM").alias("city"),
    F.col("BORR_ST_CD").alias("state"),
    F.col("BORR_ZIP_CD").alias("zip_code"),
    F.col("BORR_PH_NBR").alias("phone"),
    F.col("BORR_EMAIL_ADDR").alias("email"),
    parse_int("BORR_CRDT_SCR").alias("credit_score"),
    F.col("BORR_EMP_STAT").alias("employment_status"),
    parse_amount("BORR_ANN_INCM").alias("annual_income"),
    parse_timestamp("BORR_CRET_DT").alias("created_at"),
    parse_timestamp("BORR_UPDT_DT").alias("updated_at"),
    expand_status("BORR_STAT_CD", BORROWER_STATUS_MAP, alias="status"),
)

# Flag invalid rows (null PK or required fields) — do NOT drop them
borrowers_df = borrowers_df.withColumn(
    "_is_valid",
    F.col("external_id").isNotNull() & F.col("first_name").isNotNull(),
)

invalid_count = borrowers_df.filter(~F.col("_is_valid")).count()
print(f"Invalid borrower rows (null external_id or first_name): {invalid_count}")
borrowers_df.show(5, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Write borrowers to Delta Lake
# MAGIC
# MAGIC The `_is_valid` column is dropped before writing — it was only used for logging.
# MAGIC Invalid rows are still written so they appear in the quality report for investigation.

# COMMAND ----------

(
    borrowers_df.drop("_is_valid")
    .write.format("delta")
    .mode("overwrite")
    .option("mergeSchema", "true")
    .saveAsTable(f"{SCHEMA}.borrowers")
)
borr_count = spark.table(f"{SCHEMA}.borrowers").count()
print(f"Wrote {borr_count} borrowers to {SCHEMA}.borrowers")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Step 4: Ingest Loan Products (`CDW_LN_PROD`)
# MAGIC
# MAGIC ### Transformations applied:
# MAGIC | Legacy Column | Modern Column | Transformation |
# MAGIC |---|---|---|
# MAGIC | `PROD_TERM_MOS` | `term_months` | Cast VARCHAR → INT |
# MAGIC | `PROD_MIN_AMT` / `PROD_MAX_AMT` | `min_amount` / `max_amount` | Strip commas → DECIMAL(12,2) |
# MAGIC | `PROD_STAT_CD` | `is_active` | `ACT`→`true`, `INA`→`false` (VARCHAR→BOOLEAN) |
# MAGIC | `PROD_EFF_DT` / `PROD_EXP_DT` | `effective_date` / `expiration_date` | Parse → DATE |
# MAGIC
# MAGIC This is a small reference table — typically <100 rows in production.

# COMMAND ----------

PROD_SCHEMA = StructType([
    StructField("PROD_CD", StringType()),       StructField("PROD_DESC_TXT", StringType()),
    StructField("PROD_TYP_CD", StringType()),   StructField("PROD_TERM_MOS", StringType()),
    StructField("PROD_RT_TYP", StringType()),   StructField("PROD_MIN_AMT", StringType()),
    StructField("PROD_MAX_AMT", StringType()),  StructField("PROD_STAT_CD", StringType()),
    StructField("PROD_EFF_DT", StringType()),   StructField("PROD_EXP_DT", StringType()),
])

raw_products = (
    spark.read.schema(PROD_SCHEMA)
    .option("header", "true")
    .format(SOURCE_FMT)
    .load(f"{SOURCE_BASE}/cdw_ln_prod/")
)
print(f"Read {raw_products.count()} raw loan product records")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Apply loan product transformations
# MAGIC
# MAGIC The key transformation here is converting `PROD_STAT_CD` from a string code
# MAGIC to a proper `BOOLEAN` (`is_active`). This is the only table where a status
# MAGIC code maps to a boolean rather than an expanded string.

# COMMAND ----------

products_df = raw_products.select(
    F.col("PROD_CD").alias("code"),
    F.trim(F.col("PROD_DESC_TXT")).alias("name"),
    F.col("PROD_TYP_CD").alias("type"),
    parse_int("PROD_TERM_MOS").alias("term_months"),
    F.col("PROD_RT_TYP").alias("rate_type"),
    parse_amount("PROD_MIN_AMT").alias("min_amount"),
    parse_amount("PROD_MAX_AMT").alias("max_amount"),
    expand_product_active("PROD_STAT_CD"),
    parse_date("PROD_EFF_DT").alias("effective_date"),
    parse_date("PROD_EXP_DT").alias("expiration_date"),
)

products_df = products_df.withColumn(
    "_is_valid",
    F.col("code").isNotNull() & F.col("name").isNotNull(),
)

invalid_count = products_df.filter(~F.col("_is_valid")).count()
print(f"Invalid product rows: {invalid_count}")
products_df.show(5, truncate=False)

# COMMAND ----------

(
    products_df.drop("_is_valid")
    .write.format("delta")
    .mode("overwrite")
    .option("mergeSchema", "true")
    .saveAsTable(f"{SCHEMA}.loan_products")
)
prod_count = spark.table(f"{SCHEMA}.loan_products").count()
print(f"Wrote {prod_count} loan products to {SCHEMA}.loan_products")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Step 5: Ingest Loan Accounts (`CDW_LN_ACCT`)
# MAGIC
# MAGIC This is the most complex ingestion step because it involves:
# MAGIC
# MAGIC 1. **Denormalization removal** — dropping the embedded borrower columns
# MAGIC    (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) and replacing them with a
# MAGIC    `borrower_id` FK resolved via the already-loaded `borrowers` table.
# MAGIC
# MAGIC 2. **Product FK resolution** — replacing `PROD_CD` with `product_id` via
# MAGIC    lookup against the `loan_products` table.
# MAGIC
# MAGIC 3. **Multiple type conversions** — 8 amount fields, 6 date fields, 2 integer
# MAGIC    fields, and 2 status code expansions (loan status + property type).
# MAGIC
# MAGIC ### Transformations applied:
# MAGIC | Legacy Column | Modern Column | Transformation |
# MAGIC |---|---|---|
# MAGIC | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` | *(dropped)* | Denormalized; use `borrower_id` FK |
# MAGIC | `BORR_ID` | `borrower_id` | FK lookup: `borrowers.external_id` → `borrowers.borrower_id` |
# MAGIC | `PROD_CD` | `product_id` | FK lookup: `loan_products.code` → `loan_products.product_id` |
# MAGIC | `LN_STAT_CD` | `status` | `ACT`→`ACTIVE`, `CLO`→`CLOSED`, `DFT`→`DEFAULT`, `FRB`→`FORBEARANCE` |
# MAGIC | `PROP_TYP_CD` | `property_type` | `SFR`→`Single Family`, `CND`→`Condominium`, etc. |
# MAGIC | All amount columns | typed columns | Strip commas → DECIMAL |
# MAGIC | All date columns | typed columns | Parse `MM/DD/YYYY` → DATE or TIMESTAMP |

# COMMAND ----------

ACCT_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType()),   StructField("BORR_ID", StringType()),
    StructField("BORR_FST_NM", StringType()),   StructField("BORR_LST_NM", StringType()),
    StructField("BORR_SSN_LST4", StringType()), StructField("PROD_CD", StringType()),
    StructField("LN_ORIG_AMT", StringType()),   StructField("LN_CURR_BAL", StringType()),
    StructField("LN_INT_RT", StringType()),     StructField("LN_TERM_MOS", StringType()),
    StructField("LN_PMT_AMT", StringType()),    StructField("LN_ORIG_DT", StringType()),
    StructField("LN_MAT_DT", StringType()),     StructField("LN_1ST_PMT_DT", StringType()),
    StructField("LN_NXT_PMT_DT", StringType()), StructField("LN_STAT_CD", StringType()),
    StructField("LN_DLQ_DAYS", StringType()),   StructField("LN_ESCROW_BAL", StringType()),
    StructField("LN_LTV_PCT", StringType()),    StructField("PROP_ADDR_LN1", StringType()),
    StructField("PROP_CTY_NM", StringType()),   StructField("PROP_ST_CD", StringType()),
    StructField("PROP_ZIP_CD", StringType()),   StructField("PROP_TYP_CD", StringType()),
    StructField("PROP_APRS_VAL", StringType()), StructField("LN_CRET_DT", StringType()),
    StructField("LN_UPDT_DT", StringType()),
])

raw_accounts = (
    spark.read.schema(ACCT_SCHEMA)
    .option("header", "true")
    .format(SOURCE_FMT)
    .load(f"{SOURCE_BASE}/cdw_ln_acct/")
)
print(f"Read {raw_accounts.count()} raw loan account records")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Build FK lookup tables
# MAGIC
# MAGIC We load slim DataFrames from the already-ingested dimension tables to resolve
# MAGIC legacy string identifiers into modern BIGINT foreign keys via left joins.
# MAGIC
# MAGIC - `BORR_ID` → `borrower_id` (via `borrowers.external_id`)
# MAGIC - `PROD_CD` → `product_id` (via `loan_products.code`)
# MAGIC
# MAGIC Unresolved FKs produce `NULL` and are logged as warnings (not dropped).

# COMMAND ----------

borrower_lkp = spark.table(f"{SCHEMA}.borrowers").select(
    F.col("borrower_id"), F.col("external_id")
)
product_lkp = spark.table(f"{SCHEMA}.loan_products").select(
    F.col("product_id"), F.col("code").alias("product_code")
)
print(f"Borrower lookup: {borrower_lkp.count()} rows")
print(f"Product lookup:  {product_lkp.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Apply loan account transformations and FK resolution
# MAGIC
# MAGIC The three denormalized borrower columns (`BORR_FST_NM`, `BORR_LST_NM`,
# MAGIC `BORR_SSN_LST4`) are intentionally **not selected** — they are redundant
# MAGIC with the borrowers dimension table and would violate normalization.
# MAGIC
# MAGIC Two sequential left joins resolve the foreign keys. If a lookup fails
# MAGIC (e.g., orphaned `BORR_ID` with no matching borrower), the FK column will
# MAGIC be `NULL` and the quality framework will flag it.

# COMMAND ----------

# Step 1: Apply all type transformations and column renames
accounts_base = raw_accounts.select(
    F.col("LN_ACCT_NBR").alias("account_number"),
    F.col("BORR_ID").alias("_borr_ext_id"),          # temporary — for FK join
    F.col("PROD_CD").alias("_prod_cd"),               # temporary — for FK join
    parse_amount("LN_ORIG_AMT").alias("original_amount"),
    parse_amount("LN_CURR_BAL").alias("current_balance"),
    parse_rate("LN_INT_RT").alias("interest_rate"),
    parse_int("LN_TERM_MOS").alias("term_months"),
    parse_amount("LN_PMT_AMT", 10, 2).alias("monthly_payment"),
    parse_date("LN_ORIG_DT").alias("origination_date"),
    parse_date("LN_MAT_DT").alias("maturity_date"),
    parse_date("LN_1ST_PMT_DT").alias("first_payment_date"),
    parse_date("LN_NXT_PMT_DT").alias("next_payment_date"),
    expand_status("LN_STAT_CD", LOAN_STATUS_MAP, alias="status"),
    parse_int("LN_DLQ_DAYS").alias("delinquency_days"),
    parse_amount("LN_ESCROW_BAL", 10, 2).alias("escrow_balance"),
    parse_percent("LN_LTV_PCT").alias("ltv_percent"),
    F.col("PROP_ADDR_LN1").alias("property_address"),
    F.col("PROP_CTY_NM").alias("property_city"),
    F.col("PROP_ST_CD").alias("property_state"),
    F.col("PROP_ZIP_CD").alias("property_zip"),
    expand_status("PROP_TYP_CD", PROPERTY_TYPE_MAP, alias="property_type"),
    parse_amount("PROP_APRS_VAL").alias("appraised_value"),
    parse_timestamp("LN_CRET_DT").alias("created_at"),
    parse_timestamp("LN_UPDT_DT").alias("updated_at"),
)

# Step 2: Resolve borrower FK
with_borrower = accounts_base.join(
    borrower_lkp,
    accounts_base["_borr_ext_id"] == borrower_lkp["external_id"],
    "left",
).drop("external_id")

# Step 3: Resolve product FK
accounts_df = with_borrower.join(
    product_lkp,
    with_borrower["_prod_cd"] == product_lkp["product_code"],
    "left",
).drop("product_code", "_borr_ext_id", "_prod_cd")

# Log unresolved FKs
unresolved_borr = accounts_df.filter(F.col("borrower_id").isNull()).count()
unresolved_prod = accounts_df.filter(F.col("product_id").isNull()).count()
print(f"Unresolved borrower FKs: {unresolved_borr}")
print(f"Unresolved product FKs:  {unresolved_prod}")
accounts_df.show(5, truncate=False)

# COMMAND ----------

(
    accounts_df
    .write.format("delta")
    .mode("overwrite")
    .option("mergeSchema", "true")
    .saveAsTable(f"{SCHEMA}.loan_accounts")
)
acct_count = spark.table(f"{SCHEMA}.loan_accounts").count()
print(f"Wrote {acct_count} loan accounts to {SCHEMA}.loan_accounts")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Step 6: Ingest Payments (`CDW_PMT_HIST`)
# MAGIC
# MAGIC ### Transformations applied:
# MAGIC | Legacy Column | Modern Column | Transformation |
# MAGIC |---|---|---|
# MAGIC | `PMT_SEQ_NBR` | `legacy_sequence_nbr` | Preserved for audit traceability |
# MAGIC | `LN_ACCT_NBR` | `loan_account_id` | FK lookup: `loan_accounts.account_number` → `loan_accounts.loan_account_id` |
# MAGIC | `PMT_TYP_CD` | `type` | `REG`→`REGULAR`, `EXT`→`EXTRA`, `PRT`→`PARTIAL`, `PRE`→`PREPAYMENT` |
# MAGIC | `PMT_STAT_CD` | `status` | `PST`→`POSTED`, `REV`→`REVERSED`, `NSF`→`NSF`, `PND`→`PENDING` |
# MAGIC | All amount columns | typed columns | Strip commas → DECIMAL(10,2) |
# MAGIC | All date columns | typed columns | Parse `MM/DD/YYYY` → DATE or TIMESTAMP |
# MAGIC
# MAGIC A computed `payment_year` column is added for partitioning.

# COMMAND ----------

PMT_SCHEMA = StructType([
    StructField("PMT_SEQ_NBR", StringType()),    StructField("LN_ACCT_NBR", StringType()),
    StructField("PMT_DT", StringType()),         StructField("PMT_AMT", StringType()),
    StructField("PMT_PRIN_AMT", StringType()),   StructField("PMT_INT_AMT", StringType()),
    StructField("PMT_ESCROW_AMT", StringType()), StructField("PMT_LATE_FEE", StringType()),
    StructField("PMT_TYP_CD", StringType()),     StructField("PMT_STAT_CD", StringType()),
    StructField("PMT_RECV_DT", StringType()),    StructField("PMT_PROC_DT", StringType()),
    StructField("PMT_CRET_DT", StringType()),    StructField("PMT_UPDT_DT", StringType()),
])

raw_payments = (
    spark.read.schema(PMT_SCHEMA)
    .option("header", "true")
    .format(SOURCE_FMT)
    .load(f"{SOURCE_BASE}/cdw_pmt_hist/")
)
print(f"Read {raw_payments.count()} raw payment records")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Apply payment transformations and FK resolution
# MAGIC
# MAGIC The loan account FK is resolved by joining on `LN_ACCT_NBR = account_number`.
# MAGIC The `payment_year` column is computed from `payment_date` for partitioning.

# COMMAND ----------

loan_lkp = spark.table(f"{SCHEMA}.loan_accounts").select(
    F.col("loan_account_id"), F.col("account_number")
)

payments_base = raw_payments.select(
    F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),
    F.col("LN_ACCT_NBR").alias("_acct_nbr"),
    parse_date("PMT_DT").alias("payment_date"),
    parse_amount("PMT_AMT", 10, 2).alias("total_amount"),
    parse_amount("PMT_PRIN_AMT", 10, 2).alias("principal_amount"),
    parse_amount("PMT_INT_AMT", 10, 2).alias("interest_amount"),
    parse_amount("PMT_ESCROW_AMT", 10, 2).alias("escrow_amount"),
    parse_amount("PMT_LATE_FEE", 10, 2).alias("late_fee"),
    expand_status("PMT_TYP_CD", PAYMENT_TYPE_MAP, alias="type"),
    expand_status("PMT_STAT_CD", PAYMENT_STATUS_MAP, alias="status"),
    parse_date("PMT_RECV_DT").alias("received_date"),
    parse_date("PMT_PROC_DT").alias("processed_date"),
    parse_timestamp("PMT_CRET_DT").alias("created_at"),
    parse_timestamp("PMT_UPDT_DT").alias("updated_at"),
)

# Resolve loan account FK
payments_df = payments_base.join(
    loan_lkp,
    payments_base["_acct_nbr"] == loan_lkp["account_number"],
    "left",
).drop("account_number", "_acct_nbr")

# Add partition column
payments_df = payments_df.withColumn("payment_year", F.year(F.col("payment_date")))

unresolved_loans = payments_df.filter(F.col("loan_account_id").isNull()).count()
print(f"Unresolved loan account FKs: {unresolved_loans}")
payments_df.show(5, truncate=False)

# COMMAND ----------

(
    payments_df
    .write.format("delta")
    .mode("overwrite")
    .option("mergeSchema", "true")
    .saveAsTable(f"{SCHEMA}.payments")
)
pmt_count = spark.table(f"{SCHEMA}.payments").count()
print(f"Wrote {pmt_count} payments to {SCHEMA}.payments")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Step 7: Data Quality Checks
# MAGIC
# MAGIC Four categories of post-ingestion validation:
# MAGIC
# MAGIC 1. **Row count reconciliation** — source file count vs. Delta table count
# MAGIC 2. **Null checks** — required (NOT NULL) columns must have zero nulls
# MAGIC 3. **Referential integrity** — every FK must resolve to a parent row
# MAGIC 4. **Business rules** — domain-specific constraints on loan data
# MAGIC
# MAGIC Results are collected into a summary report at the end.

# COMMAND ----------

# MAGIC %md
# MAGIC ### 7a: Row Count Reconciliation
# MAGIC
# MAGIC Compare the number of rows read from each source file against the rows
# MAGIC written to the corresponding Delta table. Any mismatch indicates data loss.

# COMMAND ----------

from dataclasses import dataclass

@dataclass
class CheckResult:
    category: str
    name: str
    passed: bool
    detail: str = ""

results = []

# Row counts
source_counts = {
    "borrowers":    raw_borrowers.count(),
    "loan_products": raw_products.count(),
    "loan_accounts": raw_accounts.count(),
    "payments":     raw_payments.count(),
}

for table, src_count in source_counts.items():
    tgt_count = spark.table(f"{SCHEMA}.{table}").count()
    passed = src_count == tgt_count
    results.append(CheckResult(
        "1. Row Count Reconciliation",
        f"{table}: source vs target",
        passed,
        f"Source={src_count}, Target={tgt_count}",
    ))
    icon = "PASS" if passed else "FAIL"
    print(f"  [{icon}] {table}: Source={src_count}, Target={tgt_count}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 7b: Null Checks on Required Fields
# MAGIC
# MAGIC Verify that columns defined as NOT NULL in the DDL actually contain no nulls.
# MAGIC This catches parse failures (malformed dates/amounts that became NULL).

# COMMAND ----------

required_fields = {
    "borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_products": ["code", "name", "type", "term_months", "rate_type"],
    "loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "status",
    ],
    "payments": ["loan_account_id", "payment_date", "total_amount", "type", "status"],
}

for table, columns in required_fields.items():
    df = spark.table(f"{SCHEMA}.{table}")
    for col_name in columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        passed = null_count == 0
        results.append(CheckResult(
            "2. Null Checks", f"{table}.{col_name} NOT NULL", passed, f"Null count: {null_count}"
        ))
        if not passed:
            print(f"  [FAIL] {table}.{col_name}: {null_count} nulls")
        else:
            print(f"  [PASS] {table}.{col_name}: no nulls")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 7c: Referential Integrity
# MAGIC
# MAGIC Use `LEFT ANTI JOIN` to detect orphaned foreign keys — child rows whose FK
# MAGIC value does not exist in the parent table.

# COMMAND ----------

loans = spark.table(f"{SCHEMA}.loan_accounts")
borrowers_tbl = spark.table(f"{SCHEMA}.borrowers")
products_tbl = spark.table(f"{SCHEMA}.loan_products")
payments_tbl = spark.table(f"{SCHEMA}.payments")

# loan_accounts.borrower_id → borrowers
orphan_borr = loans.join(borrowers_tbl, loans["borrower_id"] == borrowers_tbl["borrower_id"], "left_anti").count()
results.append(CheckResult("3. Referential Integrity", "loan_accounts.borrower_id → borrowers", orphan_borr == 0, f"Orphaned: {orphan_borr}"))
print(f"  [{'PASS' if orphan_borr == 0 else 'FAIL'}] borrower FK: {orphan_borr} orphans")

# loan_accounts.product_id → loan_products
orphan_prod = loans.join(products_tbl, loans["product_id"] == products_tbl["product_id"], "left_anti").count()
results.append(CheckResult("3. Referential Integrity", "loan_accounts.product_id → loan_products", orphan_prod == 0, f"Orphaned: {orphan_prod}"))
print(f"  [{'PASS' if orphan_prod == 0 else 'FAIL'}] product FK: {orphan_prod} orphans")

# payments.loan_account_id → loan_accounts
orphan_loan = payments_tbl.join(loans, payments_tbl["loan_account_id"] == loans["loan_account_id"], "left_anti").count()
results.append(CheckResult("3. Referential Integrity", "payments.loan_account_id → loan_accounts", orphan_loan == 0, f"Orphaned: {orphan_loan}"))
print(f"  [{'PASS' if orphan_loan == 0 else 'FAIL'}] payment→loan FK: {orphan_loan} orphans")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 7d: Business Rule Validation
# MAGIC
# MAGIC Domain-specific checks that go beyond schema constraints:
# MAGIC - Active loans must have `current_balance > 0`
# MAGIC - All loans must have positive `original_amount`
# MAGIC - Interest rates must be in `[0, 100]`
# MAGIC - `maturity_date` must be after `origination_date`
# MAGIC - LTV percent must be in `[0, 200]`
# MAGIC - Delinquency days must be `>= 0`
# MAGIC - Loan statuses must be in the expected set
# MAGIC - Payment amounts must be `>= 0`
# MAGIC - Credit scores must be in `[300, 850]`
# MAGIC - Annual income must be `>= 0`

# COMMAND ----------

# Active loans: balance > 0
v = loans.filter((F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)).count()
results.append(CheckResult("4. Business Rules", "Active loans have balance > 0", v == 0, f"Violations: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] Active loan balance > 0: {v} violations")

# Positive original amount
v = loans.filter(F.col("original_amount") <= 0).count()
results.append(CheckResult("4. Business Rules", "Positive original_amount", v == 0, f"Violations: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] Positive original_amount: {v} violations")

# Interest rate range
v = loans.filter((F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)).count()
results.append(CheckResult("4. Business Rules", "Interest rate in [0, 100]", v == 0, f"Violations: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] Interest rate range: {v} violations")

# Maturity > origination
v = loans.filter(F.col("maturity_date") <= F.col("origination_date")).count()
results.append(CheckResult("4. Business Rules", "Maturity > origination date", v == 0, f"Violations: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] Maturity > origination: {v} violations")

# LTV range
v = loans.filter(F.col("ltv_percent").isNotNull() & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))).count()
results.append(CheckResult("4. Business Rules", "LTV percent in [0, 200]", v == 0, f"Violations: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] LTV range: {v} violations")

# Delinquency days >= 0
v = loans.filter(F.col("delinquency_days") < 0).count()
results.append(CheckResult("4. Business Rules", "Delinquency days >= 0", v == 0, f"Violations: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] Delinquency >= 0: {v} violations")

# Valid statuses
valid_statuses = {"ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE"}
v = loans.filter(~F.col("status").isin(valid_statuses)).count()
results.append(CheckResult("4. Business Rules", "Valid loan statuses", v == 0, f"Unknown: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] Valid statuses: {v} unknown")

# Payment amounts >= 0
v = payments_tbl.filter(F.col("total_amount") < 0).count()
results.append(CheckResult("4. Business Rules", "Payment amounts >= 0", v == 0, f"Violations: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] Payment amounts >= 0: {v} violations")

# Credit score range
v = borrowers_tbl.filter(F.col("credit_score").isNotNull() & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))).count()
results.append(CheckResult("4. Business Rules", "Credit score in [300, 850]", v == 0, f"Violations: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] Credit score range: {v} violations")

# Annual income >= 0
v = borrowers_tbl.filter(F.col("annual_income").isNotNull() & (F.col("annual_income") < 0)).count()
results.append(CheckResult("4. Business Rules", "Annual income >= 0", v == 0, f"Violations: {v}"))
print(f"  [{'PASS' if v == 0 else 'FAIL'}] Annual income >= 0: {v} violations")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Quality Report Summary
# MAGIC
# MAGIC Aggregated results across all four categories.

# COMMAND ----------

pass_count = sum(1 for r in results if r.passed)
fail_count = sum(1 for r in results if not r.passed)
total = len(results)

print("=" * 70)
print("DATA QUALITY REPORT SUMMARY")
print("=" * 70)
print(f"  Total checks: {total}")
print(f"  Passed:       {pass_count}")
print(f"  Failed:       {fail_count}")
print(f"  Status:       {'ALL CHECKS PASSED' if fail_count == 0 else 'FAILURES DETECTED'}")
print("=" * 70)
print()

for cat in sorted(set(r.category for r in results)):
    print(f"\n{cat}")
    print("-" * 60)
    for r in [x for x in results if x.category == cat]:
        icon = "PASS" if r.passed else "FAIL"
        print(f"  [{icon}] {r.name} — {r.detail}")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Migration Complete
# MAGIC
# MAGIC ### Summary of what was migrated:
# MAGIC | Table | Source | Rows | Key Transforms |
# MAGIC |---|---|---|---|
# MAGIC | `borrowers` | `CDW_BORR_MSTR` | 5 | Date/amount parsing, status expansion |
# MAGIC | `loan_products` | `CDW_LN_PROD` | 5 | Term/amount parsing, status→boolean |
# MAGIC | `loan_accounts` | `CDW_LN_ACCT` | 5 | Denorm removal, FK resolution, 8 amount fields |
# MAGIC | `payments` | `CDW_PMT_HIST` | 10 | FK resolution, type/status expansion |
# MAGIC
# MAGIC ### Next steps:
# MAGIC - Review the quality report above for any failures
# MAGIC - Update the Spring Boot application to read from the modern Delta tables
# MAGIC - Set up incremental ingestion using Delta Lake MERGE for ongoing sync
# MAGIC - Schedule this notebook as a Databricks Workflow for automated runs
