"""
Ingestion script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads legacy loan account data, transforms all VARCHAR columns to proper
types, expands status/property codes, resolves borrower_id and product_id
foreign keys against already-loaded dimension tables, and writes to Delta.

IMPORTANT: Run ingest_borrowers and ingest_loan_products BEFORE this script.

Usage (Databricks notebook):
    %run ./common
    %run ./ingest_loan_accounts
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

from common import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_decimal,
    parse_legacy_int,
    parse_legacy_timestamp,
    tag_ingestion_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "dbfs:/mnt/legacy-extracts/cdw_ln_acct/"
TARGET_TABLE = "loan_warehouse.loan_accounts"
SOURCE_FORMAT = "csv"

LEGACY_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_SSN_LST4", StringType(), True),
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


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def extract(spark: SparkSession) -> DataFrame:
    reader = spark.read.format(SOURCE_FORMAT).schema(LEGACY_SCHEMA)
    if SOURCE_FORMAT == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(SOURCE_PATH)
    print(f"[ingest_loan_accounts] Extracted {df.count()} rows from {SOURCE_PATH}")
    return df


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(spark: SparkSession, df: DataFrame) -> DataFrame:
    # Resolve borrower_id FK from the already-loaded borrowers table
    borrowers_lookup = spark.table("loan_warehouse.borrowers").select(
        F.col("borrower_id"),
        F.col("external_id").alias("_borr_ext_id"),
    )

    # Resolve product_id FK from the already-loaded loan_products table
    products_lookup = spark.table("loan_warehouse.loan_products").select(
        F.col("product_id"),
        F.col("code").alias("_prod_code"),
    )

    # Core transformations
    transformed = df.select(
        F.trim(F.col("LN_ACCT_NBR")).alias("account_number"),
        F.trim(F.col("BORR_ID")).alias("_borr_id_raw"),
        F.trim(F.col("PROD_CD")).alias("_prod_cd_raw"),
        parse_legacy_amount("LN_ORIG_AMT").alias("original_amount"),
        parse_legacy_amount("LN_CURR_BAL").alias("current_balance"),
        parse_legacy_decimal("LN_INT_RT", 5, 3).alias("interest_rate"),
        parse_legacy_int("LN_TERM_MOS").alias("term_months"),
        parse_legacy_amount("LN_PMT_AMT", 10, 2).alias("monthly_payment"),
        parse_legacy_date("LN_ORIG_DT").alias("origination_date"),
        parse_legacy_date("LN_MAT_DT").alias("maturity_date"),
        parse_legacy_date("LN_1ST_PMT_DT").alias("first_payment_date"),
        parse_legacy_date("LN_NXT_PMT_DT").alias("next_payment_date"),
        expand_status("LN_STAT_CD", LOAN_STATUS_MAP).alias("status"),
        F.coalesce(parse_legacy_int("LN_DLQ_DAYS"), F.lit(0)).alias("delinquency_days"),
        F.coalesce(parse_legacy_amount("LN_ESCROW_BAL", 10, 2), F.lit(0.00)).alias("escrow_balance"),
        parse_legacy_decimal("LN_LTV_PCT", 5, 2).alias("ltv_percent"),
        F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
        F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
        F.upper(F.trim(F.col("PROP_ST_CD"))).alias("property_state"),
        F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
        expand_status("PROP_TYP_CD", PROPERTY_TYPE_MAP, "OTHER").alias("property_type"),
        parse_legacy_amount("PROP_APRS_VAL").alias("appraised_value"),
        parse_legacy_timestamp("LN_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("LN_UPDT_DT").alias("updated_at"),
    )

    # Derive origination_year partition column
    transformed = transformed.withColumn(
        "origination_year",
        F.year(F.col("origination_date")),
    )

    # Resolve borrower FK
    transformed = transformed.join(
        borrowers_lookup,
        transformed["_borr_id_raw"] == borrowers_lookup["_borr_ext_id"],
        "left",
    ).drop("_borr_ext_id", "_borr_id_raw")

    # Resolve product FK
    transformed = transformed.join(
        products_lookup,
        transformed["_prod_cd_raw"] == products_lookup["_prod_code"],
        "left",
    ).drop("_prod_code", "_prod_cd_raw")

    # Log orphaned records (missing FK matches)
    orphan_borrower = transformed.filter(F.col("borrower_id").isNull()).count()
    orphan_product = transformed.filter(F.col("product_id").isNull()).count()
    if orphan_borrower > 0:
        print(f"[ingest_loan_accounts] WARNING: {orphan_borrower} loans have no matching borrower")
    if orphan_product > 0:
        print(f"[ingest_loan_accounts] WARNING: {orphan_product} loans have no matching product")

    # Business rule warnings
    delinquent_active = transformed.filter(
        (F.col("status") == "ACTIVE") & (F.col("delinquency_days") > 0)
    ).count()
    if delinquent_active > 0:
        print(
            f"[ingest_loan_accounts] WARNING: {delinquent_active} ACTIVE loans "
            f"have delinquency_days > 0 — possible status/delinquency mismatch"
        )

    transformed = tag_ingestion_metadata(transformed, "CDW_LN_ACCT")

    print(f"[ingest_loan_accounts] Transformed {transformed.count()} rows")
    return transformed


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load(df: DataFrame):
    df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).partitionBy("origination_year").saveAsTable(TARGET_TABLE)
    print(f"[ingest_loan_accounts] Loaded data into {TARGET_TABLE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession):
    raw = extract(spark)
    clean = transform(spark, raw)
    load(clean)
    print("[ingest_loan_accounts] Pipeline complete")


if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestLoanAccounts").getOrCreate()
    run(spark)
