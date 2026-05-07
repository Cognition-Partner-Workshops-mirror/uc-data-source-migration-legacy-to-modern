"""
Ingest legacy CDW_PMT_HIST into Delta Lake payments table.

Reads payment history records, parses amounts and dates from VARCHAR
strings, expands payment type and status codes, derives the
payment_year_month partition key, and writes to loan_warehouse.payments.

Usage:
    spark-submit ingest_payments.py [--source /mnt/landing/cdw_pmt_hist.csv]
"""

import sys
import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transform_utils import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    collect_parse_errors,
    drop_parse_error_columns,
    expand_status_column,
    parse_amount_column,
    parse_date_column,
    parse_timestamp_column,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_payments")

DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_pmt_hist"
DEFAULT_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(path)
    logger.info("Read %d rows from source %s (%s)", df.count(), path, fmt)
    return df


def transform_payments(df: DataFrame) -> DataFrame:
    """Apply all transformations for CDW_PMT_HIST -> payments."""
    logger.info("Starting payment transformations")

    # -- Date fields --------------------------------------------------------
    df = parse_date_column(df, "PMT_DT", "payment_date")
    df = parse_date_column(df, "PMT_RECV_DT", "received_date")
    df = parse_date_column(df, "PMT_PROC_DT", "processed_date")
    df = parse_timestamp_column(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp_column(df, "PMT_UPDT_DT", "updated_at")

    # -- Amount fields ------------------------------------------------------
    df = parse_amount_column(df, "PMT_AMT", "total_amount", precision=10, scale=2)
    df = parse_amount_column(df, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
    df = parse_amount_column(df, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
    df = parse_amount_column(df, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
    df = parse_amount_column(df, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)

    # -- Code expansion -----------------------------------------------------
    df = expand_status_column(df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)
    df = expand_status_column(df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # -- Direct-copy renames ------------------------------------------------
    df = (
        df.withColumnRenamed("PMT_SEQ_NBR", "legacy_payment_id")
          .withColumnRenamed("LN_ACCT_NBR", "loan_account_number")
    )

    # -- Derived partition key (YYYY-MM) ------------------------------------
    df = df.withColumn(
        "payment_year_month",
        F.date_format(F.col("payment_date"), "yyyy-MM"),
    )

    # -- Lineage metadata ---------------------------------------------------
    df = (
        df.withColumn("_migration_source", F.lit("CDW_PMT_HIST"))
          .withColumn("_migrated_at", F.current_timestamp())
    )

    return df


def validate_and_log_errors(df: DataFrame) -> DataFrame:
    error_summary = collect_parse_errors(df, "payments")
    if error_summary.count() > 0:
        logger.warning("Payment parse errors detected:")
        error_summary.show(truncate=False)
    else:
        logger.info("No parse errors in payment data")
    return drop_parse_error_columns(df)


def select_target_columns(df: DataFrame) -> DataFrame:
    return df.select(
        "legacy_payment_id",
        "loan_account_number",
        "payment_date",
        "total_amount",
        "principal_amount",
        "interest_amount",
        "escrow_amount",
        "late_fee",
        "type",
        "status",
        "received_date",
        "processed_date",
        "created_at",
        "updated_at",
        "payment_year_month",
        "_migration_source",
        "_migrated_at",
    )


def write_to_delta(df: DataFrame, mode: str = "overwrite") -> None:
    record_count = df.count()
    logger.info("Writing %d payment records to %s", record_count, TARGET_TABLE)
    (
        df.write
          .format("delta")
          .mode(mode)
          .option("mergeSchema", "true")
          .partitionBy("payment_year_month")
          .saveAsTable(TARGET_TABLE)
    )
    logger.info("Successfully wrote %d records to %s", record_count, TARGET_TABLE)


def run(source_path: str = DEFAULT_SOURCE_PATH, source_format: str = DEFAULT_SOURCE_FORMAT) -> None:
    spark = SparkSession.builder.appName("CDW_Payment_Ingestion").getOrCreate()

    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform_payments(raw_df)
    clean_df = validate_and_log_errors(transformed_df)
    final_df = select_target_columns(clean_df)
    write_to_delta(final_df)

    logger.info("Payment ingestion complete")


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE_PATH
    fmt = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SOURCE_FORMAT
    run(source_path=source, source_format=fmt)
