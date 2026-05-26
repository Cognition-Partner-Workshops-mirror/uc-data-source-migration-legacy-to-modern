"""
PySpark ingestion script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads legacy loan account data from CSV/Parquet source files, applies all
transformations defined in data/mappings/column_mappings.md, and writes
to the Delta Lake loan_accounts table.

Key transformations:
  - Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) dropped
  - BORR_ID resolved to borrower_id via lookup against borrowers table
  - PROD_CD resolved to product_id via lookup against loan_products table
  - All amount VARCHARs → DECIMAL, all date VARCHARs → DATE
  - LN_STAT_CD expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
  - PROP_TYP_CD expanded: SFR→Single Family, CND→Condominium, etc.

Prerequisites:
  - borrowers and loan_products tables must be populated first (for FK lookups)

Usage:
  Run as a Databricks notebook or submit via spark-submit.
"""

import logging
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
)

# Import shared transformation utilities
from transform_utils import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    parse_rate_col,
    parse_percent_col,
    expand_status_col,
    add_etl_metadata,
    tag_malformed_rows,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

# =============================================================================
# Configuration
# =============================================================================
SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_ln_acct/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
WRITE_MODE = "overwrite"

# =============================================================================
# Logging setup
# =============================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_loan_accounts")

# =============================================================================
# Legacy source schema — all VARCHAR columns as StringType
# =============================================================================
LEGACY_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("BORR_ID", StringType(), True),
    # Denormalized borrower fields — will be dropped
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_SSN_LST4", StringType(), True),
    # Loan fields
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


def read_source(spark):
    """Read the legacy CDW_LN_ACCT data from the configured source path and format."""
    logger.info(f"Reading source data from {SOURCE_PATH} (format={SOURCE_FORMAT})")
    if SOURCE_FORMAT == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .schema(LEGACY_SCHEMA)
            .csv(SOURCE_PATH)
        )
    elif SOURCE_FORMAT == "parquet":
        df = spark.read.schema(LEGACY_SCHEMA).parquet(SOURCE_PATH)
    else:
        raise ValueError(f"Unsupported source format: {SOURCE_FORMAT}")

    record_count = df.count()
    logger.info(f"Read {record_count} records from legacy CDW_LN_ACCT")
    return df


def resolve_foreign_keys(spark, df):
    """
    Resolve legacy string IDs to modern surrogate keys via lookups against
    the already-populated borrowers and loan_products tables.

    - BORR_ID → borrower_id (via borrowers.external_id)
    - PROD_CD → product_id (via loan_products.code)

    Records with unresolvable FKs are logged but NOT dropped.
    """
    logger.info("Resolving foreign keys: BORR_ID → borrower_id, PROD_CD → product_id")

    # Load borrower lookup (external_id → borrower_id)
    borrower_lookup = (
        spark.table("loan_warehouse.borrowers")
        .select(
            F.col("external_id").alias("_borr_ext_id"),
            F.col("borrower_id").alias("_resolved_borrower_id"),
        )
    )

    # Load product lookup (code → product_id)
    product_lookup = (
        spark.table("loan_warehouse.loan_products")
        .select(
            F.col("code").alias("_prod_code"),
            F.col("product_id").alias("_resolved_product_id"),
        )
    )

    # Left join to resolve borrower FK
    df_with_borr = df.join(
        borrower_lookup,
        F.trim(df["BORR_ID"]) == borrower_lookup["_borr_ext_id"],
        "left",
    )

    # Left join to resolve product FK
    df_with_fks = df_with_borr.join(
        product_lookup,
        F.trim(df_with_borr["PROD_CD"]) == product_lookup["_prod_code"],
        "left",
    )

    # Log unresolved FKs
    unresolved_borr = df_with_fks.filter(F.col("_resolved_borrower_id").isNull()).count()
    unresolved_prod = df_with_fks.filter(F.col("_resolved_product_id").isNull()).count()
    if unresolved_borr > 0:
        logger.warning(f"{unresolved_borr} loan accounts have unresolvable BORR_ID")
    if unresolved_prod > 0:
        logger.warning(f"{unresolved_prod} loan accounts have unresolvable PROD_CD")

    return df_with_fks


