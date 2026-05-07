"""
Ingest payment history from legacy CDW_PMT_HIST into Delta Lake ``loan_warehouse.payments``.

Key transformations:
  - Resolve LN_ACCT_NBR -> loan_account_id FK via loan_accounts table
  - Parse all date and amount columns
  - Expand PMT_TYP_CD and PMT_STAT_CD
  - Derive payment_year partition column from PMT_DT

Usage:
    spark-submit ingest_payments.py --source /mnt/landing/cdw_pmt_hist --format csv
"""

import argparse
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from common_utils import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    collect_parse_errors,
    drop_audit_columns,
    expand_status_col,
    log_error_summary,
    parse_amount_col,
    parse_date_col,
    parse_timestamp_col,
    read_legacy_source,
)

TARGET_TABLE = "loan_warehouse.payments"
SOURCE_SYSTEM = "CDW_PMT_HIST"
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_pmt_hist"


def transform_payments(raw_df, spark):
    """Apply all column-level transformations and FK resolution."""

    df = raw_df

    # --- Date conversions ---
    df = parse_date_col(df, "PMT_DT", "payment_date")
    df = parse_date_col(df, "PMT_RECV_DT", "received_date")
    df = parse_date_col(df, "PMT_PROC_DT", "processed_date")
    df = parse_timestamp_col(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "PMT_UPDT_DT", "updated_at")

    # --- Amount conversions ---
    df = parse_amount_col(df, "PMT_AMT", "total_amount", 10, 2)
    df = parse_amount_col(df, "PMT_PRIN_AMT", "principal_amount", 10, 2)
    df = parse_amount_col(df, "PMT_INT_AMT", "interest_amount", 10, 2)
    df = parse_amount_col(df, "PMT_ESCROW_AMT", "escrow_amount", 10, 2)
    df = parse_amount_col(df, "PMT_LATE_FEE", "late_fee", 10, 2)

    # --- Status / type expansion ---
    df = expand_status_col(df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)
    df = expand_status_col(df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # --- Legacy sequence number (preserve for audit) ---
    df = df.withColumn("legacy_sequence_nbr", F.col("PMT_SEQ_NBR"))

    # --- Derived partition column ---
    df = df.withColumn("payment_year", F.year(F.col("payment_date")))

    # --- FK resolution: LN_ACCT_NBR -> loan_account_id ---
    accounts_lkp = spark.table("loan_warehouse.loan_accounts").select(
        F.col("loan_account_id").alias("_resolved_loan_id"),
        F.col("account_number").alias("_acct_nbr"),
    )
    df = df.join(
        accounts_lkp,
        df["LN_ACCT_NBR"] == accounts_lkp["_acct_nbr"],
        "left",
    )
    df = df.withColumn("loan_account_id", F.col("_resolved_loan_id"))
    df = df.withColumn(
        "__loan_account_id_unresolved",
        F.when(F.col("loan_account_id").isNull() & F.col("LN_ACCT_NBR").isNotNull(), True)
         .otherwise(False),
    )

    # --- Metadata ---
    df = (
        df.withColumn("_migration_ts", F.current_timestamp())
          .withColumn("_source_system", F.lit(SOURCE_SYSTEM))
    )

    return df


def run(spark, source_path, source_format="csv", write_mode="overwrite"):
    """End-to-end ingestion pipeline for payments."""

    print(f"=== Ingesting {SOURCE_SYSTEM} -> {TARGET_TABLE} ===")
    print(f"  Source: {source_path} ({source_format})")

    raw_df = read_legacy_source(spark, source_path, fmt=source_format)
    source_count = raw_df.count()
    print(f"  Source row count: {source_count}")

    if source_count == 0:
        print("  WARNING: Source is empty. Skipping ingestion.")
        return {"source_count": 0, "target_count": 0, "errors": {}}

    transformed_df = transform_payments(raw_df, spark)

    error_summary = log_error_summary(transformed_df, SOURCE_SYSTEM)
    error_rows = collect_parse_errors(transformed_df)
    error_count = error_rows.count()
    if error_count > 0:
        print(f"  WARNING: {error_count} row(s) had parse issues — writing anyway.")
        error_rows.write.mode("overwrite").parquet(
            f"/mnt/migration_errors/{SOURCE_SYSTEM}_errors"
        )

    unresolved_accounts = transformed_df.filter(
        F.col("__loan_account_id_unresolved") == True  # noqa: E712
    ).count()
    if unresolved_accounts > 0:
        print(f"  WARNING: {unresolved_accounts} row(s) with unresolved loan account FK")

    final_df = drop_audit_columns(transformed_df).select(
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
        "_migration_ts",
        "_source_system",
    )

    (
        final_df.write
        .format("delta")
        .mode(write_mode)
        .option("mergeSchema", "true")
        .partitionBy("payment_year")
        .saveAsTable(TARGET_TABLE)
    )

    target_count = spark.table(TARGET_TABLE).count()
    print(f"  Target row count: {target_count}")
    print(f"  Reconciliation: source={source_count}, target={target_count}, "
          f"match={source_count == target_count}")
    print(f"=== {SOURCE_SYSTEM} ingestion complete ===\n")

    return {
        "source_count": source_count,
        "target_count": target_count,
        "errors": error_summary,
        "unresolved_loan_fks": unresolved_accounts,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_PMT_HIST into Delta Lake")
    parser.add_argument("--source", default=DEFAULT_SOURCE_PATH)
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    spark = SparkSession.builder.appName("IngestPayments").getOrCreate()
    result = run(spark, args.source, args.format, args.mode)
    if result["source_count"] != result["target_count"]:
        print("ERROR: Row count mismatch!")
        sys.exit(1)
