"""
Ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads payment history data from the CSV/Parquet landing zone, applies type
transformations, expands payment type and status codes, derives the
payment_year_month partition key, adds lineage metadata, and writes to
the payments Delta table.
"""

import argparse

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from transform_utils import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    add_error_summary,
    add_lineage_columns,
    expand_status,
    expand_status_flag,
    log_parse_errors,
    parse_amount,
    parse_amount_flag,
    parse_date,
    parse_date_flag,
    parse_timestamp,
    parse_timestamp_flag,
    strip_error_columns,
)

DEFAULT_INPUT = "/mnt/landing/cdw/CDW_PMT_HIST"
DEFAULT_OUTPUT = "loan_warehouse.payments"


def ingest_payments(
    spark: SparkSession,
    input_path: str = DEFAULT_INPUT,
    output_table: str = DEFAULT_OUTPUT,
) -> None:
    """Read, transform, and write payment data."""

    raw = spark.read.format("csv").option("header", "true").load(input_path)

    transformed = raw.select(
        F.col("PMT_SEQ_NBR").alias("payment_sequence"),
        F.col("LN_ACCT_NBR").alias("loan_account_number"),
        # Dates
        parse_date("PMT_DT", "payment_date"),
        parse_date_flag("PMT_DT"),
        # Amounts
        parse_amount("PMT_AMT", 10, 2, "total_amount"),
        parse_amount_flag("PMT_AMT"),
        parse_amount("PMT_PRIN_AMT", 10, 2, "principal_amount"),
        parse_amount_flag("PMT_PRIN_AMT"),
        parse_amount("PMT_INT_AMT", 10, 2, "interest_amount"),
        parse_amount_flag("PMT_INT_AMT"),
        parse_amount("PMT_ESCROW_AMT", 10, 2, "escrow_amount"),
        parse_amount_flag("PMT_ESCROW_AMT"),
        parse_amount("PMT_LATE_FEE", 10, 2, "late_fee"),
        parse_amount_flag("PMT_LATE_FEE"),
        # Type and status expansion
        expand_status("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        expand_status_flag("PMT_TYP_CD", PAYMENT_TYPE_MAP),
        expand_status("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
        expand_status_flag("PMT_STAT_CD", PAYMENT_STATUS_MAP),
        # More dates
        parse_date("PMT_RECV_DT", "received_date"),
        parse_date_flag("PMT_RECV_DT"),
        parse_date("PMT_PROC_DT", "processed_date"),
        parse_date_flag("PMT_PROC_DT"),
        # Timestamps
        parse_timestamp("PMT_CRET_DT", "created_at"),
        parse_timestamp_flag("PMT_CRET_DT"),
        parse_timestamp("PMT_UPDT_DT", "updated_at"),
        parse_timestamp_flag("PMT_UPDT_DT"),
    )

    # Derive partition key: YYYY-MM from payment_date
    transformed = transformed.withColumn(
        "payment_year_month",
        F.date_format(F.col("payment_date"), "yyyy-MM"),
    )

    transformed = add_error_summary(transformed)
    log_parse_errors(transformed, "payments")
    transformed = add_lineage_columns(transformed)
    transformed = strip_error_columns(transformed)

    transformed.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(output_table)

    print(f"[payments] Wrote {transformed.count()} rows to {output_table}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_PMT_HIST")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input path")
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help="Output Delta table"
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName(
        "CDW_Migration_Payments"
    ).getOrCreate()
    ingest_payments(spark, args.input, args.output)
    spark.stop()
