"""
Ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master file (CSV or Parquet), applies type
conversions and status expansion, and writes to the Delta Lake borrowers table.

Usage (Databricks notebook or spark-submit):
    spark-submit --master local[*] ingest_borrowers.py \
        --source /mnt/landing/cdw_borr_mstr.csv \
        --format csv \
        --target loan_catalog.loan_warehouse.borrowers
"""

import argparse
import logging
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from utils import (
    BORROWER_STATUS_MAP,
    expand_status_with_fallback,
    log_null_counts,
    parse_amount_expr,
    parse_date_expr,
    parse_int_expr,
    parse_timestamp_expr,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("cdw_migration.borrowers")


def read_source(spark: SparkSession, path: str, fmt: str):
    """Read the legacy borrower source file."""
    if fmt == "csv":
        return (
            spark.read.option("header", "true")
            .option("inferSchema", "false")
            .csv(path)
        )
    elif fmt == "parquet":
        return spark.read.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform(df):
    """Apply all column mappings and type transformations."""
    source_count = df.count()
    logger.info("Source row count: %d", source_count)

    transformed = df.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_date_expr("BORR_DOB_DT", "date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        parse_int_expr("BORR_CRDT_SCR", "credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount_expr("BORR_ANN_INCM", "annual_income"),
        expand_status_with_fallback("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),
        parse_timestamp_expr("BORR_CRET_DT", "created_at"),
        parse_timestamp_expr("BORR_UPDT_DT", "updated_at"),
        F.col("BORR_REC_TYP").alias("_legacy_record_type"),
        F.current_timestamp().alias("_ingestion_ts"),
    )

    # --- Null / malformed-value logging ---
    required_cols = ["external_id", "first_name", "last_name", "status"]
    log_null_counts(transformed, "borrowers", required_cols)

    # Flag rows that failed date parsing
    date_cols = ["date_of_birth", "created_at", "updated_at"]
    log_null_counts(transformed, "borrowers", date_cols)

    # Flag rows with null credit_score or annual_income (parse failures)
    numeric_cols = ["credit_score", "annual_income"]
    log_null_counts(transformed, "borrowers", numeric_cols)

    target_count = transformed.count()
    logger.info("Target row count: %d", target_count)
    if source_count != target_count:
        logger.error(
            "ROW COUNT MISMATCH: source=%d, target=%d. No records were dropped; "
            "investigate transformation logic.",
            source_count,
            target_count,
        )

    return transformed


def write_target(df, target_table: str, mode: str = "overwrite"):
    """Write the transformed DataFrame to the Delta Lake target table."""
    logger.info("Writing %d rows to %s (mode=%s)", df.count(), target_table, mode)
    df.write.format("delta").mode(mode).partitionBy("status").saveAsTable(target_table)
    logger.info("Write complete.")


def main():
    parser = argparse.ArgumentParser(description="Ingest CDW_BORR_MSTR into borrowers Delta table")
    parser.add_argument("--source", required=True, help="Path to legacy borrower source file")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    parser.add_argument("--target", default="loan_catalog.loan_warehouse.borrowers", help="Target Delta table")
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"], help="Write mode")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_Borrowers").getOrCreate()

    try:
        raw_df = read_source(spark, args.source, args.format)
        transformed_df = transform(raw_df)
        write_target(transformed_df, args.target, args.mode)
    except Exception:
        logger.exception("Borrower ingestion failed")
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
