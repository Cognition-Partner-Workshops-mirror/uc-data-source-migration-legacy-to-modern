"""
Ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment history file, applies all type conversions,
expands payment type and status codes, resolves loan_account FK, and
writes to the Delta Lake payments table.

Usage:
    spark-submit --master local[*] ingest_payments.py \
        --source /mnt/landing/cdw_pmt_hist.csv \
        --format csv \
        --target loan_catalog.loan_warehouse.payments \
        --loans-table loan_catalog.loan_warehouse.loan_accounts
"""

import argparse
import logging
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from utils import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status_with_fallback,
    log_null_counts,
    parse_amount_expr,
    parse_date_expr,
    parse_timestamp_expr,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("cdw_migration.payments")


def read_source(spark: SparkSession, path: str, fmt: str):
    if fmt == "csv":
        return spark.read.option("header", "true").option("inferSchema", "false").csv(path)
    elif fmt == "parquet":
        return spark.read.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform(df, spark: SparkSession, loans_table: str):
    source_count = df.count()
    logger.info("Source row count: %d", source_count)

    # ---- FK lookup DataFrame ----
    loans_df = spark.table(loans_table).select(
        F.col("loan_account_id").alias("_la_id"),
        F.col("account_number").alias("_la_acct_nbr"),
    )

    # ---- Core transformations ----
    transformed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),
        F.col("LN_ACCT_NBR").alias("_acct_nbr_lookup"),
        parse_date_expr("PMT_DT", "payment_date"),
        parse_amount_expr("PMT_AMT", "total_amount", precision=10),
        parse_amount_expr("PMT_PRIN_AMT", "principal_amount", precision=10),
        parse_amount_expr("PMT_INT_AMT", "interest_amount", precision=10),
        parse_amount_expr("PMT_ESCROW_AMT", "escrow_amount", precision=10),
        parse_amount_expr("PMT_LATE_FEE", "late_fee", precision=10),
        expand_status_with_fallback("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        expand_status_with_fallback("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
        parse_date_expr("PMT_RECV_DT", "received_date"),
        parse_date_expr("PMT_PROC_DT", "processed_date"),
        parse_timestamp_expr("PMT_CRET_DT", "created_at"),
        parse_timestamp_expr("PMT_UPDT_DT", "updated_at"),
        F.current_timestamp().alias("_ingestion_ts"),
    )

    # ---- Resolve loan account FK ----
    transformed = transformed.join(
        loans_df,
        transformed["_acct_nbr_lookup"] == loans_df["_la_acct_nbr"],
        "left",
    ).withColumn("loan_account_id", F.col("_la_id"))

    unresolved = transformed.filter(F.col("loan_account_id").isNull()).count()
    if unresolved > 0:
        logger.warning(
            "%d payments have no matching loan account (orphan LN_ACCT_NBR). "
            "These rows are RETAINED with loan_account_id=NULL for manual review.",
            unresolved,
        )

    # ---- Derive partition column ----
    transformed = transformed.withColumn("payment_year", F.year(F.col("payment_date")))

    # ---- Select final columns ----
    final = transformed.select(
        "legacy_sequence_nbr",
        "loan_account_id",
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
        "payment_year",
        "_ingestion_ts",
    )

    required_cols = ["loan_account_id", "payment_date", "total_amount", "type", "status"]
    log_null_counts(final, "payments", required_cols)

    target_count = final.count()
    logger.info("Target row count: %d", target_count)
    if source_count != target_count:
        logger.error("ROW COUNT MISMATCH: source=%d, target=%d", source_count, target_count)

    return final


def write_target(df, target_table: str, mode: str = "overwrite"):
    logger.info("Writing %d rows to %s (mode=%s)", df.count(), target_table, mode)
    df.write.format("delta").mode(mode).partitionBy("payment_year").saveAsTable(target_table)
    logger.info("Write complete.")


def main():
    parser = argparse.ArgumentParser(description="Ingest CDW_PMT_HIST into payments Delta table")
    parser.add_argument("--source", required=True, help="Path to legacy payment history source file")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    parser.add_argument("--target", default="loan_catalog.loan_warehouse.payments", help="Target Delta table")
    parser.add_argument("--loans-table", default="loan_catalog.loan_warehouse.loan_accounts", help="Loan accounts table for FK resolution")
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"], help="Write mode")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_Payments").getOrCreate()

    try:
        raw_df = read_source(spark, args.source, args.format)
        transformed_df = transform(raw_df, spark, args.loans_table)
        write_target(transformed_df, args.target, args.mode)
    except Exception:
        logger.exception("Payments ingestion failed")
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
