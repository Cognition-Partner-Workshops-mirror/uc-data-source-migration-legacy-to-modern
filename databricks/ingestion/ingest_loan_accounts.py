"""
Ingestion script: CDW_LN_ACCT -> loan_management.loan_accounts

Reads legacy loan account data from CSV/Parquet source files, applies
transformations per data/mappings/column_mappings.md, resolves foreign keys
to borrowers and loan_products tables, and writes to the modern Delta Lake
loan_accounts table.

Key transformations:
  - Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  - Resolve BORR_ID -> borrower_id FK via borrowers.external_id lookup
  - Resolve PROD_CD -> product_id FK via loan_products.code lookup
  - Parse all amount fields from comma-formatted strings to DECIMAL
  - Parse all date fields from MM/DD/YYYY strings to DATE
  - Expand loan status codes (ACT -> ACTIVE, CLO -> CLOSED, etc.)
  - Expand property type codes (SFR -> Single Family, etc.)
  - Derive origination_year partition column from origination_date
  - Handle nulls and malformed values with logging

Usage:
    spark-submit ingest_loan_accounts.py --source /mnt/landing/cdw_ln_acct.csv
"""

import argparse
import logging
import sys

from pyspark.sql import SparkSession, functions as F

from transformations import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    parse_rate_col,
    expand_status_col,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest_loan_accounts")

TARGET_TABLE = "loan_management.loan_accounts"
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_ln_acct"


def create_spark_session() -> SparkSession:
    """Create or retrieve the active SparkSession with Delta Lake support."""
    return (
        SparkSession.builder
        .appName("LoanMigration_IngestLoanAccounts")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .getOrCreate()
    )


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv"):
    """
    Read legacy loan account data from the source file.

    Args:
        spark: Active SparkSession.
        source_path: Path to the source file or directory.
        file_format: 'csv' or 'parquet'. Defaults to 'csv'.

    Returns:
        Raw DataFrame with all columns as strings.
    """
    logger.info(f"Reading source data from: {source_path} (format={file_format})")
    if file_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .csv(source_path)
        )
    else:
        df = spark.read.parquet(source_path)

    row_count = df.count()
    logger.info(f"Source row count: {row_count}")
    return df


def resolve_borrower_fk(spark: SparkSession, df):
    """
    Resolve legacy BORR_ID to modern borrower_id via borrowers.external_id lookup.

    Reads the already-ingested borrowers table and joins on external_id to get
    the surrogate key. Rows with unresolvable borrower IDs are logged but NOT
    dropped — they get null borrower_id for downstream quality flagging.

    Args:
        spark: Active SparkSession.
        df: Source DataFrame containing BORR_ID column.

    Returns:
        DataFrame with borrower_id column added and BORR_ID retained for audit.
    """
    logger.info("Resolving borrower foreign keys...")
    borrowers = spark.table("loan_management.borrowers").select(
        F.col("id").alias("borrower_id"),
        F.col("external_id"),
    )

    result = df.join(
        borrowers,
        df["BORR_ID"] == borrowers["external_id"],
        "left",
    ).drop("external_id")

    # Log unresolved borrower references
    unresolved = result.filter(F.col("borrower_id").isNull()).count()
    if unresolved > 0:
        logger.warning(
            f"Found {unresolved} loan accounts with unresolvable BORR_ID "
            f"(no matching borrower in borrowers table)"
        )

    return result


def resolve_product_fk(spark: SparkSession, df):
    """
    Resolve legacy PROD_CD to modern product_id via loan_products.code lookup.

    Reads the already-ingested loan_products table and joins on code to get
    the surrogate key. Unresolvable product codes are logged.

    Args:
        spark: Active SparkSession.
        df: Source DataFrame containing PROD_CD column.

    Returns:
        DataFrame with product_id column added.
    """
    logger.info("Resolving product foreign keys...")
    products = spark.table("loan_management.loan_products").select(
        F.col("id").alias("product_id"),
        F.col("code").alias("product_code"),
    )

    result = df.join(
        products,
        df["PROD_CD"] == products["product_code"],
        "left",
    ).drop("product_code")

    # Log unresolved product references
    unresolved = result.filter(F.col("product_id").isNull()).count()
    if unresolved > 0:
        logger.warning(
            f"Found {unresolved} loan accounts with unresolvable PROD_CD "
            f"(no matching product in loan_products table)"
        )

    return result


