# Databricks notebook source

# MAGIC %md
# MAGIC # Loan Accounts Ingestion: CDW_LN_ACCT → loan_accounts
# MAGIC
# MAGIC This notebook migrates the legacy **CDW_LN_ACCT** (Loan Accounts) table into
# MAGIC the modern **loan_warehouse.loan_accounts** Delta Lake table.
# MAGIC
# MAGIC ### Legacy Source Issues
# MAGIC - All 30 columns are VARCHAR
# MAGIC - **Denormalized**: borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`)
# MAGIC   are embedded directly in the loan table — redundant with CDW_BORR_MSTR
# MAGIC - Loan status codes are abbreviations (`ACT`, `CLO`, `DFT`, `FRB`)
# MAGIC - Property type codes are abbreviations (`SFR`, `CND`, `MFR`, `TWN`)
# MAGIC - Amounts, dates, and rates all stored as formatted strings
# MAGIC
# MAGIC ### What This Notebook Does
# MAGIC 1. Reads legacy loan account data
# MAGIC 2. **Drops denormalized borrower fields** (uses FK to borrowers table instead)
# MAGIC 3. Resolves `BORR_ID` → `borrower_id` (FK to borrowers)
# MAGIC 4. Resolves `PROD_CD` → `product_id` (FK to loan_products)
# MAGIC 5. Parses dates, amounts, rates to proper types
# MAGIC 6. Expands status and property type codes
# MAGIC 7. Derives `origination_year` partition column
# MAGIC 8. Validates required fields and FK resolution
# MAGIC
# MAGIC ### Dependencies
# MAGIC - **Must run after:** `01_ingest_borrowers` and `02_ingest_loan_products`
# MAGIC   (needed for FK resolution)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("source_path", "/mnt/legacy/cdw_ln_acct", "Source Path")
dbutils.widgets.dropdown("source_format", "csv", ["csv", "parquet"], "Source Format")
dbutils.widgets.text("target_table", "loan_warehouse.loan_accounts", "Target Table")
dbutils.widgets.text("borrower_table", "loan_warehouse.borrowers", "Borrower Lookup Table")
dbutils.widgets.text("product_table", "loan_warehouse.loan_products", "Product Lookup Table")
dbutils.widgets.text("error_path", "/mnt/migration/errors/loan_accounts", "Error Output Path")

source_path = dbutils.widgets.get("source_path")
source_format = dbutils.widgets.get("source_format")
target_table = dbutils.widgets.get("target_table")
borrower_table = dbutils.widgets.get("borrower_table")
product_table = dbutils.widgets.get("product_table")
error_path = dbutils.widgets.get("error_path")

