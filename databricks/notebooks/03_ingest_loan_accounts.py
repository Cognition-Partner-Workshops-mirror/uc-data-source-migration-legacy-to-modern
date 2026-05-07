# Databricks notebook source

# MAGIC %md
# MAGIC # Loan Account Ingestion — CDW_LN_ACCT → loan_warehouse.loan_accounts
# MAGIC
# MAGIC This notebook ingests the legacy **CDW_LN_ACCT** (Loan Accounts) table into the
# MAGIC modern Delta Lake **loan_accounts** fact table.
# MAGIC
# MAGIC ### Key Challenges
# MAGIC | Issue | Detail |
# MAGIC |-------|--------|
# MAGIC | Denormalized borrower data | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` embedded in loan rows |
# MAGIC | Foreign key resolution | `BORR_ID` → `borrower_key`, `PROD_CD` → `product_key` |
# MAGIC | All-VARCHAR columns | Amounts, dates, rates, percentages all stored as strings |
# MAGIC | Status codes | `ACT`/`CLO`/`DFT`/`FRB` need expansion |
# MAGIC | Property type codes | `SFR`/`CND`/`MFR`/`TWN` need expansion |
# MAGIC
# MAGIC ### Transformation Summary
# MAGIC 1. Schema validation & quarantine
# MAGIC 2. **Drop denormalized borrower columns** (use FK to borrowers table instead)
# MAGIC 3. **Resolve foreign keys** to `borrowers` and `loan_products` dimension tables
# MAGIC 4. Parse 6 date columns (`MM/DD/YYYY` → `DateType`/`TimestampType`)
# MAGIC 5. Parse 7 amount/rate columns (strip commas → `DecimalType`)
# MAGIC 6. Parse 2 integer columns
# MAGIC 7. Expand loan status and property type codes
# MAGIC 8. Derive `origination_year` for partitioning

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Configuration

# COMMAND ----------

dbutils.widgets.text("source_path", "/mnt/legacy-extract/cdw_ln_acct/", "Source Path")
dbutils.widgets.dropdown("file_format", "csv", ["csv", "parquet"], "File Format")
dbutils.widgets.text("target_table", "loan_warehouse.loan_accounts", "Target Table")
dbutils.widgets.text("borrower_table", "loan_warehouse.borrowers", "Borrower Table")
dbutils.widgets.text("product_table", "loan_warehouse.loan_products", "Product Table")
dbutils.widgets.text("quarantine_path", "/mnt/quarantine/loan_accounts/", "Quarantine Path")

source_path = dbutils.widgets.get("source_path")
file_format = dbutils.widgets.get("file_format")
target_table = dbutils.widgets.get("target_table")
borrower_table = dbutils.widgets.get("borrower_table")
product_table = dbutils.widgets.get("product_table")
quarantine_path = dbutils.widgets.get("quarantine_path")

print(f"Source:          {source_path}")
print(f"Target:          {target_table}")
print(f"Borrower table:  {borrower_table}")
print(f"Product table:   {product_table}")

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
    "LN_ACCT_NBR", "BORR_ID", "BORR_FST_NM", "BORR_LST_NM", "BORR_SSN_LST4",
    "PROD_CD", "LN_ORIG_AMT", "LN_CURR_BAL", "LN_INT_RT", "LN_TERM_MOS",
    "LN_PMT_AMT", "LN_ORIG_DT", "LN_MAT_DT", "LN_1ST_PMT_DT", "LN_NXT_PMT_DT",
    "LN_STAT_CD", "LN_DLQ_DAYS", "LN_ESCROW_BAL", "LN_LTV_PCT",
    "PROP_ADDR_LN1", "PROP_CTY_NM", "PROP_ST_CD", "PROP_ZIP_CD",
    "PROP_TYP_CD", "PROP_APRS_VAL", "LN_CRET_DT", "LN_UPDT_DT",
]

missing = set(EXPECTED_COLUMNS) - set(raw_df.columns)
if missing:
    raise ValueError(f"Source is missing expected columns: {sorted(missing)}")
