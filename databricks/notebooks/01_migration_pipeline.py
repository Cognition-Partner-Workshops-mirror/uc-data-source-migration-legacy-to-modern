# Databricks notebook source
# MAGIC %md
# MAGIC # CDW Legacy to Delta Lake Migration Pipeline
# MAGIC
# MAGIC This notebook migrates data from the legacy CDW (Corporate Data Warehouse) loan management system
# MAGIC to a modern Delta Lake schema on Databricks.
# MAGIC
# MAGIC **Source System:** Legacy CDW with all-VARCHAR columns, cryptic names, no FKs, status abbreviations
# MAGIC
# MAGIC **Target System:** Delta Lake with proper types, meaningful names, FK constraints, partitioning
# MAGIC
# MAGIC ## Execution Order
# MAGIC 1. Setup & Configuration
# MAGIC 2. Create Target Schema & Tables
# MAGIC 3. Ingest Borrowers (dimension, no dependencies)
# MAGIC 4. Ingest Loan Products (dimension, no dependencies)
# MAGIC 5. Ingest Loan Accounts (depends on borrowers + products)
# MAGIC 6. Ingest Payments (depends on loan accounts)
# MAGIC 7. Data Quality Validation

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Setup & Configuration
# MAGIC
# MAGIC Define the source file paths, target catalog/schema, and all transformation mappings.
# MAGIC The legacy system stores dates as `MM/DD/YYYY` strings and amounts with commas (e.g., "285,000").

# COMMAND ----------

# Configuration
CATALOG = "lending_warehouse"
SCHEMA = "loan_management"
LEGACY_DATE_FORMAT = "MM/dd/yyyy"

# Source file path — update this to your actual source location
# Supports: DBFS, ADLS, S3, or local (for testing)
SOURCE_BASE_PATH = "/mnt/legacy_extracts/"  # Update per environment

# Status code expansion mappings
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
}

PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

