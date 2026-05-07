"""Ingest legacy CDW_BORR_MSTR into modern borrowers Delta table.

Expected source: CSV or Parquet file at the configured landing path with columns
matching the CDW_BORR_MSTR schema (all VARCHAR/string).

Usage (Databricks notebook):
    %run ./common
    %run ./ingest_borrowers
"""

import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    BORROWER_STATUS_MAP,
    drop_flag_columns,
    expand_status,
    log_parse_errors,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
)

logger = logging.getLogger("ingestion.borrowers")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Configuration — override these via Databricks widgets or job parameters
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_borr_mstr"
SOURCE_FORMAT = "csv"  # or "parquet"
TARGET_TABLE = "loan_warehouse.borrowers"


def read_source(spark: SparkSession, path: str = SOURCE_PATH, fmt: str = SOURCE_FORMAT) -> DataFrame:
    """Read the legacy borrower source file."""
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(path)


def transform(df: DataFrame) -> DataFrame:
    """Apply all column mappings and type conversions for borrowers."""
    # Rename columns to modern names (direct copies)
    df = (
        df
        .withColumnRenamed("BORR_ID", "external_id")
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

    # Date conversions
    df = parse_date_col(df, "BORR_DOB_DT", "date_of_birth")

    # Timestamp conversions
    df = parse_timestamp_col(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "BORR_UPDT_DT", "updated_at")

    # Numeric conversions
    df = parse_int_col(df, "BORR_CRDT_SCR", "credit_score")
    df = parse_amount_col(df, "BORR_ANN_INCM", "annual_income")

    # Status expansion
    df = expand_status(df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)

    # Drop legacy source columns that have been replaced
    legacy_cols_to_drop = [
        "BORR_DOB_DT",
        "BORR_CRET_DT",
        "BORR_UPDT_DT",
        "BORR_CRDT_SCR",
        "BORR_ANN_INCM",
        "BORR_STAT_CD",
        "BORR_REC_TYP",  # Dropped per mapping — not needed in modern schema
    ]
    df = df.drop(*legacy_cols_to_drop)

    return df


def write_target(df: DataFrame, table: str = TARGET_TABLE) -> None:
    """Write the transformed DataFrame to the Delta target table."""
    (
        df
        .write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(table)
    )


def run(spark: SparkSession) -> int:
    """Execute the borrower ingestion pipeline. Returns source row count."""
    logger.info("Reading legacy borrower data from %s", SOURCE_PATH)
    raw_df = read_source(spark)
    source_count = raw_df.count()
    logger.info("Source row count: %d", source_count)

    logger.info("Applying transformations")
    transformed_df = transform(raw_df)

    # Log any parse/mapping errors before dropping flag columns
    log_parse_errors(transformed_df, "borrowers", logger)
    clean_df = drop_flag_columns(transformed_df)

    logger.info("Writing to %s", TARGET_TABLE)
    write_target(clean_df)

    target_count = spark.table(TARGET_TABLE).count()
    logger.info("Target row count: %d", target_count)

    if source_count != target_count:
        logger.error(
            "Row count mismatch! source=%d target=%d", source_count, target_count
        )

    return source_count


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest_Borrowers").getOrCreate()
    run(spark)
