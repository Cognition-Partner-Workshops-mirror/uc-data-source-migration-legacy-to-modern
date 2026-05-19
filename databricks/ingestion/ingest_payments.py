"""
Ingestion script: CDW_PMT_HIST -> loan_management.payments

Reads legacy payment history data from CSV/Parquet source files, applies
transformations per data/mappings/column_mappings.md, resolves loan account
foreign keys, and writes to the modern Delta Lake payments table.

Key transformations:
  - Resolve LN_ACCT_NBR -> loan_account_id FK via loan_accounts.account_number
  - Preserve PMT_SEQ_NBR as legacy_payment_id for audit traceability
  - Parse all amount fields from comma-formatted strings to DECIMAL
  - Parse all date fields from MM/DD/YYYY strings to DATE/TIMESTAMP
  - Expand payment type codes (REG -> REGULAR, EXT -> EXTRA, etc.)
  - Expand payment status codes (PST -> POSTED, REV -> REVERSED, etc.)
  - Derive payment_year partition column from payment_date
  - Handle nulls and malformed values with logging

Usage:
    spark-submit ingest_payments.py --source /mnt/landing/cdw_pmt_hist.csv
"""

import argparse
import logging
import sys

from pyspark.sql import SparkSession, functions as F

from transformations import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    expand_status_col,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest_payments")

TARGET_TABLE = "loan_management.payments"
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_pmt_hist"


def create_spark_session() -> SparkSession:
    """Create or retrieve the active SparkSession with Delta Lake support."""
    return (
        SparkSession.builder
        .appName("LoanMigration_IngestPayments")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .getOrCreate()
    )


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv"):
    """
    Read legacy payment history data from the source file.

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


def resolve_loan_account_fk(spark: SparkSession, df):
    """
    Resolve legacy LN_ACCT_NBR to modern loan_account_id via account_number lookup.

    Reads the already-ingested loan_accounts table and joins on account_number
    to get the surrogate key. Unresolvable references are logged.

    Args:
        spark: Active SparkSession.
        df: Source DataFrame containing LN_ACCT_NBR column.

    Returns:
        DataFrame with loan_account_id column added.
    """
    logger.info("Resolving loan account foreign keys...")
    loan_accounts = spark.table("loan_management.loan_accounts").select(
        F.col("id").alias("loan_account_id"),
        F.col("account_number"),
    )

    result = df.join(
        loan_accounts,
        df["LN_ACCT_NBR"] == loan_accounts["account_number"],
        "left",
    ).drop("account_number")

    # Log unresolved loan account references
    unresolved = result.filter(F.col("loan_account_id").isNull()).count()
    if unresolved > 0:
        logger.warning(
            f"Found {unresolved} payments with unresolvable LN_ACCT_NBR "
            f"(no matching account in loan_accounts table)"
        )

    return result


def transform_payments(spark: SparkSession, df):
    """
    Apply all transformations to convert CDW_PMT_HIST to modern payments.

    Steps:
      1. Resolve loan account foreign key
      2. Preserve legacy payment ID for audit trail
      3. Parse all amount and date fields
      4. Expand type and status codes
      5. Derive payment_year partition column

    Args:
        spark: Active SparkSession (needed for FK lookup).
        df: Raw source DataFrame with legacy column names.

    Returns:
        Transformed DataFrame ready for Delta Lake write.
    """
    logger.info("Applying payment transformations...")

    # Step 1: Resolve loan account FK
    df = resolve_loan_account_fk(spark, df)

    # Step 2-5: Select and transform columns
    transformed = df.select(
        # Preserve legacy payment ID for audit traceability
        F.col("PMT_SEQ_NBR").alias("legacy_payment_id"),

        # Resolved FK
        F.col("loan_account_id"),

        # Payment date: MM/DD/YYYY -> DATE
        parse_date_col("PMT_DT", "payment_date"),

        # Amount fields: comma-formatted strings -> DECIMAL(10,2)
        parse_amount_col("PMT_AMT", "total_amount", 10, 2),
        parse_amount_col("PMT_PRIN_AMT", "principal_amount", 10, 2),
        parse_amount_col("PMT_INT_AMT", "interest_amount", 10, 2),
        parse_amount_col("PMT_ESCROW_AMT", "escrow_amount", 10, 2),
        parse_amount_col("PMT_LATE_FEE", "late_fee", 10, 2),

        # Payment type expansion: REG -> REGULAR, EXT -> EXTRA, etc.
        expand_status_col("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),

        # Payment status expansion: PST -> POSTED, REV -> REVERSED, etc.
        expand_status_col("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),

        # Processing dates: MM/DD/YYYY -> DATE
        parse_date_col("PMT_RECV_DT", "received_date"),
        parse_date_col("PMT_PROC_DT", "processed_date"),

        # Audit timestamps
        parse_timestamp_col("PMT_CRET_DT", "created_at"),
        parse_timestamp_col("PMT_UPDT_DT", "updated_at"),
    )

    # Derive payment_year partition column from payment_date
    transformed = transformed.withColumn(
        "payment_year",
        F.year(F.col("payment_date"))
    )

    # Log null checks on critical fields
    for col_name in ["loan_account_id", "payment_date", "total_amount", "type", "status"]:
        null_count = transformed.filter(F.col(col_name).isNull()).count()
        if null_count > 0:
            logger.warning(f"Found {null_count} rows with null {col_name}")

    return transformed


def write_to_delta(df, target_table: str, mode: str = "overwrite"):
    """
    Write transformed payments to Delta Lake, partitioned by payment_year.

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
        .partitionBy("payment_year")
        .saveAsTable(target_table)
    )

    logger.info(f"Successfully wrote {output_count} rows to {target_table}")


def main():
    """Main entry point for the payment ingestion pipeline."""
    parser = argparse.ArgumentParser(
        description="Ingest CDW_PMT_HIST to Delta Lake"
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
    logger.info("Starting payment ingestion: CDW_PMT_HIST -> payments")
    logger.info("=" * 60)

    spark = create_spark_session()

    try:
        source_df = read_source(spark, args.source, args.format)
        transformed_df = transform_payments(spark, source_df)
        write_to_delta(transformed_df, TARGET_TABLE, args.mode)
        logger.info("Payment ingestion completed successfully")
    except Exception as e:
        logger.error(f"Payment ingestion FAILED: {str(e)}", exc_info=True)
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
