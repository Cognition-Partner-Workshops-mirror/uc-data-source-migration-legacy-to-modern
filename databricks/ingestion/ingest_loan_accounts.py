"""
PySpark Ingestion Script: Loan Accounts
Source: CDW_LN_ACCT (legacy CSV/Parquet extract)
Target: loan_warehouse.loan_accounts (Delta Lake)

Transformations applied:
  - Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  - Resolve BORR_ID -> borrower_id via lookup to loan_warehouse.borrowers
  - Resolve PROD_CD -> product_id via lookup to loan_warehouse.loan_products
  - Parse amount strings (commas) -> DecimalType
  - Parse date strings (MM/DD/YYYY) -> DateType / TimestampType
  - Expand LN_STAT_CD (ACT/CLO/DFT/FRB) -> status (Active/Closed/Default/Forbearance)
  - Expand PROP_TYP_CD (SFR/CND/MFR/TWN) -> property_type (readable names)

Prerequisites:
  - borrowers table must be populated first (for FK resolution)
  - loan_products table must be populated first (for FK resolution)
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from utils import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    col_expand_status,
    col_parse_amount,
    col_parse_date,
    col_parse_int,
    col_parse_timestamp,
    log_row_counts,
    quarantine_malformed_rows,
    tag_migration_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/legacy-extracts/CDW_LN_ACCT/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_accounts"
BORROWER_TABLE = "loan_warehouse.borrowers"
PRODUCT_TABLE = "loan_warehouse.loan_products"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "quote": '"',
    "escape": '"',
}


def read_source(spark: SparkSession):
    """Read the legacy CDW_LN_ACCT extract."""
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for key, val in CSV_OPTIONS.items():
            reader = reader.option(key, val)
    return reader.load(SOURCE_PATH)


def resolve_borrower_ids(spark: SparkSession):
    """Load the borrower lookup table (external_id -> borrower_id)."""
    return (
        spark.table(BORROWER_TABLE)
        .select(
            F.col("borrower_id").alias("_resolved_borrower_id"),
            F.col("external_id").alias("_borr_external_id"),
        )
    )


def resolve_product_ids(spark: SparkSession):
    """Load the product lookup table (code -> product_id)."""
    return (
        spark.table(PRODUCT_TABLE)
        .select(
            F.col("product_id").alias("_resolved_product_id"),
            F.col("code").alias("_prod_code"),
        )
    )


def transform(df, borrower_lookup, product_lookup):
    """Apply all column mappings, type conversions, and FK resolution."""

    # Step 1: Column-level transformations (rename, parse, expand)
    transformed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("_borr_external_id"),
        # Denormalized borrower fields intentionally dropped:
        #   BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4
        F.col("PROD_CD").alias("_prod_code"),
        col_parse_amount("LN_ORIG_AMT", "original_amount"),
        col_parse_amount("LN_CURR_BAL", "current_balance"),
        col_parse_amount("LN_INT_RT", "interest_rate", precision=5, scale=3),
        col_parse_int("LN_TERM_MOS", "term_months"),
        col_parse_amount("LN_PMT_AMT", "monthly_payment", precision=10, scale=2),
        col_parse_date("LN_ORIG_DT", "origination_date"),
        col_parse_date("LN_MAT_DT", "maturity_date"),
        col_parse_date("LN_1ST_PMT_DT", "first_payment_date"),
        col_parse_date("LN_NXT_PMT_DT", "next_payment_date"),
        col_expand_status("LN_STAT_CD", LOAN_STATUS_MAP, "status"),
        col_parse_int("LN_DLQ_DAYS", "delinquency_days"),
        col_parse_amount("LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2),
        col_parse_amount("LN_LTV_PCT", "ltv_percent", precision=5, scale=2),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        col_expand_status("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
        col_parse_amount("PROP_APRS_VAL", "appraised_value"),
        col_parse_timestamp("LN_CRET_DT", "created_at"),
        col_parse_timestamp("LN_UPDT_DT", "updated_at"),
    )

    # Step 2: Resolve borrower FK
    transformed = transformed.join(
        borrower_lookup,
        on="_borr_external_id",
        how="left",
    )

    # Step 3: Resolve product FK
    transformed = transformed.join(
        product_lookup,
        on="_prod_code",
        how="left",
    )

    # Step 4: Rename resolved IDs and drop join keys
    transformed = (
        transformed
        .withColumnRenamed("_resolved_borrower_id", "borrower_id")
        .withColumnRenamed("_resolved_product_id", "product_id")
        .drop("_borr_external_id", "_prod_code")
    )

    # Log unresolved FK references
    unresolved_borrowers = transformed.filter(F.col("borrower_id").isNull()).count()
    unresolved_products = transformed.filter(F.col("product_id").isNull()).count()
    if unresolved_borrowers > 0:
        print(f"[MIGRATION] WARNING: {unresolved_borrowers} loan accounts have unresolved borrower references")
    if unresolved_products > 0:
        print(f"[MIGRATION] WARNING: {unresolved_products} loan accounts have unresolved product references")

    return transformed


def run(spark: SparkSession):
    """Execute the full loan account ingestion pipeline."""
    print(f"[MIGRATION] Starting loan account ingestion from {SOURCE_PATH}")

    # Read source
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"[MIGRATION] Read {source_count} rows from CDW_LN_ACCT")

    # Load FK lookup tables
    borrower_lookup = resolve_borrower_ids(spark)
    product_lookup = resolve_product_ids(spark)

    # Transform
    transformed_df = transform(source_df, borrower_lookup, product_lookup)

    # Add migration metadata
    transformed_df = tag_migration_metadata(transformed_df, "CDW_LN_ACCT")

    # Quarantine rows with NULL in required fields (including unresolved FKs)
    required_cols = [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date",
    ]
    valid_df, quarantine_df = quarantine_malformed_rows(
        transformed_df, required_cols, "CDW_LN_ACCT", spark
    )

    # Write quarantined rows
    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        print(f"[MIGRATION] WARNING: {quarantine_count} rows quarantined for loan_accounts")
        quarantine_df.write.format("delta").mode("append").saveAsTable(QUARANTINE_TABLE)

    # Deduplicate on account_number (keep latest updated_at)
    from pyspark.sql.window import Window
    dedup_window = Window.partitionBy("account_number").orderBy(F.col("updated_at").desc())
    valid_df = (
        valid_df
        .withColumn("_row_num", F.row_number().over(dedup_window))
        .filter(F.col("_row_num") == 1)
        .drop("_row_num")
    )

    # Write to Delta Lake target
    target_count = valid_df.count()
    valid_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    # Reconciliation
    stats = log_row_counts(spark, source_count, target_count, quarantine_count, "loan_accounts")
    print(f"[MIGRATION] Loan account ingestion complete")
    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_LoanAccounts").getOrCreate()
    try:
        run(spark)
    finally:
        spark.stop()
