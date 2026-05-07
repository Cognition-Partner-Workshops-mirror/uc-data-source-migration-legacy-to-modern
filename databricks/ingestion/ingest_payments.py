"""
Ingestion notebook: CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment-history data, applies type conversions and
status/type code expansion, resolves the loan_account FK, and writes
to the modern Delta Lake payments table.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    expand_payment_status,
    expand_payment_type,
    parse_amount,
    parse_date_mmddyyyy,
    parse_timestamp_mmddyyyy,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/legacy-export/CDW_PMT_HIST"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
LOAN_ACCOUNTS_TABLE = "loan_warehouse.loan_accounts"
WRITE_MODE = "overwrite"

# ---------------------------------------------------------------------------
# Spark
# ---------------------------------------------------------------------------
spark = SparkSession.builder.appName("ingest_payments").getOrCreate()
spark.conf.set("spark.sql.legacy.timeParserPolicy", "CORRECTED")

_LOG_TAG = "[ingest_payments]"


def _log(msg: str) -> None:
    print(f"{_LOG_TAG} {msg}")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(path: str, fmt: str) -> DataFrame:
    _log(f"Reading source from {path} (format={fmt})")
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(path)
    _log(f"Source row count: {df.count()}")
    return df


# ---------------------------------------------------------------------------
# FK resolution
# ---------------------------------------------------------------------------

def _resolve_loan_account_ids(df: DataFrame) -> DataFrame:
    """Join legacy LN_ACCT_NBR to modern loan_accounts.id via account_number."""
    loans = spark.table(LOAN_ACCOUNTS_TABLE).select(
        F.col("id").alias("_loan_pk"),
        F.col("account_number"),
    )
    joined = df.join(
        loans,
        df["LN_ACCT_NBR"] == loans["account_number"],
        "left",
    )
    unresolved = joined.filter(F.col("_loan_pk").isNull()).count()
    if unresolved > 0:
        _log(f"WARNING: {unresolved} payment rows have no matching loan account")
    return joined


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame) -> DataFrame:
    df = _resolve_loan_account_ids(df)

    payment_date_col = parse_date_mmddyyyy(F.col("PMT_DT"))

    transformed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_payment_id"),
        F.col("_loan_pk").alias("loan_account_id"),
        payment_date_col.alias("payment_date"),
        parse_amount(F.col("PMT_AMT"), precision=10).alias("total_amount"),
        parse_amount(F.col("PMT_PRIN_AMT"), precision=10).alias("principal_amount"),
        parse_amount(F.col("PMT_INT_AMT"), precision=10).alias("interest_amount"),
        parse_amount(F.col("PMT_ESCROW_AMT"), precision=10).alias("escrow_amount"),
        parse_amount(F.col("PMT_LATE_FEE"), precision=10).alias("late_fee"),
        expand_payment_type(F.col("PMT_TYP_CD")).alias("type"),
        expand_payment_status(F.col("PMT_STAT_CD")).alias("status"),
        parse_date_mmddyyyy(F.col("PMT_RECV_DT")).alias("received_date"),
        parse_date_mmddyyyy(F.col("PMT_PROC_DT")).alias("processed_date"),
        parse_timestamp_mmddyyyy(F.col("PMT_CRET_DT")).alias("created_at"),
        parse_timestamp_mmddyyyy(F.col("PMT_UPDT_DT")).alias("updated_at"),
        F.year(payment_date_col).alias("payment_year"),
    )

    null_loans = transformed.filter(F.col("loan_account_id").isNull()).count()
    if null_loans > 0:
        _log(f"WARNING: {null_loans} rows have NULL loan_account_id after FK resolution")

    bad_amounts = transformed.filter(
        F.col("total_amount").isNull() & df["PMT_AMT"].isNotNull()
    ).count()
    if bad_amounts > 0:
        _log(f"WARNING: {bad_amounts} rows had unparseable total_amount values")

    _log(f"Transformed row count: {transformed.count()}")
    return transformed


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(df: DataFrame, table: str, mode: str) -> None:
    _log(f"Writing {df.count()} rows to {table} (mode={mode})")
    df.write.format("delta").mode(mode).option(
        "mergeSchema", "true"
    ).partitionBy("payment_year").saveAsTable(table)
    _log("Write complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    source_df = read_source(SOURCE_PATH, SOURCE_FORMAT)
    transformed_df = transform(source_df)
    write_target(transformed_df, TARGET_TABLE, WRITE_MODE)
    _log("Payment ingestion finished successfully.")


if __name__ == "__main__":
    main()
