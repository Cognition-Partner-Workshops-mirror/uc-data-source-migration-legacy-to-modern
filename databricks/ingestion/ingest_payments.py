"""
Ingest CDW_PMT_HIST (legacy) -> payments (Delta Lake).

Source: CSV or Parquet export of the CDW_PMT_HIST table.
Target: loan_warehouse.payments Delta table.

Transformations applied:
  - Resolve loan_account_id via FK lookup against loan_accounts table
  - Parse all date strings (MM/DD/YYYY) to DateType / TimestampType
  - Parse all amount strings (comma-formatted) to DecimalType
  - Expand payment type codes (REG->REGULAR, EXT->EXTRA, etc.)
  - Expand payment status codes (PST->POSTED, REV->REVERSED, etc.)
  - Preserve legacy PMT_SEQ_NBR as legacy_sequence_number for traceability
  - Generate surrogate id
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from databricks.ingestion.transformations import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    add_row_quality_flag,
    expand_status_col,
    log_null_counts,
    parse_amount_col,
    parse_date_col,
    parse_timestamp_col,
)
from databricks.schemas.payments import (
    PAYMENTS_PARTITION_COLS,
    PAYMENTS_PATH,
)

logger = logging.getLogger("loan_migration.ingest_payments")

REQUIRED_COLS = ["loan_account_id", "payment_date", "total_amount", "type", "status"]

SOURCE_FILE_DEFAULT = "/mnt/legacy/CDW_PMT_HIST"


def read_source(spark: SparkSession, path: str = SOURCE_FILE_DEFAULT, fmt: str = "csv") -> DataFrame:
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _build_loan_account_lookup(spark: SparkSession) -> DataFrame:
    """
    Build a lookup DataFrame mapping legacy LN_ACCT_NBR (account_number)
    to the modern loan_accounts surrogate id.
    """
    accounts_df = spark.read.format("delta").load("/mnt/delta/loan_warehouse/loan_accounts")
    return accounts_df.select(
        F.col("id").alias("_loan_pk"),
        F.col("account_number").alias("_acct_nbr"),
    )


def transform(source_df: DataFrame, spark: SparkSession) -> DataFrame:
    loan_lookup = _build_loan_account_lookup(spark)

    base = source_df.select(
        F.monotonically_increasing_id().alias("id"),
        F.col("LN_ACCT_NBR").alias("_legacy_acct_nbr"),
        parse_date_col("PMT_DT", "payment_date"),
        parse_amount_col("PMT_AMT", "total_amount", 10, 2),
        parse_amount_col("PMT_PRIN_AMT", "principal_amount", 10, 2),
        parse_amount_col("PMT_INT_AMT", "interest_amount", 10, 2),
        parse_amount_col("PMT_ESCROW_AMT", "escrow_amount", 10, 2),
        parse_amount_col("PMT_LATE_FEE", "late_fee", 10, 2),
        expand_status_col("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        expand_status_col("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
        parse_date_col("PMT_RECV_DT", "received_date"),
        parse_date_col("PMT_PROC_DT", "processed_date"),
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_number"),
        parse_timestamp_col("PMT_CRET_DT", "created_at"),
        parse_timestamp_col("PMT_UPDT_DT", "updated_at"),
    )

    # Resolve loan account FK
    with_loan = base.join(
        loan_lookup,
        base["_legacy_acct_nbr"] == loan_lookup["_acct_nbr"],
        "left",
    ).withColumn("loan_account_id", F.col("_loan_pk"))

    unresolved = with_loan.filter(F.col("loan_account_id").isNull()).count()
    if unresolved > 0:
        logger.warning(
            "payments: %d records have unresolvable loan account numbers",
            unresolved,
        )

    final = with_loan.select(
        "id", "loan_account_id", "payment_date", "total_amount",
        "principal_amount", "interest_amount", "escrow_amount",
        "late_fee", "type", "status", "received_date", "processed_date",
        "legacy_sequence_number", "created_at", "updated_at",
    )

    return add_row_quality_flag(final, REQUIRED_COLS)


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    clean_df = df.drop("_has_quality_issue")
    writer = clean_df.write.format("delta").mode(mode)
    if PAYMENTS_PARTITION_COLS:
        writer = writer.partitionBy(*PAYMENTS_PARTITION_COLS)
    writer.save(PAYMENTS_PATH)
    logger.info("Wrote payments to %s", PAYMENTS_PATH)


def run(spark: SparkSession, source_path: str = SOURCE_FILE_DEFAULT, fmt: str = "csv") -> dict:
    logger.info("Starting payments ingestion from %s", source_path)

    source_df = read_source(spark, source_path, fmt)
    source_count = source_df.count()
    logger.info("Source row count: %d", source_count)

    transformed_df = transform(source_df, spark)
    target_count = transformed_df.count()

    null_issues = log_null_counts(transformed_df, "payments", REQUIRED_COLS)
    quality_issues = transformed_df.filter(F.col("_has_quality_issue")).count()

    write_target(transformed_df)

    summary = {
        "table": "payments",
        "source_count": source_count,
        "target_count": target_count,
        "records_with_quality_issues": quality_issues,
        "null_counts": null_issues,
    }
    logger.info("Payments ingestion complete: %s", summary)
    return summary