print(f"Source:          {source_path} ({source_format})")
print(f"Target:          {target_table}")
print(f"Borrower lookup: {borrower_table}")
print(f"Product lookup:  {product_table}")
print(f"Errors:          {error_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Read Legacy Source Data

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType
from datetime import datetime

reader = spark.read.option("header", "true")
if source_format == "csv":
    reader = reader.option("inferSchema", "false")

source_df = reader.format(source_format).load(source_path)
source_count = source_df.count()
print(f"Source row count: {source_count}")
print(f"Source columns ({len(source_df.columns)}): {source_df.columns}")
display(source_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Load FK Lookup Tables
# MAGIC
# MAGIC We need to resolve two foreign keys:
# MAGIC - `BORR_ID` (string like `"B-10001"`) → `borrower_id` (BIGINT from borrowers table)
# MAGIC - `PROD_CD` (string like `"FXD30"`) → `product_id` (BIGINT from loan_products table)
# MAGIC
# MAGIC This is the **denormalization removal** step — instead of carrying borrower
# MAGIC name/SSN fields on every loan row, we just store a FK reference.

# COMMAND ----------

borrower_lookup = spark.table(borrower_table).select(
    F.col("borrower_id"),
    F.col("external_id").alias("_borr_external_id"),
)
print(f"Borrower lookup rows: {borrower_lookup.count()}")

product_lookup = spark.table(product_table).select(
    F.col("product_id"),
    F.col("code").alias("_prod_code"),
)
print(f"Product lookup rows: {product_lookup.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Apply Column Mappings & Transformations
# MAGIC
# MAGIC | Legacy Column | → Modern Column | Transformation |
# MAGIC |---------------|-----------------|----------------|
# MAGIC | `LN_ACCT_NBR` | `account_number` | Direct copy |
# MAGIC | `BORR_ID` | `borrower_id` | FK lookup via borrowers table |
# MAGIC | `BORR_FST_NM` | *(dropped)* | Denormalized — use borrower FK |
# MAGIC | `BORR_LST_NM` | *(dropped)* | Denormalized — use borrower FK |
# MAGIC | `BORR_SSN_LST4` | *(dropped)* | Denormalized — use borrower FK |
# MAGIC | `PROD_CD` | `product_id` | FK lookup via loan_products table |
# MAGIC | `LN_ORIG_AMT` | `original_amount` | Remove commas → DECIMAL(12,2) |
# MAGIC | `LN_CURR_BAL` | `current_balance` | Remove commas → DECIMAL(12,2) |
# MAGIC | `LN_INT_RT` | `interest_rate` | Parse → DECIMAL(5,3) |
# MAGIC | `LN_TERM_MOS` | `term_months` | Parse → INT |
# MAGIC | `LN_PMT_AMT` | `monthly_payment` | Remove commas → DECIMAL(10,2) |
# MAGIC | `LN_ORIG_DT` | `origination_date` | Parse MM/DD/YYYY → DATE |
# MAGIC | `LN_MAT_DT` | `maturity_date` | Parse MM/DD/YYYY → DATE |
# MAGIC | `LN_1ST_PMT_DT` | `first_payment_date` | Parse MM/DD/YYYY → DATE |
# MAGIC | `LN_NXT_PMT_DT` | `next_payment_date` | Parse MM/DD/YYYY → DATE |
# MAGIC | `LN_STAT_CD` | `status` | `ACT`→Active, `CLO`→Closed, `DFT`→Default, `FRB`→Forbearance |
# MAGIC | `LN_DLQ_DAYS` | `delinquency_days` | Parse → INT |
# MAGIC | `LN_ESCROW_BAL` | `escrow_balance` | Remove commas → DECIMAL(10,2) |
# MAGIC | `LN_LTV_PCT` | `ltv_percent` | Parse → DECIMAL(5,2) |
# MAGIC | `PROP_ADDR_LN1` | `property_address` | Direct copy |
# MAGIC | `PROP_CTY_NM` | `property_city` | Direct copy |
# MAGIC | `PROP_ST_CD` | `property_state` | Direct copy |
# MAGIC | `PROP_ZIP_CD` | `property_zip` | Direct copy |
# MAGIC | `PROP_TYP_CD` | `property_type` | `SFR`→Single Family, `CND`→Condominium, etc. |
# MAGIC | `PROP_APRS_VAL` | `appraised_value` | Remove commas → DECIMAL(12,2) |
# MAGIC | `LN_CRET_DT` | `created_at` | Parse MM/DD/YYYY → TIMESTAMP |
# MAGIC | `LN_UPDT_DT` | `updated_at` | Parse MM/DD/YYYY → TIMESTAMP |
# MAGIC | *(derived)* | `origination_year` | `year(origination_date)` — partition column |

# COMMAND ----------

LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


def expand_codes(col_name, mapping):
    expr = F.col(col_name)
    for code, label in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(label)).otherwise(expr)
    return expr


run_ts = datetime.utcnow().isoformat()

transformed_df = source_df.select(
    F.col("LN_ACCT_NBR").alias("account_number"),
    F.col("BORR_ID").alias("_borr_external_id"),
    F.col("PROD_CD").alias("_prod_code"),
    # Amounts: strip commas, cast to decimal
    F.regexp_replace(F.col("LN_ORIG_AMT"), ",", "").cast(DecimalType(12, 2)).alias("original_amount"),
    F.regexp_replace(F.col("LN_CURR_BAL"), ",", "").cast(DecimalType(12, 2)).alias("current_balance"),
    F.regexp_replace(F.col("LN_INT_RT"), ",", "").cast(DecimalType(5, 3)).alias("interest_rate"),
    F.col("LN_TERM_MOS").cast(IntegerType()).alias("term_months"),
    F.regexp_replace(F.col("LN_PMT_AMT"), ",", "").cast(DecimalType(10, 2)).alias("monthly_payment"),
    # Dates
    F.to_date(F.col("LN_ORIG_DT"), "MM/dd/yyyy").alias("origination_date"),
    F.to_date(F.col("LN_MAT_DT"), "MM/dd/yyyy").alias("maturity_date"),
    F.to_date(F.col("LN_1ST_PMT_DT"), "MM/dd/yyyy").alias("first_payment_date"),
    F.to_date(F.col("LN_NXT_PMT_DT"), "MM/dd/yyyy").alias("next_payment_date"),
    # Status expansion
    expand_codes("LN_STAT_CD", LOAN_STATUS_MAP).alias("status"),
    F.col("LN_DLQ_DAYS").cast(IntegerType()).alias("delinquency_days"),
    F.regexp_replace(F.col("LN_ESCROW_BAL"), ",", "").cast(DecimalType(10, 2)).alias("escrow_balance"),
    F.regexp_replace(F.col("LN_LTV_PCT"), ",", "").cast(DecimalType(5, 2)).alias("ltv_percent"),
    # Property fields
    F.col("PROP_ADDR_LN1").alias("property_address"),
    F.col("PROP_CTY_NM").alias("property_city"),
    F.col("PROP_ST_CD").alias("property_state"),
    F.col("PROP_ZIP_CD").alias("property_zip"),
    expand_codes("PROP_TYP_CD", PROPERTY_TYPE_MAP).alias("property_type"),
    F.regexp_replace(F.col("PROP_APRS_VAL"), ",", "").cast(DecimalType(12, 2)).alias("appraised_value"),
    # Audit timestamps
    F.to_timestamp(F.col("LN_CRET_DT"), "MM/dd/yyyy").alias("created_at"),
    F.to_timestamp(F.col("LN_UPDT_DT"), "MM/dd/yyyy").alias("updated_at"),
    F.lit("CDW_LN_ACCT").alias("_migration_source"),
    F.lit(run_ts).cast("timestamp").alias("_migrated_at"),
)

# Derive partition column
transformed_df = transformed_df.withColumn(
    "origination_year", F.year(F.col("origination_date"))
)

print("Schema after transformation:")
transformed_df.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Resolve Foreign Keys
# MAGIC
# MAGIC Join with borrower and product lookup tables to resolve string IDs
# MAGIC to modern BIGINT foreign keys. Using left joins so unresolved FKs
# MAGIC become NULL and are caught by the error-routing step.

# COMMAND ----------

# Join borrower FK
transformed_df = transformed_df.join(borrower_lookup, on="_borr_external_id", how="left")

# Join product FK
transformed_df = transformed_df.join(product_lookup, on="_prod_code", how="left")

# Drop temporary join columns
transformed_df = transformed_df.drop("_borr_external_id", "_prod_code")

display(transformed_df.select("account_number", "borrower_id", "product_id", "status", "original_amount"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Validate Required Fields & Route Errors
# MAGIC
# MAGIC Check that required fields are not NULL — this catches both source data
# MAGIC issues AND failed FK resolution (if a borrower or product wasn't found).

# COMMAND ----------

required_cols = ["account_number", "borrower_id", "product_id", "original_amount", "current_balance"]

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
    print("\n⚠️ Error records (check FK resolution):")
    display(error_df.select("account_number", "borrower_id", "product_id", "_error_reason"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Write to Delta Lake
# MAGIC
# MAGIC Table is partitioned by `status` and `origination_year` for efficient
# MAGIC filtering of active vs closed loans and time-range analytics.

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

# Verify FK joins worked
display(
    spark.sql(f"""
        SELECT la.account_number, b.first_name, b.last_name, lp.name AS product_name, la.status
        FROM {target_table} la
        JOIN {borrower_table} b ON la.borrower_id = b.borrower_id
        JOIN {product_table} lp ON la.product_id = lp.product_id
    """)
)
