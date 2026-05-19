"""
Ingestion script: CDW_LN_PROD -> loan_management.loan_products

Reads legacy loan product data from CSV/Parquet source files, applies
transformations per data/mappings/column_mappings.md, and writes to
the modern Delta Lake loan_products table.

Transformations applied:
  - Parse term months from string to INT
  - Parse amount bounds from comma-formatted strings to DECIMAL
  - Convert product status code to boolean (ACT -> true, INA -> false)
  - Parse date strings (MM/DD/YYYY) to DATE type
  - Direct copy of code, name, type, rate_type fields

Usage:
    spark-submit ingest_loan_products.py --source /mnt/landing/cdw_ln_prod.csv
"""

import argparse
import logging
import sys

from pyspark.sql import SparkSession, functions as F

from transformations import (
    parse_date_col,
    parse_amount_col,
    parse_int_col,
    expand_product_status_col,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest_loan_products")

TARGET_TABLE = "loan_management.loan_products"
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_ln_prod"


def create_spark_session() -> SparkSession:
    """Create or retrieve the active SparkSession with Delta Lake support."""
    return (
        SparkSession.builder
        .appName("LoanMigration_IngestLoanProducts")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .getOrCreate()
    )


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv"):
    """
    Read legacy loan product data from the source file.

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


def transform_loan_products(df):
    """
    Apply all transformations to convert CDW_LN_PROD to modern loan_products.

    Mapping from data/mappings/column_mappings.md:
      - PROD_CD -> code (direct copy)
      - PROD_DESC_TXT -> name (direct copy)
      - PROD_TYP_CD -> type (direct copy)
      - PROD_TERM_MOS -> term_months (string -> INT)
      - PROD_RT_TYP -> rate_type (direct copy)
      - PROD_MIN_AMT -> min_amount (comma string -> DECIMAL)
      - PROD_MAX_AMT -> max_amount (comma string -> DECIMAL)
      - PROD_STAT_CD -> is_active (ACT -> true, INA -> false)
      - PROD_EFF_DT -> effective_date (MM/DD/YYYY -> DATE)
      - PROD_EXP_DT -> expiration_date (MM/DD/YYYY -> DATE)

    Args:
        df: Raw source DataFrame with legacy column names.

    Returns:
        Transformed DataFrame ready for Delta Lake write.
    """
    logger.info("Applying loan product transformations...")

    transformed = df.select(
        # Direct copy fields
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),

        # Numeric parsing: string -> INT
        parse_int_col("PROD_TERM_MOS", "term_months"),

        # Direct copy
        F.col("PROD_RT_TYP").alias("rate_type"),

        # Amount parsing: comma-formatted string -> DECIMAL(12,2)
        parse_amount_col("PROD_MIN_AMT", "min_amount"),
        parse_amount_col("PROD_MAX_AMT", "max_amount"),

        # Status to boolean: ACT -> true, INA -> false
        expand_product_status_col("PROD_STAT_CD", "is_active"),

        # Date parsing: MM/DD/YYYY -> DATE
        parse_date_col("PROD_EFF_DT", "effective_date"),
        parse_date_col("PROD_EXP_DT", "expiration_date"),
    )

    # Log null checks on required fields
    null_code = transformed.filter(F.col("code").isNull()).count()
    null_name = transformed.filter(F.col("name").isNull()).count()
    if null_code > 0:
        logger.warning(f"Found {null_code} rows with null product code")
    if null_name > 0:
        logger.warning(f"Found {null_name} rows with null product name")

    return transformed


def write_to_delta(df, target_table: str, mode: str = "overwrite"):
    """
    Write transformed loan products to Delta Lake.

    No partitioning for this small reference table.

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
        .saveAsTable(target_table)
    )

    logger.info(f"Successfully wrote {output_count} rows to {target_table}")


def main():
    """Main entry point for the loan product ingestion pipeline."""
    parser = argparse.ArgumentParser(
        description="Ingest CDW_LN_PROD to Delta Lake"
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
    logger.info("Starting loan product ingestion: CDW_LN_PROD -> loan_products")
    logger.info("=" * 60)

    spark = create_spark_session()

    try:
        source_df = read_source(spark, args.source, args.format)
        transformed_df = transform_loan_products(source_df)
        write_to_delta(transformed_df, TARGET_TABLE, args.mode)
        logger.info("Loan product ingestion completed successfully")
    except Exception as e:
        logger.error(f"Loan product ingestion FAILED: {str(e)}", exc_info=True)
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
