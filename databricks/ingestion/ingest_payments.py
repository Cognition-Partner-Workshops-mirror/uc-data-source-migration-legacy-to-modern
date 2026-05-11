"""
ingest_payments.py — PySpark ingestion for CDW_PMT_HIST → payments.

Reads the legacy payment history data, applies all transformations from
column_mappings.md, resolves the loan account foreign key, and writes to
the Delta Lake `loan_warehouse.payments` table.

Key transformations:
  - Parse date strings (MM/DD/YYYY) → DateType / TimestampType
  - Parse amount strings with commas → DecimalType
  - Expand payment type codes: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
  - Expand payment status codes: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
  - Resolve LN_ACCT_NBR → loan_accounts.id via lookup
  - Extract payment_year from payment_date for partitioning
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
import logging

from common_transforms import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    expand_code_col,
    log_null_counts,
    add_ingestion_metadata,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

logger = logging.getLogger("cdw_migration.payments")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/legacy-extract/CDW_PMT_HIST"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"


def read_source(spark: SparkSession) -> "DataFrame":
    """Read the legacy CDW_PMT_HIST extract (CSV or Parquet)."""
    if SOURCE_FORMAT == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "NULL")
            .option("emptyValue", "")
            .csv(SOURCE_PATH)
        )
    else:
        df = spark.read.parquet(SOURCE_PATH)

    logger.info("Read %d rows from %s (%s)", df.count(), SOURCE_PATH, SOURCE_FORMAT)
    return df


def resolve_foreign_keys(df: "DataFrame", spark: SparkSession) -> "DataFrame":
    """Resolve LN_ACCT_NBR → loan_accounts.id via account_number lookup.

    Payments with unresolvable loan account references are kept (with NULL FK)
    and flagged in quality checks — never silently dropped.
    """
    loan_lookup = (
        spark.table("loan_warehouse.loan_accounts")
        .select(
            F.col("id").alias("loan_account_id"),
            F.col("account_number").alias("_acct_nbr"),
        )
    )

    # Left join to preserve all payment records
    df = df.join(loan_lookup, df["LN_ACCT_NBR"] == loan_lookup["_acct_nbr"], "left")
    df = df.drop("_acct_nbr")

    # Log unresolved references
    unresolved = df.filter(F.col("loan_account_id").isNull()).count()
    if unresolved > 0:
        logger.warning(
            "%d payments have unresolved loan_account_id (LN_ACCT_NBR not in loan_accounts)",
            unresolved,
        )

    return df


def transform(df: "DataFrame", spark: SparkSession) -> "DataFrame":
    """Apply all column mappings, type conversions, and FK resolution."""

    # --- Resolve foreign keys first (needs original LN_ACCT_NBR) ---
    df = resolve_foreign_keys(df, spark)

    # --- Date columns ---
    df = parse_date_col(df, "PMT_DT", "payment_date")
    df = parse_date_col(df, "PMT_RECV_DT", "received_date")
    df = parse_date_col(df, "PMT_PROC_DT", "processed_date")
    df = parse_timestamp_col(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "PMT_UPDT_DT", "updated_at")

    # --- Amount columns ---
    df = parse_amount_col(df, "PMT_AMT", "total_amount", 10, 2)
    df = parse_amount_col(df, "PMT_PRIN_AMT", "principal_amount", 10, 2)
    df = parse_amount_col(df, "PMT_INT_AMT", "interest_amount", 10, 2)
    df = parse_amount_col(df, "PMT_ESCROW_AMT", "escrow_amount", 10, 2)
    df = parse_amount_col(df, "PMT_LATE_FEE", "late_fee", 10, 2)

    # --- Code expansion ---
    df = expand_code_col(df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)
    df = expand_code_col(df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # --- Partition helper: extract year from parsed payment_date ---
    df = df.withColumn("payment_year", F.year(F.col("payment_date")))

    # --- Rename legacy sequence number ---
    df = df.withColumnRenamed("PMT_SEQ_NBR", "legacy_sequence_nbr")

    # --- Drop original columns that have been transformed ---
    cols_to_drop = [
        "LN_ACCT_NBR", "PMT_DT", "PMT_RECV_DT", "PMT_PROC_DT",
        "PMT_CRET_DT", "PMT_UPDT_DT",
        "PMT_AMT", "PMT_PRIN_AMT", "PMT_INT_AMT", "PMT_ESCROW_AMT", "PMT_LATE_FEE",
        "PMT_TYP_CD", "PMT_STAT_CD",
    ]
    df = df.drop(*cols_to_drop)

    # --- Add ingestion metadata ---
    df = add_ingestion_metadata(df, "CDW_PMT_HIST")

    # --- Select final column order ---
    df = df.select(
        "legacy_sequence_nbr",
        "loan_account_id",
        "payment_date",
        "total_amount", "principal_amount", "interest_amount",
        "escrow_amount", "late_fee",
        "type", "status",
        "received_date", "processed_date",
        "created_at", "updated_at",
        "payment_year",
        "_ingestion_ts", "_source_system",
    )

    return df


def validate_pre_write(df: "DataFrame") -> None:
    """Log NULL counts on critical fields before writing."""
    critical_cols = [
        "legacy_sequence_nbr", "loan_account_id", "payment_date",
        "total_amount", "type", "status",
    ]
    log_null_counts(df, critical_cols, TARGET_TABLE)


def write_target(df: "DataFrame") -> None:
    """Write payments to Delta Lake with MERGE upsert on legacy_sequence_nbr."""
    from delta.tables import DeltaTable

    spark = df.sparkSession
    if DeltaTable.isDeltaTable(spark, TARGET_TABLE):
        target = DeltaTable.forName(spark, TARGET_TABLE)
        (
            target.alias("tgt")
            .merge(df.alias("src"), "tgt.legacy_sequence_nbr = src.legacy_sequence_nbr")
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )
        logger.info("MERGE completed into %s", TARGET_TABLE)
    else:
        (
            df.write
            .format("delta")
            .mode("overwrite")
            .partitionBy("payment_year")
            .saveAsTable(TARGET_TABLE)
        )
        logger.info("Initial load completed into %s", TARGET_TABLE)


def main():
    """Entry point — orchestrates read → transform → validate → write."""
    spark = SparkSession.builder.appName("CDW Migration — Payments").getOrCreate()
    logger.info("Starting payments ingestion from %s", SOURCE_PATH)

    raw_df = read_source(spark)
    transformed_df = transform(raw_df, spark)
    validate_pre_write(transformed_df)
    write_target(transformed_df)

    logger.info("Payments ingestion complete. Rows written: %d", transformed_df.count())


if __name__ == "__main__":
    main()
