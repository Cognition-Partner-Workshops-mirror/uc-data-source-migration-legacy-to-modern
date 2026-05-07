"""
Ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads legacy payment history, applies type conversions, expands payment
type and status codes, resolves loan account FK, and writes to Delta Lake.

Requires loan_accounts table to be loaded first for FK resolution
(account_number -> loan_account_id).

Usage:
    spark-submit --master local[*] ingest_payments.py \
        --source-path /mnt/legacy/cdw_pmt_hist \
        --source-format csv \
        --target-table loan_warehouse.payments \
        --loan-table loan_warehouse.loan_accounts \
        --error-path /mnt/migration/errors/payments
"""

import argparse
import logging
import sys
from datetime import datetime

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status_col,
    parse_amount_col,
    parse_date_col,
    parse_timestamp_col,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_payments")


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.option("header", "true")
    if fmt == "csv":
        reader = reader.option("inferSchema", "false")
    return reader.format(fmt).load(path)


def resolve_loan_fk(spark: SparkSession, loan_table: str) -> DataFrame:
    """Load loan account lookup: account_number -> loan_account_id."""
    return spark.table(loan_table).select(
        F.col("loan_account_id"),
        F.col("account_number").alias("_ln_acct_nbr"),
    )


def transform(
    df: DataFrame,
    loan_lookup: DataFrame,
) -> tuple[DataFrame, DataFrame]:
    run_ts = datetime.utcnow().isoformat()

    transformed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_id"),
        F.col("LN_ACCT_NBR").alias("_ln_acct_nbr"),
        parse_date_col("PMT_DT").alias("payment_date"),
        parse_amount_col("PMT_AMT", 10, 2).alias("total_amount"),
        parse_amount_col("PMT_PRIN_AMT", 10, 2).alias("principal_amount"),
        parse_amount_col("PMT_INT_AMT", 10, 2).alias("interest_amount"),
        parse_amount_col("PMT_ESCROW_AMT", 10, 2).alias("escrow_amount"),
        parse_amount_col("PMT_LATE_FEE", 10, 2).alias("late_fee"),
        expand_status_col("PMT_TYP_CD", PAYMENT_TYPE_MAP).alias("type"),
        expand_status_col("PMT_STAT_CD", PAYMENT_STATUS_MAP).alias("status"),
        parse_date_col("PMT_RECV_DT").alias("received_date"),
        parse_date_col("PMT_PROC_DT").alias("processed_date"),
        parse_timestamp_col("PMT_CRET_DT").alias("created_at"),
        parse_timestamp_col("PMT_UPDT_DT").alias("updated_at"),
        F.lit("CDW_PMT_HIST").alias("_migration_source"),
        F.lit(run_ts).cast("timestamp").alias("_migrated_at"),
    )

    # Derive partition column
    transformed = transformed.withColumn(
        "payment_year", F.year(F.col("payment_date"))
    )

    # Resolve loan account FK
    transformed = transformed.join(loan_lookup, on="_ln_acct_nbr", how="left")
    transformed = transformed.drop("_ln_acct_nbr")

    # Validate required fields
    required_cols = ["loan_account_id", "payment_date", "total_amount", "type", "status"]
    error_condition = F.lit(False)
    for col_name in required_cols:
        error_condition = error_condition | F.col(col_name).isNull()

    error_df = transformed.filter(error_condition).withColumn(
        "_error_reason",
        F.concat_ws(
            "; ",
            *[F.when(F.col(c).isNull(), F.lit(f"{c} is NULL")) for c in required_cols],
        ),
    )
    good_df = transformed.filter(~error_condition)

    return good_df, error_df


def write_target(df: DataFrame, table: str) -> None:
    df.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(table)


def write_errors(df: DataFrame, path: str) -> None:
    if df.count() > 0:
        df.write.format("delta").mode("append").save(path)
        logger.warning("Wrote %d error records to %s", df.count(), path)
    else:
        logger.info("No error records to write.")


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest CDW_PMT_HIST -> payments")
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--target-table", default="loan_warehouse.payments")
    parser.add_argument("--loan-table", default="loan_warehouse.loan_accounts")
    parser.add_argument("--error-path", default="/mnt/migration/errors/payments")
    opts = parser.parse_args(args)

    spark = SparkSession.builder.appName("Ingest_Payments").getOrCreate()

    logger.info("Reading legacy payments from %s (%s)", opts.source_path, opts.source_format)
    source_df = read_source(spark, opts.source_path, opts.source_format)
    source_count = source_df.count()
    logger.info("Source row count: %d", source_count)

    loan_lookup = resolve_loan_fk(spark, opts.loan_table)

    good_df, error_df = transform(source_df, loan_lookup)
    good_count = good_df.count()
    error_count = error_df.count()
    logger.info("Transformed: %d good, %d errors", good_count, error_count)

    write_target(good_df, opts.target_table)
    write_errors(error_df, opts.error_path)

    logger.info(
        "Payments ingestion complete. Source=%d, Loaded=%d, Errors=%d",
        source_count,
        good_count,
        error_count,
    )

    if source_count != good_count + error_count:
        logger.error(
            "ROW COUNT MISMATCH: source=%d != good(%d) + error(%d)",
            source_count,
            good_count,
            error_count,
        )
        sys.exit(1)

    spark.stop()


if __name__ == "__main__":
    main()