def transform_loan_accounts(spark: SparkSession, df):
    """
    Apply all transformations to convert CDW_LN_ACCT to modern loan_accounts.

    Steps:
      1. Resolve borrower and product foreign keys
      2. Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
      3. Parse amounts, dates, rates, and integer fields
      4. Expand status and property type codes
      5. Derive origination_year partition column

    Args:
        spark: Active SparkSession (needed for FK lookups).
        df: Raw source DataFrame with legacy column names.

    Returns:
        Transformed DataFrame ready for Delta Lake write.
    """
    logger.info("Applying loan account transformations...")

    # Step 1: Resolve foreign keys
    df = resolve_borrower_fk(spark, df)
    df = resolve_product_fk(spark, df)

    # Step 2-5: Select and transform columns
    transformed = df.select(
        # Natural key
        F.col("LN_ACCT_NBR").alias("account_number"),

        # Resolved FKs
        F.col("borrower_id"),
        F.col("product_id"),

        # Amount fields: comma-formatted strings -> DECIMAL
        parse_amount_col("LN_ORIG_AMT", "original_amount"),
        parse_amount_col("LN_CURR_BAL", "current_balance"),

        # Interest rate: string -> DECIMAL(5,3)
        parse_rate_col("LN_INT_RT", "interest_rate", 5, 3),

        # Term: string -> INT
        parse_int_col("LN_TERM_MOS", "term_months"),

        # Monthly payment: comma-formatted string -> DECIMAL(10,2)
        parse_amount_col("LN_PMT_AMT", "monthly_payment", 10, 2),

        # Date fields: MM/DD/YYYY strings -> DATE
        parse_date_col("LN_ORIG_DT", "origination_date"),
        parse_date_col("LN_MAT_DT", "maturity_date"),
        parse_date_col("LN_1ST_PMT_DT", "first_payment_date"),
        parse_date_col("LN_NXT_PMT_DT", "next_payment_date"),

        # Status expansion: ACT -> ACTIVE, CLO -> CLOSED, DFT -> DEFAULT, FRB -> FORBEARANCE
        expand_status_col("LN_STAT_CD", LOAN_STATUS_MAP, "status"),

        # Delinquency days: string -> INT
        parse_int_col("LN_DLQ_DAYS", "delinquency_days"),

        # Escrow balance: comma-formatted string -> DECIMAL(10,2)
        parse_amount_col("LN_ESCROW_BAL", "escrow_balance", 10, 2),

        # LTV: string -> DECIMAL(5,2)
        parse_rate_col("LN_LTV_PCT", "ltv_percent", 5, 2),

        # Property fields (direct copy with rename)
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),

        # Property type expansion: SFR -> Single Family, CND -> Condominium, etc.
        expand_status_col("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),

        # Appraised value: comma-formatted string -> DECIMAL(12,2)
        parse_amount_col("PROP_APRS_VAL", "appraised_value"),

        # Audit timestamps
        parse_timestamp_col("LN_CRET_DT", "created_at"),
        parse_timestamp_col("LN_UPDT_DT", "updated_at"),

        # NOTE: BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 intentionally dropped
        # (denormalized fields — use borrower_id FK instead)
    )

    # Derive origination_year partition column from origination_date
    transformed = transformed.withColumn(
        "origination_year",
        F.year(F.col("origination_date"))
    )

    # Log null checks on critical fields
    for col_name in ["account_number", "borrower_id", "product_id",
                     "original_amount", "origination_date"]:
        null_count = transformed.filter(F.col(col_name).isNull()).count()
        if null_count > 0:
            logger.warning(f"Found {null_count} rows with null {col_name}")

    return transformed


def write_to_delta(df, target_table: str, mode: str = "overwrite"):
    """
    Write transformed loan accounts to Delta Lake, partitioned by origination_year.

    Args:
        df: Transformed DataFrame.
        target_table: Fully qualified Delta table name.
        mode: Write mode.
    """
    output_count = df.count()
    logger.info(f"Writing {output_count} rows to {target_table} (mode={mode})")

    (
        df.write
        .format("delta")
        .mode(mode)
        .option("overwriteSchema", "true")
        .partitionBy("origination_year")
        .saveAsTable(target_table)
    )

    logger.info(f"Successfully wrote {output_count} rows to {target_table}")


def main():
    """Main entry point for the loan account ingestion pipeline."""
    parser = argparse.ArgumentParser(
        description="Ingest CDW_LN_ACCT to Delta Lake"
    )
    parser.add_argument(
        "--source", default=DEFAULT_SOURCE_PATH,
        help="Path to source CSV/Parquet file",
    )
    parser.add_argument(
        "--format", default="csv", choices=["csv", "parquet"],
        help="Source file format (default: csv)",
    )
    parser.add_argument(
        "--mode", default="overwrite", choices=["overwrite", "append"],
        help="Write mode (default: overwrite for initial migration)",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Starting loan account ingestion: CDW_LN_ACCT -> loan_accounts")
    logger.info("=" * 60)

    spark = create_spark_session()

    try:
        source_df = read_source(spark, args.source, args.format)
        transformed_df = transform_loan_accounts(spark, source_df)
        write_to_delta(transformed_df, TARGET_TABLE, args.mode)
        logger.info("Loan account ingestion completed successfully")
    except Exception as e:
        logger.error(f"Loan account ingestion FAILED: {str(e)}", exc_info=True)
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
