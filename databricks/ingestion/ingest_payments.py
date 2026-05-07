"""
Ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment history table, converts types, expands payment
type and status codes, and writes to the Delta Lake payments table.

Usage:
    spark-submit ingest_payments.py --source /mnt/legacy/CDW_PMT_HIST.csv
"""

import argparse
import sys

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status_col,
    log_rejected_rows,
    logger,
    parse_amount_col,
    parse_date_col,
    parse_timestamp_col,
    read_legacy_csv,
    read_legacy_parquet,
    write_delta,
)

TARGET_TABLE = "loan_warehouse.payments"


def transform_payments(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Transform legacy CDW_PMT_HIST records to modern payments schema.

    Returns:
        (valid_df, rejected_df)
    """
    logger.info("Starting payment transformation. Source row count: %d", df.count())

    renamed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_number"),
        F.col("LN_ACCT_NBR").alias("loan_account_number"),
        F.col("PMT_DT").alias("payment_date"),
        F.col("PMT_AMT").alias("total_amount"),
        F.col("PMT_PRIN_AMT").alias("principal_amount"),
        F.col("PMT_INT_AMT").alias("interest_amount"),
        F.col("PMT_ESCROW_AMT").alias("escrow_amount"),
        F.col("PMT_LATE_FEE").alias("late_fee"),
        F.col("PMT_TYP_CD").alias("type"),
        F.col("PMT_STAT_CD").alias("status"),
        F.col("PMT_RECV_DT").alias("received_date"),
        F.col("PMT_PROC_DT").alias("processed_date"),
        F.col("PMT_CRET_DT").alias("created_at"),
        F.col("PMT_UPDT_DT").alias("updated_at"),
    )

    transformed = renamed.select(
        F.col("legacy_sequence_number"),
        F.col("loan_account_number"),
        parse_date_col("payment_date"),
        parse_amount_col("total_amount", precision=10, scale=2),
        parse_amount_col("principal_amount", precision=10, scale=2),
        parse_amount_col("interest_amount", precision=10, scale=2),
        parse_amount_col("escrow_amount", precision=10, scale=2),
        parse_amount_col("late_fee", precision=10, scale=2),
        expand_status_col("type", PAYMENT_TYPE_MAP, default="REGULAR"),
        expand_status_col("status", PAYMENT_STATUS_MAP, default="PENDING"),
        parse_date_col("received_date"),
        parse_date_col("processed_date"),
        parse_timestamp_col("created_at"),
        parse_timestamp_col("updated_at"),
    )

    # Derive payment_year for partitioning
    transformed = transformed.withColumn(
        "payment_year",
        F.year(F.col("payment_date")),
    )

    transformed = (
        transformed
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit("CDW_PMT_HIST"))
    )

    # Required-field validation
    valid = transformed.filter(
        F.col("loan_account_number").isNotNull()
        & F.col("payment_date").isNotNull()
        & F.col("total_amount").isNotNull()
        & F.col("type").isNotNull()
        & F.col("status").isNotNull()
    )
    rejected = transformed.filter(
        F.col("loan_account_number").isNull()
        | F.col("payment_date").isNull()
        | F.col("total_amount").isNull()
        | F.col("type").isNull()
        | F.col("status").isNull()
    )

    logger.info(
        "Payment transformation complete. Valid: %d, Rejected: %d",
        valid.count(), rejected.count(),
    )
    return valid, rejected


def run(spark: SparkSession, source_path: str, source_format: str = "csv") -> None:
    """Execute the payment ingestion pipeline."""
    if source_format == "parquet":
        raw_df = read_legacy_parquet(spark, source_path)
    else:
        raw_df = read_legacy_csv(spark, source_path)

    valid_df, rejected_df = transform_payments(raw_df)

    log_rejected_rows(
        rejected_df,
        "Missing required fields (loan_account_number, payment_date, total_amount, type, status)",
        TARGET_TABLE,
    )

    write_delta(valid_df, TARGET_TABLE, mode="overwrite", partition_cols=["payment_year"])
    logger.info("Payment ingestion complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_PMT_HIST into Delta Lake payments table")
    parser.add_argument("--source", required=True, help="Path to legacy CDW_PMT_HIST export (CSV or Parquet)")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_Payments").getOrCreate()
    try:
        run(spark, args.source, args.format)
    except Exception:
        logger.exception("Payment ingestion failed")
        sys.exit(1)
    finally:
        spark.stop()
