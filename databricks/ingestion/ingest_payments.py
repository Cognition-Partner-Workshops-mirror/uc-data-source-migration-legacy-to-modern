"""
Ingestion script: CDW_PMT_HIST → payments (Delta Lake)

Reads legacy payment history data from CSV/Parquet source, applies transformations
per column_mappings.md, resolves loan account FK, and writes to the modern payments Delta table.
"""

from pyspark.sql.functions import col, monotonically_increasing_id

from common import (
    get_spark,
    logger,
    parse_date_column,
    parse_timestamp_column,
    parse_amount_column,
    expand_status_code,
    log_record_counts,
    log_null_counts,
    write_delta,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
    CATALOG,
    SCHEMA,
)


def read_legacy_payments(spark, source_path: str):
    """Read legacy CDW_PMT_HIST data from CSV or Parquet."""
    if source_path.endswith(".parquet"):
        df = spark.read.parquet(source_path)
    else:
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .csv(source_path)
        )
    logger.info(f"Read source file: {source_path}")
    return df


def resolve_loan_account_ids(spark, df):
    """
    Resolve LN_ACCT_NBR to the modern loan_accounts.id via lookup.
    Records with unresolved account numbers are logged but retained.
    """
    accounts_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts").select(
        col("id").alias("loan_account_id"),
        col("account_number"),
    )

    joined = df.join(
        accounts_df,
        df["LN_ACCT_NBR"] == accounts_df["account_number"],
        "left"
    )

    unresolved_count = joined.filter(col("loan_account_id").isNull()).count()
    if unresolved_count > 0:
        logger.warning(
            f"[payments] {unresolved_count} records have unresolved loan account numbers"
        )

    return joined.drop("account_number")


def transform_payments(spark, df):
    """Apply transformations for payment history."""
    source_count = log_record_counts(df, "payments", "source")

    log_null_counts(df, "payments", ["PMT_SEQ_NBR", "LN_ACCT_NBR", "PMT_DT", "PMT_AMT"])

    result = df.select(
        col("PMT_SEQ_NBR").alias("legacy_sequence_id"),
        col("LN_ACCT_NBR"),
        col("PMT_DT"),
        col("PMT_AMT"),
        col("PMT_PRIN_AMT"),
        col("PMT_INT_AMT"),
        col("PMT_ESCROW_AMT"),
        col("PMT_LATE_FEE"),
        col("PMT_TYP_CD"),
        col("PMT_STAT_CD"),
        col("PMT_RECV_DT"),
        col("PMT_PROC_DT"),
        col("PMT_CRET_DT"),
        col("PMT_UPDT_DT"),
    )

    # Resolve loan account FK
    result = resolve_loan_account_ids(spark, result)
    result = result.drop("LN_ACCT_NBR")

    # Parse amount columns
    result = parse_amount_column(result, "PMT_AMT", "total_amount", precision=10, scale=2)
    result = result.drop("PMT_AMT")
    result = parse_amount_column(result, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
    result = result.drop("PMT_PRIN_AMT")
    result = parse_amount_column(result, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
    result = result.drop("PMT_INT_AMT")
    result = parse_amount_column(result, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
    result = result.drop("PMT_ESCROW_AMT")
    result = parse_amount_column(result, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)
    result = result.drop("PMT_LATE_FEE")

    # Parse date columns
    result = parse_date_column(result, "PMT_DT", "payment_date")
    result = result.drop("PMT_DT")
    result = parse_date_column(result, "PMT_RECV_DT", "received_date")
    result = result.drop("PMT_RECV_DT")
    result = parse_date_column(result, "PMT_PROC_DT", "processed_date")
    result = result.drop("PMT_PROC_DT")

    # Parse timestamps
    result = parse_timestamp_column(result, "PMT_CRET_DT", "created_at")
    result = result.drop("PMT_CRET_DT")
    result = parse_timestamp_column(result, "PMT_UPDT_DT", "updated_at")
    result = result.drop("PMT_UPDT_DT")

    # Expand status/type codes
    result = expand_status_code(result, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)
    result = result.drop("PMT_TYP_CD")
    result = expand_status_code(result, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)
    result = result.drop("PMT_STAT_CD")

    # Add surrogate key
    result = result.withColumn("id", monotonically_increasing_id())

    target_count = log_record_counts(result, "payments", "transformed")

    if source_count != target_count:
        logger.error(
            f"[payments] Record count mismatch! Source={source_count}, Target={target_count}"
        )

    return result


def run(source_path: str):
    """Main entry point for payment ingestion."""
    spark = get_spark()
    logger.info("=== Starting Payment Ingestion ===")

    raw_df = read_legacy_payments(spark, source_path)
    transformed_df = transform_payments(spark, raw_df)
    write_delta(transformed_df, "payments", partition_cols=["status"])

    logger.info("=== Payment Ingestion Complete ===")
    return transformed_df


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: spark-submit ingest_payments.py <source_path>")
        sys.exit(1)
    run(sys.argv[1])
