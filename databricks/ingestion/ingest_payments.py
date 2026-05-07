"""
Ingestion script: CDW_PMT_HIST → loan_warehouse.payments

Reads the legacy payment history extract, resolves loan account foreign keys,
expands payment type and status codes, and converts amount/date strings.

Prerequisite: loan_accounts must be ingested first.

Usage:
    spark-submit ingest_payments.py --source /mnt/landing/cdw_pmt_hist/
"""

import argparse
import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status_code,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_timestamp,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_payments")

TARGET_TABLE = "loan_warehouse.payments"


def read_source(spark: SparkSession, source_path: str) -> DataFrame:
    """Read the legacy payment history extract."""
    if source_path.endswith(".parquet") or source_path.endswith("/parquet"):
        return spark.read.parquet(source_path)
    return spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)


def resolve_loan_account_keys(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join against loan_accounts to resolve loan_account_key from account_number."""
    accounts = spark.table("loan_warehouse.loan_accounts").select(
        F.col("loan_account_key"),
        F.col("account_number").alias("_acct_number"),
    )
    joined = df.join(accounts, df["LN_ACCT_NBR"] == accounts["_acct_number"], "left")

    unmatched = joined.filter(F.col("loan_account_key").isNull()).count()
    if unmatched > 0:
        logger.error("Payments with no matching loan account: %d", unmatched)
        unmatched_rows = (
            joined.filter(F.col("loan_account_key").isNull())
            .select("PMT_SEQ_NBR", "LN_ACCT_NBR")
            .collect()
        )
        for row in unmatched_rows:
            logger.error(
                "  Unmatched: payment=%s, loan_account=%s",
                row["PMT_SEQ_NBR"], row["LN_ACCT_NBR"],
            )

    return joined


def transform(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Apply all column mappings, FK resolution, and type conversions."""
    source_count = df.count()
    logger.info("Source CDW_PMT_HIST row count: %d", source_count)

    df = resolve_loan_account_keys(spark, df)

    transformed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_id"),
        F.col("loan_account_key"),
        parse_legacy_date("PMT_DT").alias("payment_date"),
        parse_legacy_amount("PMT_AMT", 10, 2).alias("total_amount"),
        parse_legacy_amount("PMT_PRIN_AMT", 10, 2).alias("principal_amount"),
        parse_legacy_amount("PMT_INT_AMT", 10, 2).alias("interest_amount"),
        parse_legacy_amount("PMT_ESCROW_AMT", 10, 2).alias("escrow_amount"),
        parse_legacy_amount("PMT_LATE_FEE", 10, 2).alias("late_fee"),
        expand_status_code("PMT_TYP_CD", PAYMENT_TYPE_MAP).alias("type"),
        expand_status_code("PMT_STAT_CD", PAYMENT_STATUS_MAP).alias("status"),
        parse_legacy_date("PMT_RECV_DT").alias("received_date"),
        parse_legacy_date("PMT_PROC_DT").alias("processed_date"),
        parse_legacy_timestamp("PMT_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("PMT_UPDT_DT").alias("updated_at"),
        F.lit("CDW_PMT_HIST").alias("_migration_source"),
        F.current_timestamp().alias("_migrated_at"),
    )

    # Log null required fields
    for col_name in ["loan_account_key", "payment_date", "total_amount", "type", "status"]:
        null_count = transformed.filter(F.col(col_name).isNull()).count()
        if null_count > 0:
            logger.warning("Records with NULL %s: %d", col_name, null_count)

    # Validate payment component breakdown
    bad_breakdown = transformed.filter(
        (F.col("principal_amount") + F.col("interest_amount") +
         F.coalesce(F.col("escrow_amount"), F.lit(0)) +
         F.coalesce(F.col("late_fee"), F.lit(0)))
        != F.col("total_amount")
    ).count()
    if bad_breakdown > 0:
        logger.warning(
            "Payments where components don't sum to total: %d (may be rounding)",
            bad_breakdown,
        )

    target_count = transformed.count()
    logger.info("Transformed row count: %d", target_count)
    if source_count != target_count:
        logger.error(
            "ROW COUNT MISMATCH: source=%d, transformed=%d", source_count, target_count
        )

    return transformed


def write_target(df: DataFrame) -> None:
    """Write the transformed payments to Delta Lake."""
    df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)
    logger.info("Successfully wrote %d rows to %s", df.count(), TARGET_TABLE)


def main(source_path: str) -> None:
    spark = SparkSession.builder.appName("Ingest_CDW_PMT_HIST").getOrCreate()
    try:
        raw_df = read_source(spark, source_path)
        transformed_df = transform(spark, raw_df)
        write_target(transformed_df)
    except Exception:
        logger.exception("Payment ingestion failed")
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_PMT_HIST to Delta Lake")
    parser.add_argument("--source", required=True, help="Path to legacy payment history CSV/Parquet")
    args = parser.parse_args()
    main(args.source)
