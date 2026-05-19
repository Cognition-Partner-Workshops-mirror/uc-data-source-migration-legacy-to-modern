"""
Ingestion script: CDW_BORR_MSTR -> loan_management.borrowers

Reads legacy borrower data from CSV/Parquet source files (simulating CDW extract),
applies all transformations defined in data/mappings/column_mappings.md, and writes
to the modern Delta Lake borrowers table.

Transformations applied:
  - Parse MM/DD/YYYY date strings to DATE / TIMESTAMP types
  - Parse comma-formatted annual income to DECIMAL
  - Parse credit score string to INT
  - Expand status abbreviations (ACT -> ACTIVE, INA -> INACTIVE)
  - Drop BORR_REC_TYP column (not needed in modern schema)
  - Add validation flags for parse-failure detection (no silent drops)

Usage (Databricks notebook or spark-submit):
    spark-submit ingest_borrowers.py --source /mnt/landing/cdw_borr_mstr.csv
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
    expand_status_col,
    add_validation_flags,
    BORROWER_STATUS_MAP,
)

# Configure logging to capture transformation issues
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest_borrowers")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TARGET_TABLE = "loan_management.borrowers"
# Default source path (override via --source argument)
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_borr_mstr"


def create_spark_session() -> SparkSession:
    """Create or retrieve the active SparkSession with Delta Lake support."""
    return (
        SparkSession.builder
        .appName("LoanMigration_IngestBorrowers")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .getOrCreate()
    )


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv"):
    """
    Read legacy borrower data from the source file.

    Supports CSV (with header) and Parquet formats. CSV is the default since
    the legacy CDW exports are typically flat-file extracts.

    Args:
        spark: Active SparkSession.
        source_path: Path to the source file or directory.
        file_format: 'csv' or 'parquet'. Defaults to 'csv'.

    Returns:
        Raw DataFrame with all columns as strings (matching legacy schema).
    """
    logger.info(f"Reading source data from: {source_path} (format={file_format})")
    if file_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")  # Keep everything as string
            .csv(source_path)
        )
    else:
        df = spark.read.parquet(source_path)

    row_count = df.count()
    logger.info(f"Source row count: {row_count}")
    return df


def transform_borrowers(df):
    """
    Apply all transformations to convert legacy CDW_BORR_MSTR to modern borrowers.

    Follows the mapping defined in data/mappings/column_mappings.md:
      - Direct copies: name fields, address, phone, email, employment status
      - Type conversions: dates, income, credit score
      - Code expansion: status abbreviation
      - Column drops: BORR_REC_TYP

    Args:
        df: Raw source DataFrame with legacy column names.

    Returns:
        Transformed DataFrame ready for Delta Lake write.
    """
    logger.info("Applying borrower transformations...")

    transformed = df.select(
        # Direct copy fields (legacy -> modern name mapping)
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),

        # Date parsing: MM/DD/YYYY string -> DATE
        parse_date_col("BORR_DOB_DT", "date_of_birth"),

        # Address fields (direct copy with rename)
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),

        # Contact fields (direct copy with rename)
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),

        # Numeric parsing: string -> INT
        parse_int_col("BORR_CRDT_SCR", "credit_score"),

        # Direct copy
        F.col("BORR_EMP_STAT").alias("employment_status"),

        # Amount parsing: comma-formatted string -> DECIMAL(12,2)
        parse_amount_col("BORR_ANN_INCM", "annual_income"),

        # Status expansion: ACT -> ACTIVE, INA -> INACTIVE
        expand_status_col("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),

        # Timestamp parsing for audit fields
        parse_timestamp_col("BORR_CRET_DT", "created_at"),
        parse_timestamp_col("BORR_UPDT_DT", "updated_at"),

        # NOTE: BORR_REC_TYP is intentionally dropped (not in modern schema)
    )

    # Log any null values in required fields for visibility
    null_first_name = transformed.filter(F.col("first_name").isNull()).count()
    null_last_name = transformed.filter(F.col("last_name").isNull()).count()
    null_external_id = transformed.filter(F.col("external_id").isNull()).count()

    if null_first_name > 0:
        logger.warning(f"Found {null_first_name} rows with null first_name")
    if null_last_name > 0:
        logger.warning(f"Found {null_last_name} rows with null last_name")
    if null_external_id > 0:
        logger.warning(f"Found {null_external_id} rows with null external_id")

    # Add validation flags for parse-failure detection
    transformed = add_validation_flags(
        # Re-join source columns temporarily for validation
        df.select("BORR_DOB_DT", "BORR_CRET_DT", "BORR_UPDT_DT",
                  "BORR_ANN_INCM", "BORR_CRDT_SCR")
        .withColumn("_row_idx", F.monotonically_increasing_id())
        .join(
            transformed.withColumn("_row_idx", F.monotonically_increasing_id()),
            "_row_idx"
        ),
        date_cols=[
            ("BORR_DOB_DT", "date_of_birth"),
            ("BORR_CRET_DT", "created_at"),
            ("BORR_UPDT_DT", "updated_at"),
        ],
        amount_cols=[
            ("BORR_ANN_INCM", "annual_income"),
        ],
    )

    # Count and log validation failures (rows where source was non-null but parse failed)
    for flag_col in [c for c in transformed.columns if c.startswith("_is_valid_")]:
        failures = transformed.filter(~F.col(flag_col)).count()
        if failures > 0:
            logger.warning(f"Validation flag {flag_col}: {failures} parse failures")

    # Drop temporary columns before final output
    final_cols = [
        "external_id", "first_name", "last_name", "middle_initial", "ssn_hash",
        "date_of_birth", "address_line1", "address_line2", "city", "state",
        "zip_code", "phone", "email", "credit_score", "employment_status",
        "annual_income", "status", "created_at", "updated_at",
    ]
    return transformed.select(*final_cols)


def write_to_delta(df, target_table: str, mode: str = "overwrite"):
    """
    Write the transformed DataFrame to the target Delta Lake table.

    Uses overwrite mode for initial migration; switch to append/merge
    for incremental loads.

    Args:
        df: Transformed DataFrame to write.
        target_table: Fully qualified Delta table name.
        mode: Write mode ('overwrite' for initial, 'append' for incremental).
    """
    output_count = df.count()
    logger.info(f"Writing {output_count} rows to {target_table} (mode={mode})")

    (
        df.write
        .format("delta")
        .mode(mode)
        .option("overwriteSchema", "true")
        .partitionBy("status")
        .saveAsTable(target_table)
    )

    logger.info(f"Successfully wrote {output_count} rows to {target_table}")


def main():
    """Main entry point for the borrower ingestion pipeline."""
    parser = argparse.ArgumentParser(description="Ingest CDW_BORR_MSTR to Delta Lake")
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
    logger.info("Starting borrower ingestion: CDW_BORR_MSTR -> borrowers")
    logger.info("=" * 60)

    spark = create_spark_session()

    try:
        # Read source data
        source_df = read_source(spark, args.source, args.format)

        # Apply transformations
        transformed_df = transform_borrowers(source_df)

        # Write to Delta Lake
        write_to_delta(transformed_df, TARGET_TABLE, args.mode)

        logger.info("Borrower ingestion completed successfully")

    except Exception as e:
        logger.error(f"Borrower ingestion FAILED: {str(e)}", exc_info=True)
        sys.exit(1)

    finally:
        spark.stop()


if __name__ == "__main__":
    main()
