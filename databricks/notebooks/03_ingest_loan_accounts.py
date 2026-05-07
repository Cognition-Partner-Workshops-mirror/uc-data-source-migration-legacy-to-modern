# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Notebook 03: Ingest Loan Accounts
# MAGIC **Source:** `CDW_LN_ACCT` (Legacy Corporate Data Warehouse)
# MAGIC **Target:** `loan_warehouse.loan_accounts` (Delta Lake)
# MAGIC
# MAGIC This is the most complex ingestion notebook. It transforms the legacy loan account table
# MAGIC — which contains denormalized borrower data, all-VARCHAR columns, and no foreign keys —
# MAGIC into a normalized fact table with proper types and FK references.
# MAGIC
# MAGIC ### Prerequisites
# MAGIC - **Notebook 01** (`ingest_borrowers`) must have been run first — we resolve `BORR_ID` → `borrower_id` via FK lookup.
# MAGIC - **Notebook 02** (`ingest_loan_products`) must have been run first — we resolve `PROD_CD` → `product_id` via FK lookup.
# MAGIC
# MAGIC ### Anomalies Handled
# MAGIC | ID | Anomaly | Severity |
# MAGIC |----|---------|----------|
# MAGIC | ANO-001 | Numeric amounts as strings with commas | Critical |
# MAGIC | ANO-002 | Dates in `MM/DD/YYYY` string format | Critical |
# MAGIC | ANO-003 | No FK constraints — orphaned borrower/product references | Critical |
# MAGIC | ANO-004 | Status/property type code abbreviations | High |
# MAGIC | ANO-005 | Denormalized borrower data inconsistency (name drift) | High |
# MAGIC | ANO-009 | Delinquency days inconsistent with status code | Medium |
# MAGIC | ANO-010 | LTV percent doesn't match current balance / appraised value | Medium |

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Configuration

# COMMAND ----------

from datetime import datetime

SOURCE_PATH = "/mnt/legacy-cdw/CDW_LN_ACCT"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
BORROWER_TABLE = "loan_warehouse.borrowers"
PRODUCT_TABLE = "loan_warehouse.loan_products"
DQ_LOG_TABLE = "loan_warehouse.data_quality_log"
RUN_ID = f"loan_acct_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