print(f"Target: {CATALOG}.{SCHEMA}")
print(f"Source: {SOURCE_BASE_PATH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Transformation Helper Functions
# MAGIC
# MAGIC These reusable functions handle the core conversion patterns:
# MAGIC - **Date parsing:** `MM/DD/YYYY` string → Spark `DateType` using `to_date()` with format string
# MAGIC - **Amount parsing:** Remove commas via regex, then cast to `DecimalType`
# MAGIC - **Status expansion:** Map abbreviated codes to human-readable values using `coalesce(when(...))`
# MAGIC - **Integer parsing:** Direct cast from trimmed string to `IntegerType`
# MAGIC
# MAGIC All functions return NULL on parse failure (Spark's default behavior) — records are never dropped.

# COMMAND ----------

from pyspark.sql.functions import (
    col, to_date, regexp_replace, trim, when, lit, coalesce,
    monotonically_increasing_id, current_timestamp
)
from pyspark.sql.types import DecimalType, IntegerType, TimestampType


def parse_date(df, source_col, target_col):
    """Parse MM/DD/YYYY string → DateType. Returns NULL if unparseable."""
    return df.withColumn(
        target_col,
        to_date(trim(col(source_col)), LEGACY_DATE_FORMAT)
    )


def parse_timestamp(df, source_col, target_col):
    """Parse MM/DD/YYYY string → TimestampType (midnight). Returns NULL if unparseable."""
    return df.withColumn(
        target_col,
        to_date(trim(col(source_col)), LEGACY_DATE_FORMAT).cast(TimestampType())
    )


def parse_amount(df, source_col, target_col, precision=12, scale=2):
    """
    Remove commas from amount string, cast to DecimalType.
    Examples: "285,000" → 285000.00, "271,432.56" → 271432.56
    Returns NULL if the string cannot be parsed.
    """
    return df.withColumn(
        target_col,
        regexp_replace(trim(col(source_col)), ",", "").cast(DecimalType(precision, scale))
    )


def parse_int(df, source_col, target_col):
    """Parse string → IntegerType. Returns NULL if non-numeric."""
    return df.withColumn(
        target_col,
        trim(col(source_col)).cast(IntegerType())
    )


def expand_codes(df, source_col, target_col, mapping):
    """
    Expand abbreviated status codes using a lookup mapping.
    Unmapped values are preserved as-is (safe fallback).
    """
    expr = coalesce(
        *[when(trim(col(source_col)) == k, lit(v)) for k, v in mapping.items()],
        trim(col(source_col))
    )
    return df.withColumn(target_col, expr)


def expand_to_boolean(df, source_col, target_col, mapping):
    """Expand status codes to boolean (e.g., ACT→true, INA→false)."""
    expr = coalesce(
        *[when(trim(col(source_col)) == k, lit(v)) for k, v in mapping.items()],
        lit(None)
    )
    return df.withColumn(target_col, expr)


print("Transformation helpers loaded.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Create Target Schema
# MAGIC
# MAGIC Create the Unity Catalog schema and Delta Lake tables with proper types,
# MAGIC constraints, and partitioning.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE CATALOG IF NOT EXISTS lending_warehouse;
# MAGIC USE CATALOG lending_warehouse;
# MAGIC CREATE SCHEMA IF NOT EXISTS loan_management
# MAGIC COMMENT 'Modern loan management schema migrated from legacy CDW data warehouse';
# MAGIC USE SCHEMA loan_management;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Borrower dimension table
# MAGIC CREATE TABLE IF NOT EXISTS loan_management.borrowers (
# MAGIC     id                  BIGINT GENERATED ALWAYS AS IDENTITY,
# MAGIC     external_id         STRING NOT NULL,
# MAGIC     first_name          STRING NOT NULL,
# MAGIC     last_name           STRING NOT NULL,
# MAGIC     middle_initial      STRING,
# MAGIC     ssn_hash            STRING,
# MAGIC     date_of_birth       DATE,
# MAGIC     address_line1       STRING,
# MAGIC     address_line2       STRING,
# MAGIC     city                STRING,
# MAGIC     state               STRING,
# MAGIC     zip_code            STRING,
# MAGIC     phone               STRING,
# MAGIC     email               STRING,
# MAGIC     credit_score        INT,
# MAGIC     employment_status   STRING,
# MAGIC     annual_income       DECIMAL(12, 2),
# MAGIC     status              STRING NOT NULL,
# MAGIC     created_at          TIMESTAMP,
# MAGIC     updated_at          TIMESTAMP
# MAGIC )
# MAGIC USING DELTA
# MAGIC COMMENT 'Borrower dimension table migrated from CDW_BORR_MSTR'
# MAGIC PARTITIONED BY (state);

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Loan products reference table
# MAGIC CREATE TABLE IF NOT EXISTS loan_management.loan_products (
# MAGIC     id                  BIGINT GENERATED ALWAYS AS IDENTITY,
# MAGIC     code                STRING NOT NULL,
# MAGIC     name                STRING NOT NULL,
# MAGIC     type                STRING NOT NULL,
# MAGIC     term_months         INT,
# MAGIC     rate_type           STRING,
# MAGIC     min_amount          DECIMAL(12, 2),
# MAGIC     max_amount          DECIMAL(12, 2),
# MAGIC     is_active           BOOLEAN NOT NULL DEFAULT true,
# MAGIC     effective_date      DATE,
# MAGIC     expiration_date     DATE
# MAGIC )
# MAGIC USING DELTA
# MAGIC COMMENT 'Loan product reference table migrated from CDW_LN_PROD';

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Loan accounts fact table
# MAGIC CREATE TABLE IF NOT EXISTS loan_management.loan_accounts (
# MAGIC     id                  BIGINT GENERATED ALWAYS AS IDENTITY,
# MAGIC     account_number      STRING NOT NULL,
# MAGIC     borrower_id         BIGINT NOT NULL,
# MAGIC     product_id          BIGINT NOT NULL,
# MAGIC     original_amount     DECIMAL(12, 2) NOT NULL,
# MAGIC     current_balance     DECIMAL(12, 2) NOT NULL,
# MAGIC     interest_rate       DECIMAL(5, 3) NOT NULL,
# MAGIC     term_months         INT NOT NULL,
# MAGIC     monthly_payment     DECIMAL(10, 2) NOT NULL,
# MAGIC     origination_date    DATE NOT NULL,
# MAGIC     maturity_date       DATE NOT NULL,
# MAGIC     first_payment_date  DATE,
# MAGIC     next_payment_date   DATE,
# MAGIC     status              STRING NOT NULL,
# MAGIC     delinquency_days    INT DEFAULT 0,
# MAGIC     escrow_balance      DECIMAL(10, 2),
# MAGIC     ltv_percent         DECIMAL(5, 2),
# MAGIC     property_address    STRING,
# MAGIC     property_city       STRING,
# MAGIC     property_state      STRING,
# MAGIC     property_zip        STRING,
# MAGIC     property_type       STRING,
# MAGIC     appraised_value     DECIMAL(12, 2),
# MAGIC     created_at          TIMESTAMP,
# MAGIC     updated_at          TIMESTAMP,
# MAGIC     CONSTRAINT fk_loan_borrower FOREIGN KEY (borrower_id) REFERENCES loan_management.borrowers(id),
# MAGIC     CONSTRAINT fk_loan_product FOREIGN KEY (product_id) REFERENCES loan_management.loan_products(id)
# MAGIC )
# MAGIC USING DELTA
# MAGIC COMMENT 'Loan accounts fact table migrated from CDW_LN_ACCT'
# MAGIC PARTITIONED BY (status);

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Payment history table
# MAGIC CREATE TABLE IF NOT EXISTS loan_management.payments (
# MAGIC     id                  BIGINT GENERATED ALWAYS AS IDENTITY,
# MAGIC     legacy_sequence_id  STRING,
# MAGIC     loan_account_id     BIGINT NOT NULL,
# MAGIC     payment_date        DATE NOT NULL,
# MAGIC     total_amount        DECIMAL(10, 2) NOT NULL,
# MAGIC     principal_amount    DECIMAL(10, 2),
# MAGIC     interest_amount     DECIMAL(10, 2),
# MAGIC     escrow_amount       DECIMAL(10, 2),
# MAGIC     late_fee            DECIMAL(10, 2) DEFAULT 0.00,
# MAGIC     type                STRING NOT NULL,
# MAGIC     status              STRING NOT NULL,
# MAGIC     received_date       DATE,
# MAGIC     processed_date      DATE,
# MAGIC     created_at          TIMESTAMP,
# MAGIC     updated_at          TIMESTAMP,
# MAGIC     CONSTRAINT fk_payment_loan FOREIGN KEY (loan_account_id) REFERENCES loan_management.loan_accounts(id)
# MAGIC )
# MAGIC USING DELTA
# MAGIC COMMENT 'Payment history table migrated from CDW_PMT_HIST'
# MAGIC PARTITIONED BY (status);

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Ingest Borrowers
# MAGIC
# MAGIC **Source:** `CDW_BORR_MSTR` — Legacy borrower master table
# MAGIC
# MAGIC **Transformations applied:**
# MAGIC - `BORR_DOB_DT` (VARCHAR "03/15/1978") → `date_of_birth` (DATE)
# MAGIC - `BORR_CRDT_SCR` (VARCHAR "745") → `credit_score` (INT)
# MAGIC - `BORR_ANN_INCM` (VARCHAR "92,500") → `annual_income` (DECIMAL removing commas)
# MAGIC - `BORR_STAT_CD` (VARCHAR "ACT") → `status` (STRING "ACTIVE")
# MAGIC - `BORR_CRET_DT` / `BORR_UPDT_DT` → `created_at` / `updated_at` (TIMESTAMP)
# MAGIC - `BORR_REC_TYP` is dropped (not needed in modern schema)

# COMMAND ----------

# Read legacy borrower data
borrowers_raw = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "false")
    .csv(f"{SOURCE_BASE_PATH}/CDW_BORR_MSTR.csv")
)

