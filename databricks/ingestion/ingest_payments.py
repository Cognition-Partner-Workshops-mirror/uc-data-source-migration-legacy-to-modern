"""Ingest legacy CDW_PMT_HIST into Delta Lake ``loan_warehouse.payments``.

Reads from a CSV/Parquet source file that mirrors the legacy CDW_PMT_HIST
table structure. Resolves loan account foreign keys, applies type conversions,
expands status/type codes, and writes to the target Delta table partitioned
by payment year.

Usage:
    from databricks.ingestion.ingest_payments import run
    run(spark, source_path="...", target_table="loan_warehouse.payments")
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from databricks.ingestion.utils import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    add_ingestion_metadata,
    expand_status,
    log_null_counts,
    parse_amount,
    parse_date,
    parse_timestamp,
)

EXPECTED_COLUMNS = [
    "PMT_SEQ_NBR", "LN_ACCT_NBR", "PMT_DT", "PMT_AMT", "PMT_PRIN_AMT",
    "PMT_INT_AMT", "PMT_ESCROW_AMT", "PMT_LATE_FEE", "PMT_TYP_CD",
    "PMT_STAT_CD", "PMT_RECV_DT", "PMT_PROC_DT", "PMT_CRET_DT", "PMT_UPDT_DT",
]

REQUIRED_FIELDS = ["PMT_SEQ_NBR", "LN_ACCT_NBR", "PMT_DT", "PMT_AMT"]


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv") -> DataFrame:
    if file_format == "parquet":
        return spark.read.parquet(source_path)
    return spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)


def validate_schema(df: DataFrame) -> DataFrame:
    missing = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Source is missing expected columns: {sorted(missing)}")
    return df


def quarantine_bad_rows(df: DataFrame) -> tuple:
    condition = F.lit(True)
    for col_name in REQUIRED_FIELDS:
        condition = condition & F.col(col_name).isNotNull() & (F.trim(F.col(col_name)) != "")
    good_df = df.filter(condition)
    quarantine_df = df.filter(~condition)

    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        print(f"[WARN] Quarantined {quarantine_count} payment rows with missing required fields.")

    return good_df, quarantine_df


def resolve_loan_account_keys(df: DataFrame, spark: SparkSession, loan_table: str) -> DataFrame:
    """Join with loan_accounts to resolve LN_ACCT_NBR -> loan_account_key."""
    loans = spark.table(loan_table).select(
        F.col("loan_account_key"),
        F.col("account_number").alias("_ln_acct_nbr"),
    )
    df = df.join(loans, df["LN_ACCT_NBR"] == loans["_ln_acct_nbr"], "left")

    unmatched = df.filter(F.col("loan_account_key").isNull()).count()
    if unmatched > 0:
        print(f"[WARN] {unmatched} payments have no matching loan account (LN_ACCT_NBR not found).")

    return df.drop("_ln_acct_nbr")


def transform(df: DataFrame) -> DataFrame:
    """Apply all column transformations for the payments table."""
    # Date conversions
    df = parse_date(df, "PMT_DT", "payment_date")
    df = parse_date(df, "PMT_RECV_DT", "received_date")
    df = parse_date(df, "PMT_PROC_DT", "processed_date")
    df = parse_timestamp(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp(df, "PMT_UPDT_DT", "updated_at")

    # Amount conversions
    df = parse_amount(df, "PMT_AMT", "total_amount", precision=10, scale=2)
    df = parse_amount(df, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
    df = parse_amount(df, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
    df = parse_amount(df, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
    df = parse_amount(df, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)

    # Status and type expansion
    df = expand_status(df, "PMT_TYP_CD", PAYMENT_TYPE_MAP, "type")
    df = expand_status(df, "PMT_STAT_CD", PAYMENT_STATUS_MAP, "status")

    # Derived column: payment year for partitioning
    df = df.withColumn("payment_year", F.year(F.col("payment_date")))

    # Rename legacy ID column
    df = df.withColumnRenamed("PMT_SEQ_NBR", "legacy_payment_id")

    df = add_ingestion_metadata(df, "CDW_PMT_HIST")

    final_columns = [
        "legacy_payment_id", "loan_account_key",
        "payment_date", "total_amount", "principal_amount",
        "interest_amount", "escrow_amount", "late_fee",
        "type", "status",
        "received_date", "processed_date", "payment_year",
        "created_at", "updated_at",
        "_ingestion_ts", "_source_system",
    ]
    return df.select(*final_columns)


def write_target(df: DataFrame, target_table: str, mode: str = "overwrite") -> None:
    df.write.format("delta").mode(mode).partitionBy("payment_year").saveAsTable(target_table)
    row_count = df.count()
    print(f"[INFO] Wrote {row_count} rows to {target_table}.")


def run(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.payments",
    loan_table: str = "loan_warehouse.loan_accounts",
    file_format: str = "csv",
    quarantine_path: str | None = None,
) -> dict:
    print(f"[INFO] Starting payment ingestion from {source_path}")

    raw_df = read_source(spark, source_path, file_format)
    raw_df = validate_schema(raw_df)
    raw_count = raw_df.count()
    print(f"[INFO] Source row count: {raw_count}")

    good_df, quarantine_df = quarantine_bad_rows(raw_df)
    log_null_counts(good_df, "CDW_PMT_HIST (pre-transform)", EXPECTED_COLUMNS)

    good_df = resolve_loan_account_keys(good_df, spark, loan_table)

    transformed_df = transform(good_df)
    write_target(transformed_df, target_table)

    quarantine_count = quarantine_df.count()
    if quarantine_count > 0 and quarantine_path:
        quarantine_df.write.format("delta").mode("overwrite").save(quarantine_path)
        print(f"[WARN] {quarantine_count} quarantined rows written to {quarantine_path}")

    return {
        "source_count": raw_count,
        "loaded_count": raw_count - quarantine_count,
        "quarantined_count": quarantine_count,
        "target_table": target_table,
    }