def transform(spark, df):
    """
    Apply all column mappings and transformations to convert legacy loan account
    data to the modern loan_accounts schema.
    """
    logger.info("Applying transformations for CDW_LN_ACCT → loan_accounts")

    # Tag rows with potential quality issues
    df_tagged = tag_malformed_rows(df, [
        (F.col("LN_ACCT_NBR").isNull(), "NULL_ACCT_NBR"),
        (F.col("BORR_ID").isNull(), "NULL_BORR_ID"),
        (F.col("PROD_CD").isNull(), "NULL_PROD_CD"),
        (F.col("LN_ORIG_AMT").isNull(), "NULL_ORIG_AMT"),
        (F.col("LN_CURR_BAL").isNull(), "NULL_CURR_BAL"),
        (F.col("LN_ORIG_DT").isNotNull() &
         ~F.col("LN_ORIG_DT").rlike(r"^\d{2}/\d{2}/\d{4}$"), "MALFORMED_ORIG_DT"),
    ])

    # Log flagged records
    flagged = df_tagged.filter(F.col("_quality_flags").isNotNull())
    flagged_count = flagged.count()
    if flagged_count > 0:
        logger.warning(
            f"Found {flagged_count} records with quality issues in CDW_LN_ACCT. "
            "Records preserved — not dropped."
        )
        flagged.select("LN_ACCT_NBR", "_quality_flags").show(truncate=False)

    # Resolve foreign keys via lookup tables
    df_with_fks = resolve_foreign_keys(spark, df_tagged)

    # Apply column transformations per the mapping document
    transformed = df_with_fks.select(
        # Surrogate key
        F.monotonically_increasing_id().alias("loan_account_id"),

        # Natural key
        F.trim(F.col("LN_ACCT_NBR")).alias("account_number"),

        # Resolved foreign keys
        F.col("_resolved_borrower_id").alias("borrower_id"),
        F.col("_resolved_product_id").alias("product_id"),

        # Financial fields: remove commas, parse to decimal
        parse_amount_col("LN_ORIG_AMT", "original_amount"),
        parse_amount_col("LN_CURR_BAL", "current_balance"),
        parse_rate_col("LN_INT_RT", "interest_rate"),
        parse_int_col("LN_TERM_MOS", "term_months"),
        parse_amount_col("LN_PMT_AMT", "monthly_payment", precision=10, scale=2),

        # Date fields: parse MM/DD/YYYY → DATE
        parse_date_col("LN_ORIG_DT", "origination_date"),
        parse_date_col("LN_MAT_DT", "maturity_date"),
        parse_date_col("LN_1ST_PMT_DT", "first_payment_date"),
        parse_date_col("LN_NXT_PMT_DT", "next_payment_date"),

        # Status: expand abbreviation (ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE)
        expand_status_col("LN_STAT_CD", LOAN_STATUS_MAP, "status"),

        # Numeric fields
        parse_int_col("LN_DLQ_DAYS", "delinquency_days"),
        parse_amount_col("LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2),
        parse_percent_col("LN_LTV_PCT", "ltv_percent"),

        # Property fields: direct copy
        F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
        F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
        F.trim(F.col("PROP_ST_CD")).alias("property_state"),
        F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),

        # Property type: expand abbreviation
        expand_status_col("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
        parse_amount_col("PROP_APRS_VAL", "appraised_value"),

        # Audit timestamps: parse MM/DD/YYYY → TIMESTAMP
        parse_timestamp_col("LN_CRET_DT", "created_at"),
        parse_timestamp_col("LN_UPDT_DT", "updated_at"),

        # Note: BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 intentionally dropped
        # (denormalized fields — use borrower_id FK instead)
    )

    # Add ETL metadata
    transformed = add_etl_metadata(transformed, "CDW_LN_ACCT")

    logger.info(f"Transformation complete. Output row count: {transformed.count()}")
    return transformed


def write_target(df):
    """
    Write the transformed loan accounts DataFrame to the Delta Lake target table.
    Partitioned by status as defined in the DDL.
    """
    logger.info(f"Writing to {TARGET_TABLE} (mode={WRITE_MODE}), partitioned by status")
    (
        df.write
        .format("delta")
        .mode(WRITE_MODE)
        .option("mergeSchema", "true")
        .partitionBy("status")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info(f"Successfully wrote data to {TARGET_TABLE}")


def main():
    """Main entry point: read → transform → write for loan accounts ingestion."""
    spark = SparkSession.builder.appName("Ingest_CDW_LN_ACCT").getOrCreate()
    logger.info("=" * 70)
    logger.info("Starting loan account ingestion: CDW_LN_ACCT → loan_warehouse.loan_accounts")
    logger.info("=" * 70)

    try:
        source_df = read_source(spark)
        target_df = transform(spark, source_df)
        write_target(target_df)
        logger.info("Loan account ingestion completed successfully")
    except Exception as e:
        logger.error(f"Loan account ingestion FAILED: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
