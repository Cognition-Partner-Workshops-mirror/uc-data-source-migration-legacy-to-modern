"""
PySpark Ingestion Script: Payments
Source: CDW_PMT_HIST (legacy CSV/Parquet extract)
Target: loan_warehouse.payments (Delta Lake)

Transformations applied:
  - Resolve LN_ACCT_NBR -> loan_account_id via lookup to loan_warehouse.loan_accounts
  - Parse amount strings (commas) -> DecimalType
  - Parse date strings (MM/DD/YYYY) -> DateType / TimestampType
  - Expand PMT_TYP_CD (REG/EXT/PRT/PRE) -> type (Regular/Extra/Partial/Prepayment)
  - Expand PMT_STAT_CD (PST/REV/NSF/PND) -> status (Posted/Reversed/NSF/Pending)

Prerequisites:
  - loan_accounts table must be populated first (for FK resolution)
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from utils import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    col_expand_status,
    col_parse_amount,
    col_parse_date,
    col_parse_timestamp,
    log_row_counts,
    quarantine_malformed_rows,
    tag_migration_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/legacy-extracts/CDW_PMT_HIST/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_TABLE = "loan_warehouse._quarantine_payments"
LOAN_ACCOUNT_TABLE = "loan_warehouse.loan_accounts"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "quote": '"',
    "escape": '"',
}


def read_source(spark: SparkSession):
    """Read the legacy CDW_PMT_HIST extract."""
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for key, val in CSV_OPTIONS.items():
            reader = reader.option(key, val)
    return reader.load(SOURCE_PATH)


def resolve_loan_account_ids(spark: SparkSession):
    """Load the loan account lookup table (account_number -> loan_account_id)."""
    return (
        spark.table(LOAN_ACCOUNT_TABLE)
        .select(
            F.col("loan_account_id").alias("_resolved_loan_account_id"),
            F.col("account_number").alias("_acct_number"),
        )
    )


def transform(df, loan_account_lookup):
    """Apply all column mappings, type conversions, and FK resolution."""

    # Step 1: Column-level transformations
    transformed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_id"),
        F.col("LN_ACCT_NBR").alias("_acct_number"),
        col_parse_date("PMT_DT", "payment_date"),
        col_parse_amount("PMT_AMT", "total_amount", precision=10, scale=2),
        col_parse_amount("PMT_PRIN_AMT", "principal_amount", precision=10, scale=2),
        col_parse_amount("PMT_INT_AMT", "interest_amount", precision=10, scale=2),
        col_parse_amount("PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2),
        col_parse_amount("PMT_LATE_FEE", "late_fee", precision=10, scale=2),
        col_expand_status("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        col_expand_status("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
        col_parse_date("PMT_RECV_DT", "received_date"),
        col_parse_date("PMT_PROC_DT", "processed_date"),
        col_parse_timestamp("PMT_CRET_DT", "created_at"),
        col_parse_timestamp("PMT_UPDT_DT", "updated_at"),
    )

    # Step 2: Resolve loan account FK
    transformed = transformed.join(
        loan_account_lookup,
        on="_acct_number",
        how="left",
    )

    # Step 3: Rename resolved ID and drop join key
    transformed = (
        transformed
        .withColumnRenamed("_resolved_loan_account_id", "loan_account_id")
        .drop("_acct_number")
    )

    # Log unresolved FK references
    unresolved_accounts = transformed.filter(F.col("loan_account_id").isNull()).count()
    if unresolved_accounts > 0:
        print(f"[MIGRATION] WARNING: {unresolved_accounts} payments have unresolved loan account references")

    return transformed


def run(spark: SparkSession):
    """Execute the full payment ingestion pipeline."""
    print(f"[MIGRATION] Starting payment ingestion from {SOURCE_PATH}")

    # Read source
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"[MIGRATION] Read {source_count} rows from CDW_PMT_HIST")

    # Load FK lookup table
    loan_account_lookup = resolve_loan_account_ids(spark)

    # Transform
    transformed_df = transform(source_df, loan_account_lookup)

    # Add migration metadata
    transformed_df = tag_migration_metadata(transformed_df, "CDW_PMT_HIST")

    # Quarantine rows with NULL in required fields
    required_cols = ["loan_account_id", "payment_date", "total_amount", "type", "status"]
    valid_df, quarantine_df = quarantine_malformed_rows(
        transformed_df, required_cols, "CDW_PMT_HIST", spark
    )

    # Write quarantined rows
    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        print(f"[MIGRATION] WARNING: {quarantine_count} rows quarantined for payments")
        quarantine_df.write.format("delta").mode("append").saveAsTable(QUARANTINE_TABLE)

    # Write to Delta Lake target (no dedup needed — payments are immutable events)
    target_count = valid_df.count()
    valid_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    # Reconciliation
    stats = log_row_counts(spark, source_count, target_count, quarantine_count, "payments")
    print(f"[MIGRATION] Payment ingestion complete")
    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_Payments").getOrCreate()
    try:
        run(spark)
    finally:
        spark.stop()