print("Schema validation passed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Quarantine Bad Rows
# MAGIC Required fields: `LN_ACCT_NBR`, `BORR_ID`, `PROD_CD`, `LN_ORIG_AMT`, `LN_CURR_BAL`.

# COMMAND ----------

from pyspark.sql import functions as F

REQUIRED_FIELDS = ["LN_ACCT_NBR", "BORR_ID", "PROD_CD", "LN_ORIG_AMT", "LN_CURR_BAL"]

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
# MAGIC ## Step 5 — Resolve Foreign Keys
# MAGIC
# MAGIC ### 5a — Borrower FK Resolution
# MAGIC The legacy `BORR_ID` (e.g. `"B-10001"`) is looked up in the already-loaded
# MAGIC `borrowers` Delta table to get the surrogate `borrower_key`. Unmatched rows
# MAGIC are logged but **not dropped** — they proceed with `NULL` borrower_key so
# MAGIC the data quality framework can catch them.

# COMMAND ----------

borrowers = spark.table(borrower_table).select(
    F.col("borrower_key"),
    F.col("external_id").alias("_borr_ext_id"),
)
good_df = good_df.join(borrowers, good_df["BORR_ID"] == borrowers["_borr_ext_id"], "left")

unmatched_borr = good_df.filter(F.col("borrower_key").isNull()).count()
print(f"Unmatched borrower IDs: {unmatched_borr}")

good_df = good_df.drop("_borr_ext_id")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5b — Product FK Resolution
# MAGIC The legacy `PROD_CD` (e.g. `"FXD30"`) is looked up in `loan_products` to get
# MAGIC the surrogate `product_key`.

# COMMAND ----------

products = spark.table(product_table).select(
    F.col("product_key"),
    F.col("code").alias("_prod_code"),
)
good_df = good_df.join(products, good_df["PROD_CD"] == products["_prod_code"], "left")

unmatched_prod = good_df.filter(F.col("product_key").isNull()).count()
print(f"Unmatched product codes: {unmatched_prod}")

good_df = good_df.drop("_prod_code")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6 — Parse Date Columns
# MAGIC Six date columns converted from `MM/DD/YYYY` strings:
# MAGIC
# MAGIC | Legacy Column | Modern Column | Target Type |
# MAGIC |---------------|---------------|-------------|
# MAGIC | `LN_ORIG_DT` | `origination_date` | DATE |
# MAGIC | `LN_MAT_DT` | `maturity_date` | DATE |
# MAGIC | `LN_1ST_PMT_DT` | `first_payment_date` | DATE |
# MAGIC | `LN_NXT_PMT_DT` | `next_payment_date` | DATE |
# MAGIC | `LN_CRET_DT` | `created_at` | TIMESTAMP |
# MAGIC | `LN_UPDT_DT` | `updated_at` | TIMESTAMP |

# COMMAND ----------

from pyspark.sql.types import DateType, TimestampType

date_cols = [
    ("LN_ORIG_DT", "origination_date", DateType()),
    ("LN_MAT_DT", "maturity_date", DateType()),
    ("LN_1ST_PMT_DT", "first_payment_date", DateType()),
    ("LN_NXT_PMT_DT", "next_payment_date", DateType()),
]

for src, tgt, dtype in date_cols:
    good_df = good_df.withColumn(f"_raw_{tgt}", F.col(src))
    good_df = good_df.withColumn(tgt, F.to_date(F.col(src), "MM/dd/yyyy").cast(dtype))

ts_cols = [("LN_CRET_DT", "created_at"), ("LN_UPDT_DT", "updated_at")]
for src, tgt in ts_cols:
    good_df = good_df.withColumn(f"_raw_{tgt}", F.col(src))
    good_df = good_df.withColumn(tgt, F.to_timestamp(F.col(src), "MM/dd/yyyy").cast(TimestampType()))

display(good_df.select("LN_ORIG_DT", "origination_date", "LN_MAT_DT", "maturity_date").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7 — Parse Amount / Rate / Percentage Columns
# MAGIC Seven columns need comma stripping and decimal casting:
# MAGIC
# MAGIC | Legacy Column | Modern Column | Precision |
# MAGIC |---------------|---------------|-----------|
# MAGIC | `LN_ORIG_AMT` | `original_amount` | DECIMAL(12,2) |
# MAGIC | `LN_CURR_BAL` | `current_balance` | DECIMAL(12,2) |
# MAGIC | `LN_PMT_AMT` | `monthly_payment` | DECIMAL(10,2) |
# MAGIC | `LN_ESCROW_BAL` | `escrow_balance` | DECIMAL(10,2) |
# MAGIC | `PROP_APRS_VAL` | `appraised_value` | DECIMAL(12,2) |
# MAGIC | `LN_INT_RT` | `interest_rate` | DECIMAL(5,3) |
# MAGIC | `LN_LTV_PCT` | `ltv_percent` | DECIMAL(5,2) |

# COMMAND ----------

from pyspark.sql.types import DecimalType, IntegerType

amount_cols = [
    ("LN_ORIG_AMT", "original_amount", 12, 2),
    ("LN_CURR_BAL", "current_balance", 12, 2),
    ("LN_PMT_AMT", "monthly_payment", 10, 2),
    ("LN_ESCROW_BAL", "escrow_balance", 10, 2),
    ("PROP_APRS_VAL", "appraised_value", 12, 2),
    ("LN_INT_RT", "interest_rate", 5, 3),
    ("LN_LTV_PCT", "ltv_percent", 5, 2),
]

for src, tgt, prec, scale in amount_cols:
    good_df = good_df.withColumn(f"_raw_{tgt}", F.col(src))
    good_df = good_df.withColumn(
        tgt,
        F.regexp_replace(F.col(src), ",", "").cast(DecimalType(prec, scale)),
    )

display(good_df.select("LN_ORIG_AMT", "original_amount", "LN_CURR_BAL", "current_balance").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8 — Parse Integer Columns
# MAGIC - `LN_TERM_MOS` → `term_months`
# MAGIC - `LN_DLQ_DAYS` → `delinquency_days`

# COMMAND ----------

good_df = good_df.withColumn("_raw_term_months", F.col("LN_TERM_MOS"))
good_df = good_df.withColumn("term_months", F.col("LN_TERM_MOS").cast(IntegerType()))

good_df = good_df.withColumn("_raw_delinquency_days", F.col("LN_DLQ_DAYS"))
good_df = good_df.withColumn("delinquency_days", F.col("LN_DLQ_DAYS").cast(IntegerType()))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9 — Expand Status & Property Type Codes
# MAGIC
# MAGIC **Loan Status:**
# MAGIC | Code | Expanded |
# MAGIC |------|----------|
# MAGIC | `ACT` | `ACTIVE` |
# MAGIC | `CLO` | `CLOSED` |
# MAGIC | `DFT` | `DEFAULT` |
# MAGIC | `FRB` | `FORBEARANCE` |
# MAGIC
# MAGIC **Property Type:**
# MAGIC | Code | Expanded |
# MAGIC |------|----------|
# MAGIC | `SFR` | `Single Family` |
# MAGIC | `CND` | `Condominium` |
# MAGIC | `MFR` | `Multi-Family` |
# MAGIC | `TWN` | `Townhouse` |

# COMMAND ----------

LOAN_STATUS_MAP = {"ACT": "ACTIVE", "CLO": "CLOSED", "DFT": "DEFAULT", "FRB": "FORBEARANCE"}
PROPERTY_TYPE_MAP = {"SFR": "Single Family", "CND": "Condominium", "MFR": "Multi-Family", "TWN": "Townhouse"}

for col_name, mapping, target_col in [
    ("LN_STAT_CD", LOAN_STATUS_MAP, "status"),
    ("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
]:
    map_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])
    good_df = good_df.withColumn(
        target_col,
        F.coalesce(map_expr[F.upper(F.col(col_name))], F.col(col_name)),
    )

display(good_df.select("LN_STAT_CD", "status", "PROP_TYP_CD", "property_type").limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10 — Derive Origination Year & Rename Columns
# MAGIC We extract `origination_year` from `origination_date` for potential
# MAGIC analytics use. Direct-copy columns are renamed. The three **denormalized
# MAGIC borrower columns** (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) are
# MAGIC dropped — the borrower data lives in the normalized `borrowers` table and
# MAGIC is referenced via `borrower_key`.

# COMMAND ----------

good_df = good_df.withColumn("origination_year", F.year(F.col("origination_date")))

good_df = (
    good_df
    .withColumnRenamed("LN_ACCT_NBR", "account_number")
    .withColumnRenamed("PROP_ADDR_LN1", "property_address")
    .withColumnRenamed("PROP_CTY_NM", "property_city")
    .withColumnRenamed("PROP_ST_CD", "property_state")
    .withColumnRenamed("PROP_ZIP_CD", "property_zip")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 11 — Add Audit Columns, Select Final Set & Write

# COMMAND ----------

good_df = (
    good_df
    .withColumn("_ingestion_ts", F.current_timestamp())
    .withColumn("_source_system", F.lit("CDW_LN_ACCT"))
)

FINAL_COLUMNS = [
    "account_number", "borrower_key", "product_key",
    "original_amount", "current_balance", "interest_rate",
    "term_months", "monthly_payment",
    "origination_date", "maturity_date",
    "first_payment_date", "next_payment_date",
    "status", "delinquency_days", "escrow_balance", "ltv_percent",
    "property_address", "property_city", "property_state", "property_zip",
    "property_type", "appraised_value", "origination_year",
    "created_at", "updated_at",
    "_ingestion_ts", "_source_system",
]

final_df = good_df.select(*FINAL_COLUMNS)
display(final_df.limit(5))

# COMMAND ----------

final_df.write.format("delta").mode("overwrite").partitionBy("status").saveAsTable(target_table)
print(f"Wrote {final_df.count()} rows to {target_table}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 12 — Persist Quarantined Rows

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
# MAGIC | Unmatched borrower FKs | `{unmatched_borr}` |
# MAGIC | Unmatched product FKs | `{unmatched_prod}` |
# MAGIC | Target table | `loan_warehouse.loan_accounts` |
# MAGIC | Partition column | `status` |