print(f"Run ID: {RUN_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Define Legacy Schema
# MAGIC The loan account table has 27 columns — all VARCHAR. Notable issues:
# MAGIC - `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` are **denormalized copies** from the borrower master. These will be dropped in favor of a FK reference.
# MAGIC - Financial amounts (`LN_ORIG_AMT`, `LN_CURR_BAL`, etc.) contain commas.
# MAGIC - 6 date columns, all in `MM/DD/YYYY` string format.

# COMMAND ----------

from pyspark.sql.types import StructType, StructField, StringType

LEGACY_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),       # Denormalized — will drop
    StructField("BORR_LST_NM", StringType(), True),       # Denormalized — will drop
    StructField("BORR_SSN_LST4", StringType(), True),     # Denormalized — will drop
    StructField("PROD_CD", StringType(), True),
    StructField("LN_ORIG_AMT", StringType(), True),
    StructField("LN_CURR_BAL", StringType(), True),
    StructField("LN_INT_RT", StringType(), True),
    StructField("LN_TERM_MOS", StringType(), True),
    StructField("LN_PMT_AMT", StringType(), True),
    StructField("LN_ORIG_DT", StringType(), True),
    StructField("LN_MAT_DT", StringType(), True),
    StructField("LN_1ST_PMT_DT", StringType(), True),
    StructField("LN_NXT_PMT_DT", StringType(), True),
    StructField("LN_STAT_CD", StringType(), True),
    StructField("LN_DLQ_DAYS", StringType(), True),
    StructField("LN_ESCROW_BAL", StringType(), True),
    StructField("LN_LTV_PCT", StringType(), True),
    StructField("PROP_ADDR_LN1", StringType(), True),
    StructField("PROP_CTY_NM", StringType(), True),
    StructField("PROP_ST_CD", StringType(), True),
    StructField("PROP_ZIP_CD", StringType(), True),
    StructField("PROP_TYP_CD", StringType(), True),
    StructField("PROP_APRS_VAL", StringType(), True),
    StructField("LN_CRET_DT", StringType(), True),
    StructField("LN_UPDT_DT", StringType(), True),
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
display(source_df.limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Define Transformation Helpers
# MAGIC Same reusable functions as previous notebooks, plus status code expansion maps
# MAGIC for both loan status and property type.

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
    return cleaned.cast(DecimalType(12, 2)).alias(alias)

def expand_status(col_name, mapping, alias):
    mapping_expr = F.create_map(
        *[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    upper_col = F.upper(F.trim(F.col(col_name)))
    return F.coalesce(mapping_expr[upper_col], upper_col).alias(alias)

# Loan status: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
STATUS_MAP = {"ACT": "ACTIVE", "CLO": "CLOSED", "DFT": "DEFAULT", "FRB": "FORBEARANCE"}

# Property type: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family", "CND": "Condominium",
    "MFR": "Multi-Family", "TWN": "Townhouse",
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Resolve Foreign Keys
# MAGIC This is the key normalization step. Instead of carrying denormalized borrower data
# MAGIC inside each loan record, we look up the `borrower_id` and `product_id` from the
# MAGIC already-populated dimension tables.
# MAGIC
# MAGIC - `CDW_LN_ACCT.BORR_ID` → `loan_warehouse.borrowers.external_id` → `borrower_id`
# MAGIC - `CDW_LN_ACCT.PROD_CD` → `loan_warehouse.loan_products.code` → `product_id`
# MAGIC
# MAGIC We use **left joins** so that orphaned references (ANO-003) produce `NULL` FKs
# MAGIC rather than dropped records. These orphans are logged as anomalies.

# COMMAND ----------

borrowers = spark.table(BORROWER_TABLE).select(
    F.col("borrower_id"), F.col("external_id").alias("borr_ext_id")
)
products = spark.table(PRODUCT_TABLE).select(
    F.col("product_id"), F.col("code").alias("prod_code")
)

print(f"Borrowers available for FK resolution: {borrowers.count()}")
print(f"Products available for FK resolution: {products.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Apply Transformations
# MAGIC
# MAGIC Join with dimension tables and transform all columns:
# MAGIC
# MAGIC | Legacy Column | Modern Column | Transformation |
# MAGIC |---------------|---------------|----------------|
# MAGIC | `LN_ACCT_NBR` | `account_number` | Direct copy |
# MAGIC | `BORR_ID` | `borrower_id` | FK lookup → `BIGINT` |
# MAGIC | `BORR_FST_NM` | *(dropped)* | Use borrower FK instead |
# MAGIC | `BORR_LST_NM` | *(dropped)* | Use borrower FK instead |
# MAGIC | `BORR_SSN_LST4` | *(dropped)* | Use borrower FK instead |
# MAGIC | `PROD_CD` | `product_id` | FK lookup → `BIGINT` |
# MAGIC | `LN_ORIG_AMT` | `original_amount` | Strip commas → `DECIMAL(12,2)` |
# MAGIC | `LN_STAT_CD` | `status` | `ACT` → `ACTIVE`, `CLO` → `CLOSED`, etc. |
# MAGIC | `PROP_TYP_CD` | `property_type` | `SFR` → `Single Family`, etc. |
# MAGIC | All dates | `DATE` type | Parse `MM/DD/YYYY` |

# COMMAND ----------

transformed_df = (
    source_df
    .join(borrowers, source_df["BORR_ID"] == borrowers["borr_ext_id"], "left")
    .join(products, source_df["PROD_CD"] == products["prod_code"], "left")
    .select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("borrower_id"),
        F.col("product_id"),
        parse_legacy_amount("LN_ORIG_AMT", "original_amount"),
        parse_legacy_amount("LN_CURR_BAL", "current_balance"),
        F.col("LN_INT_RT").cast(DecimalType(5, 3)).alias("interest_rate"),
        F.col("LN_TERM_MOS").cast(IntegerType()).alias("term_months"),
        parse_legacy_amount("LN_PMT_AMT", "monthly_payment"),
        parse_legacy_date("LN_ORIG_DT", "origination_date"),
        parse_legacy_date("LN_MAT_DT", "maturity_date"),
        parse_legacy_date("LN_1ST_PMT_DT", "first_payment_date"),
        parse_legacy_date("LN_NXT_PMT_DT", "next_payment_date"),
        expand_status("LN_STAT_CD", STATUS_MAP, "status"),
        F.col("LN_DLQ_DAYS").cast(IntegerType()).alias("delinquency_days"),
        parse_legacy_amount("LN_ESCROW_BAL", "escrow_balance"),
        F.col("LN_LTV_PCT").cast(DecimalType(5, 2)).alias("ltv_percent"),
        F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
        F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
        F.trim(F.col("PROP_ST_CD")).alias("property_state"),
        F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
        expand_status("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
        parse_legacy_amount("PROP_APRS_VAL", "appraised_value"),
        F.coalesce(
            F.to_timestamp(F.col("LN_CRET_DT"), "MM/dd/yyyy"),
            F.to_timestamp(F.col("LN_CRET_DT"), "yyyy-MM-dd"),
            F.current_timestamp()
        ).alias("created_at"),
        F.coalesce(
            F.to_timestamp(F.col("LN_UPDT_DT"), "MM/dd/yyyy"),
            F.to_timestamp(F.col("LN_UPDT_DT"), "yyyy-MM-dd"),
            F.current_timestamp()
        ).alias("updated_at"),
        F.current_timestamp().alias("_ingestion_ts"),
        F.lit("CDW").alias("_source_system"),
    )
)

print(f"Transformed rows: {transformed_df.count()}")
display(transformed_df.limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Detect Data Quality Anomalies
# MAGIC
# MAGIC This is the most comprehensive anomaly detection of all four notebooks:
# MAGIC
# MAGIC 1. **ANO-003 — Orphaned borrower references:** Loan accounts where `BORR_ID` doesn't match any record in `borrowers`
# MAGIC 2. **ANO-003 — Orphaned product references:** Loan accounts where `PROD_CD` doesn't match any record in `loan_products`
# MAGIC 3. **ANO-005 — Denormalized name mismatch:** The copy of borrower name in `CDW_LN_ACCT` differs from the master in `borrowers`
# MAGIC 4. **ANO-009 — Delinquency-status inconsistency:** `LN_DLQ_DAYS > 0` but `LN_STAT_CD = 'ACT'`
# MAGIC 5. **ANO-010 — LTV mismatch:** Stored `LN_LTV_PCT` differs from `LN_CURR_BAL / PROP_APRS_VAL * 100` by more than 5 points

# COMMAND ----------

from functools import reduce
from pyspark.sql import DataFrame

anomalies = []

# --- ANO-003: Orphaned borrower references ---
borrower_ids = spark.table(BORROWER_TABLE).select(
    F.col("external_id").alias("valid_borr_id")
)
orphan_borrowers = (
    source_df
    .join(borrower_ids, source_df["BORR_ID"] == borrower_ids["valid_borr_id"], "left_anti")
    .filter(F.col("BORR_ID").isNotNull())
    .select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_LN_ACCT").alias("source_table"),
        F.col("LN_ACCT_NBR").alias("source_record_id"),
        F.lit("BORR_ID").alias("column_name"),
        F.lit("FK_VIOLATION").alias("anomaly_type"),
        F.lit("CRITICAL").alias("severity"),
        F.concat(F.lit("Borrower "), F.col("BORR_ID"),
                 F.lit(" not found in borrowers table")).alias("description"),
        F.col("BORR_ID").alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
)
anomalies.append(orphan_borrowers)

# --- ANO-003: Orphaned product references ---
product_codes = spark.table(PRODUCT_TABLE).select(
    F.col("code").alias("valid_prod_cd")
)
orphan_products = (
    source_df
    .join(product_codes, source_df["PROD_CD"] == product_codes["valid_prod_cd"], "left_anti")
    .filter(F.col("PROD_CD").isNotNull())
    .select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_LN_ACCT").alias("source_table"),
        F.col("LN_ACCT_NBR").alias("source_record_id"),
        F.lit("PROD_CD").alias("column_name"),
        F.lit("FK_VIOLATION").alias("anomaly_type"),
        F.lit("CRITICAL").alias("severity"),
        F.concat(F.lit("Product "), F.col("PROD_CD"),
                 F.lit(" not found in products table")).alias("description"),
        F.col("PROD_CD").alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
)
anomalies.append(orphan_products)

# --- ANO-005: Denormalized borrower name mismatch ---
borrowers_full = spark.table(BORROWER_TABLE).select(
    F.col("external_id"),
    F.col("first_name").alias("master_first"),
    F.col("last_name").alias("master_last"),
)
name_mismatches = (
    source_df
    .join(borrowers_full, source_df["BORR_ID"] == borrowers_full["external_id"], "inner")
    .filter(
        (F.upper(F.trim(F.col("BORR_FST_NM"))) != F.upper(F.col("master_first")))
        | (F.upper(F.trim(F.col("BORR_LST_NM"))) != F.upper(F.col("master_last")))
    )
    .select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_LN_ACCT").alias("source_table"),
        F.col("LN_ACCT_NBR").alias("source_record_id"),
        F.lit("BORR_FST_NM/BORR_LST_NM").alias("column_name"),
        F.lit("DATA_DRIFT").alias("anomaly_type"),
        F.lit("HIGH").alias("severity"),
        F.concat(
            F.lit("Denormalized name '"),
            F.col("BORR_FST_NM"), F.lit(" "), F.col("BORR_LST_NM"),
            F.lit("' differs from master '"),
            F.col("master_first"), F.lit(" "), F.col("master_last"), F.lit("'")
        ).alias("description"),
        F.concat(F.col("BORR_FST_NM"), F.lit(" "),
                 F.col("BORR_LST_NM")).alias("original_value"),
        F.concat(F.col("master_first"), F.lit(" "),
                 F.col("master_last")).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
)
anomalies.append(name_mismatches)

# --- ANO-009: Delinquency > 0 but status = ACT ---
delinquency_issues = source_df.filter(
    (F.col("LN_DLQ_DAYS").cast(IntegerType()) > 0)
    & (F.upper(F.trim(F.col("LN_STAT_CD"))) == "ACT")
).select(
    F.lit(RUN_ID).alias("run_id"),
    F.lit("CDW_LN_ACCT").alias("source_table"),
    F.col("LN_ACCT_NBR").alias("source_record_id"),
    F.lit("LN_DLQ_DAYS/LN_STAT_CD").alias("column_name"),
    F.lit("BUSINESS_RULE").alias("anomaly_type"),
    F.lit("MEDIUM").alias("severity"),
    F.concat(F.lit("Delinquency days="), F.col("LN_DLQ_DAYS"),
             F.lit(" but status="), F.col("LN_STAT_CD")).alias("description"),
    F.col("LN_DLQ_DAYS").alias("original_value"),
    F.lit(None).cast(StringType()).alias("corrected_value"),
    F.current_timestamp().alias("detected_at"),
)
anomalies.append(delinquency_issues)

# --- ANO-010: LTV mismatch ---
amt_clean = lambda c: F.regexp_replace(F.col(c), r"[$,\s]", "").cast(DecimalType(12, 2))
ltv_df = source_df.filter(
    F.col("PROP_APRS_VAL").isNotNull()
    & (amt_clean("PROP_APRS_VAL") > 0)
    & F.col("LN_LTV_PCT").isNotNull()
).withColumn("computed_ltv",
    amt_clean("LN_CURR_BAL") * 100 / amt_clean("PROP_APRS_VAL")
).withColumn("stored_ltv", F.col("LN_LTV_PCT").cast(DecimalType(5, 2)))

ltv_mismatches = ltv_df.filter(
    F.abs(F.col("stored_ltv") - F.col("computed_ltv")) > 5.0
).select(
    F.lit(RUN_ID).alias("run_id"),
    F.lit("CDW_LN_ACCT").alias("source_table"),
    F.col("LN_ACCT_NBR").alias("source_record_id"),
    F.lit("LN_LTV_PCT").alias("column_name"),
    F.lit("BUSINESS_RULE").alias("anomaly_type"),
    F.lit("MEDIUM").alias("severity"),
    F.concat(F.lit("Stored LTV="), F.col("stored_ltv"),
             F.lit(" vs computed="), F.round(F.col("computed_ltv"), 1)).alias("description"),
    F.col("LN_LTV_PCT").alias("original_value"),
    F.round(F.col("computed_ltv"), 1).cast(StringType()).alias("corrected_value"),
    F.current_timestamp().alias("detected_at"),
)
anomalies.append(ltv_mismatches)

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
# MAGIC Idempotent upsert on `account_number` (legacy `LN_ACCT_NBR`).
# MAGIC The target table is partitioned by `status` for efficient queries on active loans.

# COMMAND ----------

transformed_df.createOrReplaceTempView("loans_staging")

spark.sql(f"""
    MERGE INTO {TARGET_TABLE} AS target
    USING loans_staging AS source
    ON target.account_number = source.account_number
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
""")

target_count = spark.table(TARGET_TABLE).count()
print(f"Target rows after merge: {target_count}")
display(spark.table(TARGET_TABLE).limit(5))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10: Verify FK Resolution
# MAGIC Confirm that borrower and product FK lookups succeeded. Any `NULL` values
# MAGIC here indicate orphaned references (already logged as ANO-003 anomalies).

# COMMAND ----------

null_borrower_fk = spark.table(TARGET_TABLE).filter(F.col("borrower_id").isNull()).count()
null_product_fk = spark.table(TARGET_TABLE).filter(F.col("product_id").isNull()).count()

print(f"Loans with NULL borrower_id (orphaned): {null_borrower_fk}")
print(f"Loans with NULL product_id (orphaned):  {null_product_fk}")

if null_borrower_fk == 0 and null_product_fk == 0:
    print("FK RESOLUTION: PASS — all references resolved")
else:
    print("FK RESOLUTION: WARN — orphaned references exist (see DQ log)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC | Metric | Value |
# MAGIC |--------|-------|
# MAGIC | Source rows | `{source_count}` |
# MAGIC | Target rows | `{target_count}` |
# MAGIC | Anomalies | `{anomaly_count}` |
# MAGIC | Orphaned borrower FKs | `{null_borrower_fk}` |
# MAGIC | Orphaned product FKs | `{null_product_fk}` |
# MAGIC
# MAGIC **Next step:** Run `04_ingest_payments` notebook.