print(f"Source records: {borrowers_raw.count()}")
borrowers_raw.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Borrower Transformations
# MAGIC
# MAGIC 1. Select and rename columns from cryptic → meaningful names
# MAGIC 2. Parse date of birth from string to DATE
# MAGIC 3. Parse credit score from string to INT
# MAGIC 4. Parse annual income (remove commas, cast to DECIMAL)
# MAGIC 5. Parse audit timestamps to TIMESTAMP type
# MAGIC 6. Expand status code abbreviations (ACT → ACTIVE)

# COMMAND ----------

# Step 4a: Select and rename direct-copy columns
borrowers_renamed = borrowers_raw.select(
    col("BORR_ID").alias("external_id"),
    col("BORR_FST_NM").alias("first_name"),
    col("BORR_LST_NM").alias("last_name"),
    col("BORR_MID_INIT").alias("middle_initial"),
    col("BORR_SSN_ENCR").alias("ssn_hash"),
    col("BORR_DOB_DT"),
    col("BORR_ADDR_LN1").alias("address_line1"),
    col("BORR_ADDR_LN2").alias("address_line2"),
    col("BORR_CTY_NM").alias("city"),
    col("BORR_ST_CD").alias("state"),
    col("BORR_ZIP_CD").alias("zip_code"),
    col("BORR_PH_NBR").alias("phone"),
    col("BORR_EMAIL_ADDR").alias("email"),
    col("BORR_CRDT_SCR"),
    col("BORR_EMP_STAT").alias("employment_status"),
    col("BORR_ANN_INCM"),
    col("BORR_CRET_DT"),
    col("BORR_UPDT_DT"),
    col("BORR_STAT_CD"),
    # BORR_REC_TYP intentionally dropped — not needed in modern schema
)

# Step 4b: Parse date of birth (MM/DD/YYYY string → DATE)
borrowers_df = parse_date(borrowers_renamed, "BORR_DOB_DT", "date_of_birth")
borrowers_df = borrowers_df.drop("BORR_DOB_DT")

# Step 4c: Parse credit score (string → INT)
borrowers_df = parse_int(borrowers_df, "BORR_CRDT_SCR", "credit_score")
borrowers_df = borrowers_df.drop("BORR_CRDT_SCR")

