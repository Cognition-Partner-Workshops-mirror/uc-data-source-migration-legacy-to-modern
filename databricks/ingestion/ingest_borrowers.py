"""
Ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master table (exported as CSV/Parquet), applies
type conversions and status code expansions per column_mappings.md, and
writes to the Delta Lake borrowers table.

Usage (Databricks notebook or spark-submit):
    %run ./common
    %run ./ingest_borrowers
    -- or --
    spark-submit ingest_borrowers.py --source /mnt/legacy/CDW_BORR_MSTR.csv
"""

import argparse
import sys

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    BORROWER_STATUS_MAP,
    expand_status_col,
    log_rejected_rows,
    logger,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
    read_legacy_csv,
    read_legacy_parquet,
    write_delta,
)

TARGET_TABLE = "loan_warehouse.borrowers"


def transform_borrowers(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Transform legacy CDW_BORR_MSTR records to modern borrowers schema.

    Returns:
        (valid_df, rejected_df) -- valid rows for insertion, rejected rows for logging.
    """
    logger.info("Starting borrower transformation. Source row count: %d", df.count())

    # ----- Column renaming (legacy cryptic -> modern readable) -----
    renamed = df.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        F.col("BORR_DOB_DT").alias("date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        F.col("BORR_CRDT_SCR").alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        F.col("BORR_ANN_INCM").alias("annual_income"),
        F.col("BORR_CRET_DT").alias("created_at"),
        F.col("BORR_UPDT_DT").alias("updated_at"),
        F.col("BORR_STAT_CD").alias("status"),
        # BORR_REC_TYP is intentionally dropped per column_mappings.md
    )

    # ----- Type conversions -----
    transformed = renamed.select(
        F.col("external_id"),
        F.col("first_name"),
        F.col("last_name"),
        F.col("middle_initial"),
        F.col("ssn_hash"),
        parse_date_col("date_of_birth"),
        F.col("address_line1"),
        F.col("address_line2"),
        F.col("city"),
        F.col("state"),
        F.col("zip_code"),
        F.col("phone"),
        F.col("email"),
        parse_int_col("credit_score"),
        F.col("employment_status"),
        parse_amount_col("annual_income"),
        parse_timestamp_col("created_at"),
        parse_timestamp_col("updated_at"),
        expand_status_col("status", BORROWER_STATUS_MAP, default="ACTIVE"),
    )

    # ----- Add audit columns -----
    transformed = transformed.withColumn("_ingestion_ts", F.current_timestamp())
    transformed = transformed.withColumn("_source_system", F.lit("CDW_BORR_MSTR"))

    # ----- Null validation: required fields -----
    valid = transformed.filter(
        F.col("external_id").isNotNull()
        & F.col("first_name").isNotNull()
        & F.col("last_name").isNotNull()
    )
    rejected = transformed.filter(
        F.col("external_id").isNull()
        | F.col("first_name").isNull()
        | F.col("last_name").isNull()
    )

    logger.info(
        "Borrower transformation complete. Valid: %d, Rejected: %d",
        valid.count(), rejected.count(),
    )
    return valid, rejected


def run(spark: SparkSession, source_path: str, source_format: str = "csv") -> None:
    """Execute the borrower ingestion pipeline."""
    if source_format == "parquet":
        raw_df = read_legacy_parquet(spark, source_path)
    else:
        raw_df = read_legacy_csv(spark, source_path)

    valid_df, rejected_df = transform_borrowers(raw_df)

    log_rejected_rows(rejected_df, "Missing required fields (external_id, first_name, last_name)", TARGET_TABLE)

    write_delta(valid_df, TARGET_TABLE, mode="overwrite", partition_cols=["state"])
    logger.info("Borrower ingestion complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_BORR_MSTR into Delta Lake borrowers table")
    parser.add_argument("--source", required=True, help="Path to legacy CDW_BORR_MSTR export (CSV or Parquet)")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_Borrowers").getOrCreate()
    try:
        run(spark, args.source, args.format)
    except Exception:
        logger.exception("Borrower ingestion failed")
        sys.exit(1)
    finally:
        spark.stop()
