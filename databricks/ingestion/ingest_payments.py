"""
Ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment history table (simulated as CSV/Parquet),
applies type conversions and status/type expansion, derives partition
columns, and writes to Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from databricks.ingestion.transforms import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    expand_status,
    quarantine_nulls,
    log_row_counts,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
    logger,
)

TARGET_TABLE = "loan_warehouse.payments"
SOURCE_TABLE = "CDW_PMT_HIST"
REQUIRED_COLS = ["loan_account_number", "payment_date", "total_amount", "type", "status"]


def read_source(spark: SparkSession, source_path: str, source_format: str = "csv") -> DataFrame:
    """Read legacy payment history data from CSV or Parquet source files."""
    if source_format == "csv":
        df = (
            spark.read.format("csv")
            .option("header", "true")
            .option("inferSchema", "false")
            .load(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from %s (%s)", df.count(), source_path, source_format)
    return df


def transform(df: DataFrame) -> DataFrame:
    """Transform legacy payment history data to modern schema.

    Transformations:
        - Rename cryptic columns to meaningful names
        - Parse all amount strings (with commas) to DecimalType
        - Parse all date strings from MM/DD/YYYY to DateType / TimestampType
        - Expand payment type codes (REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT)
        - Expand payment status codes (PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING)
        - Derive payment_year and payment_month partition columns
        - Retain legacy PMT_SEQ_NBR for traceability
    """
    # Rename key columns
    df = (
        df.withColumnRenamed("PMT_SEQ_NBR", "legacy_payment_seq")
        .withColumnRenamed("LN_ACCT_NBR", "loan_account_number")
    )

    # Parse amount fields
    df = parse_amount_col(df, "PMT_AMT", "total_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)

    # Parse date fields
    df = parse_date_col(df, "PMT_DT", "payment_date")
    df = parse_date_col(df, "PMT_RECV_DT", "received_date")
    df = parse_date_col(df, "PMT_PROC_DT", "processed_date")
    df = parse_timestamp_col(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "PMT_UPDT_DT", "updated_at")

    # Expand type and status codes
    df = expand_status(df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)
    df = expand_status(df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # Derive partition columns
    df = df.withColumn("payment_year", F.year(F.col("payment_date")))
    df = df.withColumn("payment_month", F.month(F.col("payment_date")))

    # Add migration metadata
    df = df.withColumn("_migration_source", F.lit(SOURCE_TABLE))
    df = df.withColumn("_migrated_at", F.current_timestamp())

    # Select final columns
    df = df.select(
        "legacy_payment_seq", "loan_account_number",
        "payment_date", "total_amount",
        "principal_amount", "interest_amount", "escrow_amount", "late_fee",
        "type", "status",
        "received_date", "processed_date",
        "created_at", "updated_at",
        "payment_year", "payment_month",
        "_migration_source", "_migrated_at",
    )

    return df


def load(df: DataFrame, mode: str = "overwrite"):
    """Write transformed payment DataFrame to Delta Lake."""
    df.write.format("delta").mode(mode).partitionBy("payment_year", "payment_month").saveAsTable(TARGET_TABLE)
    logger.info("Wrote %d rows to %s", df.count(), TARGET_TABLE)


def run(spark: SparkSession, source_path: str, source_format: str = "csv",
        write_mode: str = "overwrite"):
    """Execute the full payment ingestion pipeline.

    Returns:
        Tuple of (valid_df, quarantine_df).
    """
    logger.info("=== Starting payment ingestion from %s ===", source_path)

    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform(raw_df)

    valid_df, quarantine_df = quarantine_nulls(transformed_df, REQUIRED_COLS, TARGET_TABLE)
    src_count, tgt_count = log_row_counts(raw_df, valid_df, TARGET_TABLE)

    load(valid_df, mode=write_mode)

    logger.info("=== Payment ingestion complete: %d/%d rows loaded ===", tgt_count, src_count)
    return valid_df, quarantine_df