# Step 4d: Parse annual income (remove commas, cast to DECIMAL)
# "92,500" → 92500.00
borrowers_df = parse_amount(borrowers_df, "BORR_ANN_INCM", "annual_income")
borrowers_df = borrowers_df.drop("BORR_ANN_INCM")

# Step 4e: Parse audit timestamps (MM/DD/YYYY → TIMESTAMP at midnight)
borrowers_df = parse_timestamp(borrowers_df, "BORR_CRET_DT", "created_at")
borrowers_df = borrowers_df.drop("BORR_CRET_DT")
borrowers_df = parse_timestamp(borrowers_df, "BORR_UPDT_DT", "updated_at")
borrowers_df = borrowers_df.drop("BORR_UPDT_DT")

# Step 4f: Expand status codes (ACT → ACTIVE, INA → INACTIVE)
borrowers_df = expand_codes(borrowers_df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)
borrowers_df = borrowers_df.drop("BORR_STAT_CD")

print(f"Transformed records: {borrowers_df.count()}")
borrowers_df.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Write Borrowers to Delta Lake
# MAGIC
# MAGIC Write the transformed borrower data partitioned by `state` (geographic queries are common in loan servicing).

# COMMAND ----------

# Write to Delta Lake
(
    borrowers_df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .partitionBy("state")
    .saveAsTable(f"{CATALOG}.{SCHEMA}.borrowers")
)

print(f"Borrowers written: {spark.table(f'{CATALOG}.{SCHEMA}.borrowers').count()} records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Ingest Loan Products
# MAGIC
# MAGIC **Source:** `CDW_LN_PROD` — Legacy loan product reference table
# MAGIC
# MAGIC **Transformations applied:**
# MAGIC - `PROD_TERM_MOS` (VARCHAR "360") → `term_months` (INT)
# MAGIC - `PROD_MIN_AMT` / `PROD_MAX_AMT` (VARCHAR "50,000") → DECIMAL (remove commas)
# MAGIC - `PROD_STAT_CD` (VARCHAR "ACT") → `is_active` (BOOLEAN: ACT→true, INA→false)
# MAGIC - `PROD_EFF_DT` / `PROD_EXP_DT` (VARCHAR dates) → DATE type

# COMMAND ----------

# Read legacy loan product data
products_raw = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "false")
    .csv(f"{SOURCE_BASE_PATH}/CDW_LN_PROD.csv")
)

print(f"Source records: {products_raw.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Loan Product Transformations
# MAGIC
# MAGIC Key decision: `PROD_STAT_CD` is converted to a boolean `is_active` field
# MAGIC rather than keeping it as a string. This gives semantic clarity — a product
# MAGIC is either active or inactive, there's no third state.

# COMMAND ----------

# Rename and select columns
products_df = products_raw.select(
    col("PROD_CD").alias("code"),
    col("PROD_DESC_TXT").alias("name"),
    col("PROD_TYP_CD").alias("type"),
    col("PROD_TERM_MOS"),
    col("PROD_RT_TYP").alias("rate_type"),
    col("PROD_MIN_AMT"),
    col("PROD_MAX_AMT"),
    col("PROD_STAT_CD"),
    col("PROD_EFF_DT"),
    col("PROD_EXP_DT"),
)

# Parse term months (string → INT)
products_df = parse_int(products_df, "PROD_TERM_MOS", "term_months")
products_df = products_df.drop("PROD_TERM_MOS")

# Parse amount fields (remove commas → DECIMAL)
products_df = parse_amount(products_df, "PROD_MIN_AMT", "min_amount")
products_df = products_df.drop("PROD_MIN_AMT")
products_df = parse_amount(products_df, "PROD_MAX_AMT", "max_amount")
products_df = products_df.drop("PROD_MAX_AMT")

# Convert status to boolean (ACT → true, INA → false)
products_df = expand_to_boolean(products_df, "PROD_STAT_CD", "is_active", {"ACT": True, "INA": False})
products_df = products_df.drop("PROD_STAT_CD")

# Parse date fields
products_df = parse_date(products_df, "PROD_EFF_DT", "effective_date")
products_df = products_df.drop("PROD_EFF_DT")
products_df = parse_date(products_df, "PROD_EXP_DT", "expiration_date")
products_df = products_df.drop("PROD_EXP_DT")

print(f"Transformed records: {products_df.count()}")
products_df.display()

# COMMAND ----------

# Write to Delta Lake (no partitioning — small reference table)
(
    products_df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{CATALOG}.{SCHEMA}.loan_products")
)

print(f"Loan products written: {spark.table(f'{CATALOG}.{SCHEMA}.loan_products').count()} records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Ingest Loan Accounts
# MAGIC
# MAGIC **Source:** `CDW_LN_ACCT` — Legacy loan accounts (denormalized)
# MAGIC
# MAGIC **Key transformations:**
# MAGIC - **Denormalization removal:** Drop `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` (redundant with borrower FK)
# MAGIC - **FK resolution:** `BORR_ID` → lookup `borrowers.id`, `PROD_CD` → lookup `loan_products.id`
# MAGIC - **Amount parsing:** 7 amount fields converted from comma-strings to DECIMAL
# MAGIC - **Date parsing:** 6 date fields from MM/DD/YYYY strings to DATE/TIMESTAMP
# MAGIC - **Status expansion:** `LN_STAT_CD` (ACT/CLO/DFT/FRB) → full names
# MAGIC - **Property type expansion:** `PROP_TYP_CD` (SFR/CND/MFR/TWN) → full names

# COMMAND ----------

# Read legacy loan account data
loans_raw = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "false")
    .csv(f"{SOURCE_BASE_PATH}/CDW_LN_ACCT.csv")
)

