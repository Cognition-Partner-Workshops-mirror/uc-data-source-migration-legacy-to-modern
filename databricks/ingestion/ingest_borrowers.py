"""
Ingest legacy CDW_BORR_MSTR into Delta Lake borrowers table.

Reads the legacy borrower master data (simulated as CSV/Parquet),
applies type conversions and status code expansion, and writes to
the loan_warehouse.borrowers Delta table.

Usage (Databricks notebook or job):
    %run ./transform_utils
    %run ./ingest_borrowers
    -- or --
    spark-submit ingest_borrowers.py --source /mnt/landing/cdw_borr_mstr.csv
"""

import sys
import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transform_utils import (
    BORROWER_STATUS_MAP,
    collect_parse_errors,
    drop_parse_error_columns,
    expand_status_column,
    parse_amount_column,
    parse_date_column,
    parse_int_column,
    parse_timestamp_column,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_borrowers")

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_borr_mstr"
DEFAULT_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.borrowers"


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    """Read the legacy CDW_BORR_MSTR source file."""
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(path)
    logger.info("Read %d rows from source %s (%s)", df.count(), path, fmt)
    return df


def transform_borrowers(df: DataFrame) -> DataFrame:
    """Apply all transformations to convert legacy borrower data to modern schema."""
    logger.info("Starting borrower transformations")

    # -- Date fields --------------------------------------------------------
    df = parse_date_column(df, "BORR_DOB_DT", "date_of_birth")
    df = parse_timestamp_column(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp_column(df, "BORR_UPDT_DT", "updated_at")

    # -- Numeric fields -----------------------------------------------------
    df = parse_int_column(df, "BORR_CRDT_SCR", "credit_score")
    df = parse_amount_column(df, "BORR_ANN_INCM", "annual_income")

    # -- Status expansion ---------------------------------------------------
    df = expand_status_column(df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)

    # -- Direct-copy renames ------------------------------------------------
    df = (
        df.withColumnRenamed("BORR_ID", "external_id")
          .withColumnRenamed("BORR_FST_NM", "first_name")
          .withColumnRenamed("BORR_LST_NM", "last_name")
          .withColumnRenamed("BORR_MID_INIT", "middle_initial")
          .withColumnRenamed("BORR_SSN_ENCR", "ssn_hash")
          .withColumnRenamed("BORR_ADDR_LN1", "address_line1")
          .withColumnRenamed("BORR_ADDR_LN2", "address_line2")
          .withColumnRenamed("BORR_CTY_NM", "city")
          .withColumnRenamed("BORR_ST_CD", "state")
          .withColumnRenamed("BORR_ZIP_CD", "zip_code")
          .withColumnRenamed("BORR_PH_NBR", "phone")
          .withColumnRenamed("BORR_EMAIL_ADDR", "email")
          .withColumnRenamed("BORR_EMP_STAT", "employment_status")
    )

    # -- Lineage metadata ---------------------------------------------------
    df = (
        df.withColumn("_migration_source", F.lit("CDW_BORR_MSTR"))
          .withColumn("_migrated_at", F.current_timestamp())
    )

    return df


def validate_and_log_errors(df: DataFrame) -> DataFrame:
    """Log parse errors, then strip internal error-flag columns."""
    error_summary = collect_parse_errors(df, "borrowers")
    error_count = error_summary.count()
    if error_count > 0:
        logger.warning("Borrower parse errors detected:")
        error_summary.show(truncate=False)
    else:
        logger.info("No parse errors in borrower data")
    return drop_parse_error_columns(df)


def select_target_columns(df: DataFrame) -> DataFrame:
    """Select and order columns matching the target Delta table schema."""
    return df.select(
        "external_id",
        "first_name",
        "last_name",
        "middle_initial",
        "ssn_hash",
        "date_of_birth",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "zip_code",
        "phone",
        "email",
        "credit_score",
        "employment_status",
        "annual_income",
        "status",
        "created_at",
        "updated_at",
        "_migration_source",
        "_migrated_at",
    )


def write_to_delta(df: DataFrame, mode: str = "overwrite") -> None:
    """Write the transformed DataFrame to the target Delta table."""
    record_count = df.count()
    logger.info("Writing %d borrower records to %s", record_count, TARGET_TABLE)
    (
        df.write
          .format("delta")
          .mode(mode)
          .option("mergeSchema", "true")
          .partitionBy("status")
          .saveAsTable(TARGET_TABLE)
    )
    logger.info("Successfully wrote %d records to %s", record_count, TARGET_TABLE)


def run(source_path: str = DEFAULT_SOURCE_PATH, source_format: str = DEFAULT_SOURCE_FORMAT) -> None:
    """End-to-end borrower ingestion pipeline."""
    spark = SparkSession.builder.appName("CDW_Borrower_Ingestion").getOrCreate()

    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform_borrowers(raw_df)
    clean_df = validate_and_log_errors(transformed_df)
    final_df = select_target_columns(clean_df)
    write_to_delta(final_df)

    logger.info("Borrower ingestion complete")


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE_PATH
    fmt = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SOURCE_FORMAT
    run(source_path=source, source_format=fmt)
