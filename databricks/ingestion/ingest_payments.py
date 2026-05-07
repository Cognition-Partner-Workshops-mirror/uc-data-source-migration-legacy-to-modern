"""
Ingest CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment history table, resolves the loan_account FK,
expands type/status codes, and writes the payments fact table to Delta.

Execution order: run AFTER ingest_loan_accounts.py.

Usage:
    spark-submit ingest_payments.py --source /mnt/landing/cdw_pmt_hist --format csv
"""

import logging
from argparse import ArgumentParser

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status_code_preserving,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_timestamp,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ingest_payments")

TARGET_TABLE = "loan_warehouse.payments"


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def resolve_loan_account_ids(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join with loan_accounts Delta table to resolve LN_ACCT_NBR -> loan_account_id."""
    accounts = spark.read.table("loan_warehouse.loan_accounts").select(
        F.col("loan_account_id"), F.col("account_number")
    )
    joined = df.join(
        accounts, df["LN_ACCT_NBR"] == accounts["account_number"], "left"
    )

    unresolved = joined.filter(F.col("loan_account_id").isNull())
    unresolved_count = unresolved.count()
    if unresolved_count > 0:
        logger.warning(
            "Found %d payment rows with unresolved LN_ACCT_NBR (no matching loan account).",
            unresolved_count,
        )
        unresolved.select("PMT_SEQ_NBR", "LN_ACCT_NBR").show(truncate=False)

    return joined


def transform(spark: SparkSession, df: DataFrame) -> tuple:
    source_count = df.count()
    logger.info("Source CDW_PMT_HIST row count: %d", source_count)

    df = resolve_loan_account_ids(spark, df)

    transformed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),
        F.col("loan_account_id"),
        parse_legacy_date("PMT_DT").alias("payment_date"),
        parse_legacy_amount("PMT_AMT", precision=10, scale=2).alias("total_amount"),
        parse_legacy_amount("PMT_PRIN_AMT", precision=10, scale=2).alias(
            "principal_amount"
        ),
        parse_legacy_amount("PMT_INT_AMT", precision=10, scale=2).alias(
            "interest_amount"
        ),
        parse_legacy_amount("PMT_ESCROW_AMT", precision=10, scale=2).alias(
            "escrow_amount"
        ),
        parse_legacy_amount("PMT_LATE_FEE", precision=10, scale=2).alias("late_fee"),
        expand_status_code_preserving("PMT_TYP_CD", PAYMENT_TYPE_MAP).alias("type"),
        expand_status_code_preserving("PMT_STAT_CD", PAYMENT_STATUS_MAP).alias("status"),
        parse_legacy_date("PMT_RECV_DT").alias("received_date"),
        parse_legacy_date("PMT_PROC_DT").alias("processed_date"),
        parse_legacy_timestamp("PMT_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("PMT_UPDT_DT").alias("updated_at"),
        F.current_timestamp().alias("_ingestion_ts"),
    )

    # Quality: required fields
    null_required = transformed.filter(
        F.col("legacy_sequence_nbr").isNull()
        | F.col("loan_account_id").isNull()
        | F.col("payment_date").isNull()
        | F.col("total_amount").isNull()
    )
    null_count = null_required.count()
    if null_count > 0:
        logger.warning(
            "Found %d payment rows with NULL required fields. Quarantining.",
            null_count,
        )

    good = transformed.filter(
        F.col("legacy_sequence_nbr").isNotNull()
        & F.col("loan_account_id").isNotNull()
        & F.col("payment_date").isNotNull()
        & F.col("total_amount").isNotNull()
    )
    quarantine = transformed.filter(
        F.col("legacy_sequence_nbr").isNull()
        | F.col("loan_account_id").isNull()
        | F.col("payment_date").isNull()
        | F.col("total_amount").isNull()
    )

    logger.info(
        "Transform complete: %d good rows, %d quarantined (source: %d)",
        good.count(),
        quarantine.count(),
        source_count,
    )
    return good, quarantine


def write_target(good: DataFrame, quarantine: DataFrame, quarantine_path: str) -> None:
    good.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)
    logger.info("Wrote %d rows to %s", good.count(), TARGET_TABLE)

    if quarantine.count() > 0:
        quarantine.write.format("delta").mode("overwrite").save(quarantine_path)
        logger.info("Wrote %d quarantined rows to %s", quarantine.count(), quarantine_path)


def main(source_path: str, source_format: str, quarantine_path: str) -> None:
    spark = SparkSession.builder.appName("CDW_PMT_HIST_Ingestion").getOrCreate()

    logger.info("Reading source from %s (format=%s)", source_path, source_format)
    raw = read_source(spark, source_path, source_format)

    good, quarantine = transform(spark, raw)
    write_target(good, quarantine, quarantine_path)
    logger.info("Payment ingestion complete.")


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Ingest CDW_PMT_HIST into payments Delta table"
    )
    parser.add_argument("--source", required=True, help="Path to source data")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument(
        "--quarantine",
        default="/mnt/quarantine/payments",
        help="Path for quarantined records",
    )
    args = parser.parse_args()
    main(args.source, args.format, args.quarantine)