print(f"Source records: {loans_raw.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Loan Account Transformations
# MAGIC
# MAGIC The legacy table `CDW_LN_ACCT` is heavily denormalized — it contains borrower
# MAGIC name and SSN fields that duplicate `CDW_BORR_MSTR`. In the modern schema, we
# MAGIC normalize this by keeping only a `borrower_id` foreign key.
# MAGIC
# MAGIC We resolve the FK by joining on `external_id` in the already-ingested borrowers table.
# MAGIC Records with unresolvable borrower IDs are retained (not dropped) with NULL `borrower_id`
# MAGIC — the data quality framework will flag these.

# COMMAND ----------

# Step 6a: Select columns, dropping denormalized borrower fields
loans_df = loans_raw.select(
    col("LN_ACCT_NBR").alias("account_number"),
    col("BORR_ID"),          # Will be resolved to borrower_id FK
    col("PROD_CD"),          # Will be resolved to product_id FK
    col("LN_ORIG_AMT"),
    col("LN_CURR_BAL"),
    col("LN_INT_RT"),
    col("LN_TERM_MOS"),
    col("LN_PMT_AMT"),
    col("LN_ORIG_DT"),
    col("LN_MAT_DT"),
    col("LN_1ST_PMT_DT"),
    col("LN_NXT_PMT_DT"),
    col("LN_STAT_CD"),
    col("LN_DLQ_DAYS"),
    col("LN_ESCROW_BAL"),
    col("LN_LTV_PCT"),
    col("PROP_ADDR_LN1").alias("property_address"),
    col("PROP_CTY_NM").alias("property_city"),
    col("PROP_ST_CD").alias("property_state"),
    col("PROP_ZIP_CD").alias("property_zip"),
    col("PROP_TYP_CD"),
    col("PROP_APRS_VAL"),
    col("LN_CRET_DT"),
    col("LN_UPDT_DT"),
    # BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 intentionally dropped (denormalized)
)

print("Denormalized borrower columns dropped.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### FK Resolution: Borrower ID
# MAGIC
# MAGIC Look up `borrowers.id` by matching `CDW_LN_ACCT.BORR_ID` to `borrowers.external_id`.
# MAGIC Uses a LEFT JOIN so records with no match are preserved (logged as warnings).

# COMMAND ----------

# Step 6b: Resolve borrower FK
borrowers_lookup = spark.table(f"{CATALOG}.{SCHEMA}.borrowers").select(
    col("id").alias("borrower_id"),
    col("external_id"),
)

loans_df = loans_df.join(
    borrowers_lookup,
    loans_df["BORR_ID"] == borrowers_lookup["external_id"],
    "left"
).drop("external_id", "BORR_ID")

unresolved_borrowers = loans_df.filter(col("borrower_id").isNull()).count()
print(f"Unresolved borrower IDs: {unresolved_borrowers}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### FK Resolution: Product ID
# MAGIC
# MAGIC Look up `loan_products.id` by matching `CDW_LN_ACCT.PROD_CD` to `loan_products.code`.

# COMMAND ----------

# Step 6c: Resolve product FK
products_lookup = spark.table(f"{CATALOG}.{SCHEMA}.loan_products").select(
    col("id").alias("product_id"),
    col("code").alias("product_code"),
)

loans_df = loans_df.join(
    products_lookup,
    loans_df["PROD_CD"] == products_lookup["product_code"],
    "left"
).drop("product_code", "PROD_CD")

unresolved_products = loans_df.filter(col("product_id").isNull()).count()
print(f"Unresolved product codes: {unresolved_products}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Amount & Rate Parsing
# MAGIC
# MAGIC Seven financial fields are converted from comma-separated strings to proper DECIMAL types:
# MAGIC - `"285,000"` → `285000.00` (DECIMAL(12,2) for amounts)
# MAGIC - `"5.250"` → `5.250` (DECIMAL(5,3) for interest rate)
# MAGIC - `"82.5"` → `82.50` (DECIMAL(5,2) for LTV percentage)

# COMMAND ----------

# Step 6d: Parse amount columns
loans_df = parse_amount(loans_df, "LN_ORIG_AMT", "original_amount")
loans_df = loans_df.drop("LN_ORIG_AMT")

loans_df = parse_amount(loans_df, "LN_CURR_BAL", "current_balance")
loans_df = loans_df.drop("LN_CURR_BAL")

loans_df = parse_amount(loans_df, "LN_INT_RT", "interest_rate", precision=5, scale=3)
loans_df = loans_df.drop("LN_INT_RT")

loans_df = parse_amount(loans_df, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
loans_df = loans_df.drop("LN_PMT_AMT")

loans_df = parse_amount(loans_df, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
loans_df = loans_df.drop("LN_ESCROW_BAL")

loans_df = parse_amount(loans_df, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)
loans_df = loans_df.drop("LN_LTV_PCT")

loans_df = parse_amount(loans_df, "PROP_APRS_VAL", "appraised_value")
loans_df = loans_df.drop("PROP_APRS_VAL")

print("Amount fields parsed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Integer, Date, and Status Parsing

# COMMAND ----------

# Step 6e: Parse integer columns
loans_df = parse_int(loans_df, "LN_TERM_MOS", "term_months")
loans_df = loans_df.drop("LN_TERM_MOS")

loans_df = parse_int(loans_df, "LN_DLQ_DAYS", "delinquency_days")
loans_df = loans_df.drop("LN_DLQ_DAYS")

# Step 6f: Parse date columns (MM/DD/YYYY → DATE)
for src, tgt in [
    ("LN_ORIG_DT", "origination_date"),
    ("LN_MAT_DT", "maturity_date"),
    ("LN_1ST_PMT_DT", "first_payment_date"),
    ("LN_NXT_PMT_DT", "next_payment_date"),
]:
    loans_df = parse_date(loans_df, src, tgt)
    loans_df = loans_df.drop(src)

# Step 6g: Parse audit timestamps
loans_df = parse_timestamp(loans_df, "LN_CRET_DT", "created_at")
loans_df = loans_df.drop("LN_CRET_DT")
loans_df = parse_timestamp(loans_df, "LN_UPDT_DT", "updated_at")
loans_df = loans_df.drop("LN_UPDT_DT")

# Step 6h: Expand status codes
# LN_STAT_CD: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
loans_df = expand_codes(loans_df, "LN_STAT_CD", "status", LOAN_STATUS_MAP)
loans_df = loans_df.drop("LN_STAT_CD")

# PROP_TYP_CD: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse
loans_df = expand_codes(loans_df, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)
loans_df = loans_df.drop("PROP_TYP_CD")

print(f"Transformed records: {loans_df.count()}")

# COMMAND ----------

# Write to Delta Lake, partitioned by loan status
(
    loans_df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .partitionBy("status")
    .saveAsTable(f"{CATALOG}.{SCHEMA}.loan_accounts")
)

print(f"Loan accounts written: {spark.table(f'{CATALOG}.{SCHEMA}.loan_accounts').count()} records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Ingest Payments
# MAGIC
# MAGIC **Source:** `CDW_PMT_HIST` — Legacy payment history
# MAGIC
# MAGIC **Transformations applied:**
# MAGIC - FK resolution: `LN_ACCT_NBR` → lookup `loan_accounts.id`
# MAGIC - 5 amount fields parsed from comma-strings to DECIMAL
# MAGIC - 4 date fields parsed from MM/DD/YYYY to DATE/TIMESTAMP
# MAGIC - Payment type expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
# MAGIC - Payment status expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
# MAGIC - Legacy `PMT_SEQ_NBR` preserved as `legacy_sequence_id` for audit trail

# COMMAND ----------

# Read legacy payment data
payments_raw = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "false")
    .csv(f"{SOURCE_BASE_PATH}/CDW_PMT_HIST.csv")
)

print(f"Source records: {payments_raw.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Payment Transformations
# MAGIC
# MAGIC The `PMT_SEQ_NBR` is kept as `legacy_sequence_id` (not used as PK) so the original
# MAGIC payment identifiers remain traceable for audit purposes.

# COMMAND ----------

# Select and rename
payments_df = payments_raw.select(
    col("PMT_SEQ_NBR").alias("legacy_sequence_id"),
    col("LN_ACCT_NBR"),
    col("PMT_DT"),
    col("PMT_AMT"),
    col("PMT_PRIN_AMT"),
    col("PMT_INT_AMT"),
    col("PMT_ESCROW_AMT"),
    col("PMT_LATE_FEE"),
    col("PMT_TYP_CD"),
    col("PMT_STAT_CD"),
    col("PMT_RECV_DT"),
    col("PMT_PROC_DT"),
    col("PMT_CRET_DT"),
    col("PMT_UPDT_DT"),
)

# Resolve loan account FK
accounts_lookup = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts").select(
    col("id").alias("loan_account_id"),
    col("account_number"),
)

payments_df = payments_df.join(
    accounts_lookup,
    payments_df["LN_ACCT_NBR"] == accounts_lookup["account_number"],
    "left"
).drop("account_number", "LN_ACCT_NBR")

unresolved_loans = payments_df.filter(col("loan_account_id").isNull()).count()
print(f"Unresolved loan account numbers: {unresolved_loans}")

# COMMAND ----------

# Parse amount fields
payments_df = parse_amount(payments_df, "PMT_AMT", "total_amount", precision=10, scale=2)
payments_df = payments_df.drop("PMT_AMT")

payments_df = parse_amount(payments_df, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
payments_df = payments_df.drop("PMT_PRIN_AMT")

payments_df = parse_amount(payments_df, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
payments_df = payments_df.drop("PMT_INT_AMT")

payments_df = parse_amount(payments_df, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
payments_df = payments_df.drop("PMT_ESCROW_AMT")

payments_df = parse_amount(payments_df, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)
payments_df = payments_df.drop("PMT_LATE_FEE")

# Parse date fields
payments_df = parse_date(payments_df, "PMT_DT", "payment_date")
payments_df = payments_df.drop("PMT_DT")

payments_df = parse_date(payments_df, "PMT_RECV_DT", "received_date")
payments_df = payments_df.drop("PMT_RECV_DT")

payments_df = parse_date(payments_df, "PMT_PROC_DT", "processed_date")
payments_df = payments_df.drop("PMT_PROC_DT")

# Parse audit timestamps
payments_df = parse_timestamp(payments_df, "PMT_CRET_DT", "created_at")
payments_df = payments_df.drop("PMT_CRET_DT")

payments_df = parse_timestamp(payments_df, "PMT_UPDT_DT", "updated_at")
payments_df = payments_df.drop("PMT_UPDT_DT")

# Expand type and status codes
payments_df = expand_codes(payments_df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)
payments_df = payments_df.drop("PMT_TYP_CD")

payments_df = expand_codes(payments_df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)
payments_df = payments_df.drop("PMT_STAT_CD")

print(f"Transformed records: {payments_df.count()}")

# COMMAND ----------

# Write to Delta Lake, partitioned by payment status
(
    payments_df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .partitionBy("status")
    .saveAsTable(f"{CATALOG}.{SCHEMA}.payments")
)

print(f"Payments written: {spark.table(f'{CATALOG}.{SCHEMA}.payments').count()} records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8: Data Quality Validation
# MAGIC
# MAGIC Run post-ingestion checks to verify the migration was successful:
# MAGIC 1. **Row count reconciliation** — source count matches target
# MAGIC 2. **Null checks** — required fields have no NULLs
# MAGIC 3. **Referential integrity** — all FKs resolve
# MAGIC 4. **Business rules** — domain-specific invariants hold

# COMMAND ----------

# MAGIC %md
# MAGIC ### Row Count Reconciliation

# COMMAND ----------

# Compare source vs target counts
expected_counts = {
    "borrowers": borrowers_raw.count(),
    "loan_products": products_raw.count(),
    "loan_accounts": loans_raw.count(),
    "payments": payments_raw.count(),
}

print("Row Count Reconciliation:")
print("-" * 50)
all_match = True
for table_name, expected in expected_counts.items():
    actual = spark.table(f"{CATALOG}.{SCHEMA}.{table_name}").count()
    status = "PASS" if actual == expected else "FAIL"
    if actual != expected:
        all_match = False
    print(f"  [{status}] {table_name}: expected={expected}, actual={actual}")

print(f"\nOverall: {'PASSED' if all_match else 'FAILED'}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Null Checks on Required Fields

# COMMAND ----------

required_fields = {
    "borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_products": ["code", "name", "type", "is_active"],
    "loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "status",
    ],
    "payments": ["loan_account_id", "payment_date", "total_amount", "type", "status"],
}

print("Null Checks on Required Fields:")
print("-" * 50)
null_issues = []
for table_name, fields in required_fields.items():
    df = spark.table(f"{CATALOG}.{SCHEMA}.{table_name}")
    total = df.count()
    for field_name in fields:
        null_count = df.filter(col(field_name).isNull()).count()
        status = "PASS" if null_count == 0 else "FAIL"
        if null_count > 0:
            null_issues.append(f"{table_name}.{field_name}: {null_count} nulls")
        print(f"  [{status}] {table_name}.{field_name}: {null_count}/{total} nulls")

if null_issues:
    print(f"\nFAILED — {len(null_issues)} field(s) with nulls")
else:
    print("\nPASSED — no null violations")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Referential Integrity

# COMMAND ----------

print("Referential Integrity Checks:")
print("-" * 50)

# loan_accounts.borrower_id → borrowers.id
loans = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")
borrowers = spark.table(f"{CATALOG}.{SCHEMA}.borrowers")

orphan_borrowers = loans.join(borrowers, loans["borrower_id"] == borrowers["id"], "left_anti").count()
print(f"  [{'PASS' if orphan_borrowers == 0 else 'FAIL'}] loan_accounts.borrower_id → borrowers.id: {orphan_borrowers} orphans")

# loan_accounts.product_id → loan_products.id
products = spark.table(f"{CATALOG}.{SCHEMA}.loan_products")
orphan_products = loans.join(products, loans["product_id"] == products["id"], "left_anti").count()
print(f"  [{'PASS' if orphan_products == 0 else 'FAIL'}] loan_accounts.product_id → loan_products.id: {orphan_products} orphans")

# payments.loan_account_id → loan_accounts.id
payments = spark.table(f"{CATALOG}.{SCHEMA}.payments")
orphan_payments = payments.join(loans, payments["loan_account_id"] == loans["id"], "left_anti").count()
print(f"  [{'PASS' if orphan_payments == 0 else 'FAIL'}] payments.loan_account_id → loan_accounts.id: {orphan_payments} orphans")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Business Rule Validation

# COMMAND ----------

from pyspark.sql.functions import current_date

print("Business Rule Validation:")
print("-" * 50)

loans = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")
payments = spark.table(f"{CATALOG}.{SCHEMA}.payments")
borrowers = spark.table(f"{CATALOG}.{SCHEMA}.borrowers")

# Rule 1: Active loans must have positive balance
active_zero = loans.filter((col("status") == "ACTIVE") & (col("current_balance") <= 0)).count()
print(f"  [{'PASS' if active_zero == 0 else 'FAIL'}] Active loans have positive balance: {active_zero} violations")

# Rule 2: Interest rate in valid range (0-25%)
bad_rate = loans.filter((col("interest_rate") < 0) | (col("interest_rate") > 25)).count()
print(f"  [{'PASS' if bad_rate == 0 else 'FAIL'}] Interest rates in range 0-25%: {bad_rate} violations")

# Rule 3: Origination date before maturity date
bad_dates = loans.filter(col("origination_date") >= col("maturity_date")).count()
print(f"  [{'PASS' if bad_dates == 0 else 'FAIL'}] Origination before maturity: {bad_dates} violations")

# Rule 4: Payment amounts must be positive
bad_payments = payments.filter(col("total_amount") <= 0).count()
print(f"  [{'PASS' if bad_payments == 0 else 'FAIL'}] Positive payment amounts: {bad_payments} violations")

# Rule 5: Credit scores in valid range (300-850)
bad_scores = borrowers.filter(
    col("credit_score").isNotNull() & ((col("credit_score") < 300) | (col("credit_score") > 850))
).count()
print(f"  [{'PASS' if bad_scores == 0 else 'FAIL'}] Credit scores 300-850: {bad_scores} violations")

# Rule 6: LTV in valid range (0-200%)
bad_ltv = loans.filter(
    col("ltv_percent").isNotNull() & ((col("ltv_percent") < 0) | (col("ltv_percent") > 200))
).count()
print(f"  [{'PASS' if bad_ltv == 0 else 'FAIL'}] LTV percent 0-200%: {bad_ltv} violations")

# Rule 7: Active loans with >90 days delinquent (warning)
severe_delinquent = loans.filter(
    (col("status") == "ACTIVE") & (col("delinquency_days") > 90)
).count()
print(f"  [{'PASS' if severe_delinquent == 0 else 'WARN'}] No active loans >90 days delinquent: {severe_delinquent}")

print("\nAll business rule checks complete.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Migration Complete
# MAGIC
# MAGIC The pipeline has successfully:
# MAGIC 1. Created the modern Delta Lake schema with proper types and constraints
# MAGIC 2. Ingested and transformed all 4 tables from the legacy CDW format
# MAGIC 3. Resolved foreign key relationships between tables
# MAGIC 4. Validated data quality across all dimensions
# MAGIC
# MAGIC ### Next Steps
# MAGIC - Review the quality check results above for any FAIL/WARN items
# MAGIC - Spot-check 5+ records manually to verify transformation accuracy
# MAGIC - Configure downstream consumers to point to the new schema
# MAGIC - Set up incremental ingestion for ongoing data changes
