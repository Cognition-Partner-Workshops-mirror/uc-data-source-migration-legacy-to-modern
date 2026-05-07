"""
Ingest CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment history table, converts all VARCHAR amounts
and dates, expands type/status codes, resolves the loan_account_id
foreign key, and writes to the modern Delta Lake table.

Usage:
    from ingestion.ingest_payments import run
    report_df = run(spark, source_path="...", source_format="csv")
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from transform_utils import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    collect_bad_value_report,
    drop_flag_columns,
    expand_status_col,
    parse_amount_col,
    parse_date_col,
    parse_timestamp_col,
)

TARGET_TABLE = "loan_warehouse.payments"
SOURCE_TABLE = "CDW_PMT_HIST"


def read_source(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
) -> DataFrame:
    reader = spark.read.format(source_format)
    if source_format == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(source_path)


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    # --- keep legacy sequence number for traceability ---
    df = df.withColumnRenamed("PMT_SEQ_NBR", "legacy_sequence_nbr")

    # --- amount conversions ---
    df = parse_amount_col(df, "PMT_AMT", "total_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)

    # --- date conversions ---
    df = parse_date_col(df, "PMT_DT", "payment_date")
    df = parse_date_col(df, "PMT_RECV_DT", "received_date")
    df = parse_date_col(df, "PMT_PROC_DT", "processed_date")
    df = parse_timestamp_col(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "PMT_UPDT_DT", "updated_at")

    # --- code expansions ---
    df = expand_status_col(df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)
    df = expand_status_col(df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # --- FK resolution: loan_account_id ---
    accounts = spark.table("loan_warehouse.loan_accounts").select(
        F.col("loan_account_id"), F.col("account_number"),
    )
    df = df.join(
        accounts,
        df["LN_ACCT_NBR"] == accounts["account_number"],
        "left",
    )
    unmatched = df.filter(F.col("loan_account_id").isNull()).count()
    if unmatched > 0:
        print(
            f"[{SOURCE_TABLE}] WARNING: {unmatched} payments have no matching "
            f"loan account (LN_ACCT_NBR not found in loan_accounts.account_number)"
        )
    df = df.drop("account_number")

    # --- drop legacy columns ---
    legacy_cols = [
        "LN_ACCT_NBR",
        "PMT_AMT", "PMT_PRIN_AMT", "PMT_INT_AMT", "PMT_ESCROW_AMT",
        "PMT_LATE_FEE", "PMT_DT", "PMT_RECV_DT", "PMT_PROC_DT",
        "PMT_CRET_DT", "PMT_UPDT_DT", "PMT_TYP_CD", "PMT_STAT_CD",
    ]
    df = df.drop(*legacy_cols)

    # --- lineage ---
    df = df.withColumn("_migration_source", F.lit(SOURCE_TABLE))
    df = df.withColumn("_migrated_at", F.current_timestamp())

    return df


def run(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
    write_mode: str = "overwrite",
) -> DataFrame:
    raw_df = read_source(spark, source_path, source_format)
    source_count = raw_df.count()
    print(f"[{SOURCE_TABLE}] Source row count: {source_count}")

    transformed_df = transform(raw_df, spark)

    bad_report = collect_bad_value_report(transformed_df, SOURCE_TABLE)
    bad_count = bad_report.count()
    if bad_count > 0:
        print(f"[{SOURCE_TABLE}] WARNING: {bad_count} parse issues detected")
        bad_report.show(truncate=False)

    clean_df = drop_flag_columns(transformed_df)

    final_df = clean_df.select(
        "legacy_sequence_nbr", "loan_account_id",
        "payment_date", "total_amount",
        "principal_amount", "interest_amount", "escrow_amount", "late_fee",
        "type", "status",
        "received_date", "processed_date",
        "created_at", "updated_at",
        "_migration_source", "_migrated_at",
    )

    final_df.write.format("delta").mode(write_mode).partitionBy("status").saveAsTable(TARGET_TABLE)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[{SOURCE_TABLE}] Target row count: {target_count}")

    if source_count != target_count:
        print(
            f"[{SOURCE_TABLE}] ERROR: Row count mismatch! "
            f"source={source_count}, target={target_count}"
        )

    return bad_report
