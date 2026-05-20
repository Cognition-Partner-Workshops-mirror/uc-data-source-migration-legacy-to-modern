"""
ingest_payments.py — PySpark ingestion script for the payments fact table.

Reads from the legacy CDW_PMT_HIST source (simulated as CSV/Parquet), applies
all required transformations per column_mappings.md, and writes to the Delta Lake
loan_management.payments table.

Source: CDW_PMT_HIST (legacy all-VARCHAR payment history)
Target: loan_management.payments (typed Delta Lake table)

Transformations:
  - PMT_SEQ_NBR preserved as legacy_payment_id for reconciliation
  - LN_ACCT_NBR kept as loan_account_number for FK resolution
  - All amount VARCHARs (commas stripped) → DECIMAL
  - All date VARCHARs (MM/DD/YYYY) → DATE / TIMESTAMP
  - PMT_TYP_CD expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
  - PMT_STAT_CD expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
  - payment_year derived from payment_date for partitioning
"""

from pyspark.sql import SparkSession, functions as F

from common_transforms import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    expand_status_col,
    add_parse_error_flags,
    log_transformation_summary,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

# =============================================================================
# Configuration — update these paths for your Databricks environment
# =============================================================================
SOURCE_PATH = "/mnt/legacy-data/cdw_pmt_hist/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_management.payments"


def read_source(spark, path=SOURCE_PATH, fmt=SOURCE_FORMAT):
    """
    Read the legacy CDW_PMT_HIST source data.
    All columns are read as strings to match the legacy all-VARCHAR schema.
    """
    if fmt == "csv":
        return (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .csv(path)
        )
    elif fmt == "parquet":
        return spark.read.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform_payments(df):
    """
    Apply all transformations to convert legacy CDW_PMT_HIST columns
    to the modern payments schema per column_mappings.md.
    """
    # Rename direct-copy / FK columns
    transformed = (
        df
        .withColumnRenamed("PMT_SEQ_NBR", "legacy_payment_id")
        .withColumnRenamed("LN_ACCT_NBR", "loan_account_number")
    )

    # Parse all amount columns: comma-formatted VARCHARs → DECIMAL(10,2)
    transformed = parse_amount_col(
        transformed, "PMT_AMT", "total_amount", precision=10, scale=2
    )
    transformed = parse_amount_col(
        transformed, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2
    )
    transformed = parse_amount_col(
        transformed, "PMT_INT_AMT", "interest_amount", precision=10, scale=2
    )
    transformed = parse_amount_col(
        transformed, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2
    )
    transformed = parse_amount_col(
        transformed, "PMT_LATE_FEE", "late_fee", precision=10, scale=2
    )

    # Parse date columns: MM/DD/YYYY → DATE
    transformed = parse_date_col(transformed, "PMT_DT", "payment_date")
    transformed = parse_date_col(transformed, "PMT_RECV_DT", "received_date")
    transformed = parse_date_col(transformed, "PMT_PROC_DT", "processed_date")

    # Parse created/updated timestamps
    transformed = parse_timestamp_col(transformed, "PMT_CRET_DT", "created_at")
    transformed = parse_timestamp_col(transformed, "PMT_UPDT_DT", "updated_at")

    # Expand payment type code: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
    transformed = expand_status_col(
        transformed, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP
    )

    # Expand payment status code: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
    transformed = expand_status_col(
        transformed, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP
    )

    # Derive payment_year from payment_date for partitioning
    transformed = transformed.withColumn(
        "payment_year", F.year(F.col("payment_date"))
    )

    # Add parse error flags for data quality monitoring
    transformed = add_parse_error_flags(
        transformed,
        date_cols=[
            ("PMT_DT", "payment_date"),
            ("PMT_RECV_DT", "received_date"),
            ("PMT_PROC_DT", "processed_date"),
            ("PMT_CRET_DT", "created_at"),
            ("PMT_UPDT_DT", "updated_at"),
        ],
        amount_cols=[
            ("PMT_AMT", "total_amount"),
            ("PMT_PRIN_AMT", "principal_amount"),
            ("PMT_INT_AMT", "interest_amount"),
            ("PMT_ESCROW_AMT", "escrow_amount"),
            ("PMT_LATE_FEE", "late_fee"),
        ],
    )

    # Select only modern schema columns
    result = transformed.select(
        "legacy_payment_id",
        "loan_account_number",
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
        "_parse_errors",
    )

    return result


def write_target(df, table=TARGET_TABLE, mode="overwrite"):
    """
    Write the transformed payment data to the Delta Lake target table.
    Partitioned by payment_year (configured in the DDL).
    """
    (
        df
        .drop("_parse_errors")
        .write
        .format("delta")
        .mode(mode)
        .option("partitionOverwriteMode", "dynamic")
        .saveAsTable(table)
    )


def run(spark=None):
    """
    Main entry point: read legacy payment data, transform, validate, and write.
    Returns a summary dict with row counts for reconciliation.
    """
    if spark is None:
        spark = SparkSession.builder.appName("IngestPayments").getOrCreate()

    print("=" * 60)
    print("Starting payment ingestion from CDW_PMT_HIST")
    print("=" * 60)

    # Step 1: Read legacy source
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"Source rows read: {source_count}")

    # Step 2: Transform to modern schema
    transformed_df = transform_payments(source_df)

    # Step 3: Log transformation summary
    total, errors = log_transformation_summary(transformed_df, "payments")

    # Step 4: Write to Delta Lake target
    write_target(transformed_df)
    print(f"Successfully wrote {total} rows to {TARGET_TABLE}")

    return {"source_count": source_count, "target_count": total, "error_count": errors}


if __name__ == "__main__":
    run()
