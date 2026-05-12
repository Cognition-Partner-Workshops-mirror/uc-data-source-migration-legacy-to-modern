"""
Ingestion script: CDW_PMT_HIST → loan_warehouse.payments

Reads the legacy payment history table (simulated as CSV/Parquet),
applies all transformations from column_mappings.md, resolves
FK references to loan_accounts, and writes to the modern Delta Lake
payments table.

Execution order: Run FOURTH (last) — depends on loan_accounts being
loaded first for FK resolution.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    expand_payment_type,
    expand_payment_status,
)

# =============================================================================
# Configuration
# =============================================================================
LEGACY_SOURCE_PATH = "/mnt/legacy-data/CDW_PMT_HIST"
LEGACY_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_PATH = "/mnt/migration/quarantine/payments"


def read_legacy_payments(spark: SparkSession) -> DataFrame:
    """Read legacy payment history data. All columns as STRING."""
    return (
        spark.read
        .format(LEGACY_SOURCE_FORMAT)
        .option("header", "true")
        .option("inferSchema", "false")
        .load(LEGACY_SOURCE_PATH)
    )


def transform_payments(df: DataFrame, loan_accounts_df: DataFrame) -> DataFrame:
    """
    Apply all transformations from column_mappings.md § CDW_PMT_HIST → payments.

    Key operations:
    - Resolves LN_ACCT_NBR → loan_account_id via loan_accounts.account_number lookup
    - Parses all VARCHAR amounts to DECIMAL
    - Parses all VARCHAR dates to DATE/TIMESTAMP
    - Expands PMT_TYP_CD and PMT_STAT_CD codes
    """
    # Build lookup for FK resolution
    loan_lookup = loan_accounts_df.select(
        F.col("loan_account_id"),
        F.col("account_number").alias("_acct_nbr")
    )

    resolved = df.join(loan_lookup, df["LN_ACCT_NBR"] == loan_lookup["_acct_nbr"], "left")

    transformed = resolved.select(
        # Legacy ID preserved for audit traceability
        F.col("PMT_SEQ_NBR").alias("legacy_payment_id"),

        # FK resolution
        F.col("loan_account_id"),

        # Date parsing
        parse_legacy_date(F.col("PMT_DT")).alias("payment_date"),

        # Amount parsing: all VARCHAR with commas → DECIMAL
        parse_legacy_amount(F.col("PMT_AMT"), 10, 2).alias("total_amount"),
        parse_legacy_amount(F.col("PMT_PRIN_AMT"), 10, 2).alias("principal_amount"),
        parse_legacy_amount(F.col("PMT_INT_AMT"), 10, 2).alias("interest_amount"),
        parse_legacy_amount(F.col("PMT_ESCROW_AMT"), 10, 2).alias("escrow_amount"),
        parse_legacy_amount(F.col("PMT_LATE_FEE"), 10, 2).alias("late_fee"),

        # Status/type expansion
        expand_payment_type(F.col("PMT_TYP_CD")).alias("type"),
        expand_payment_status(F.col("PMT_STAT_CD")).alias("status"),

        # Additional date fields
        parse_legacy_date(F.col("PMT_RECV_DT")).alias("received_date"),
        parse_legacy_date(F.col("PMT_PROC_DT")).alias("processed_date"),
        parse_legacy_timestamp(F.col("PMT_CRET_DT")).alias("created_at"),
        parse_legacy_timestamp(F.col("PMT_UPDT_DT")).alias("updated_at"),
    )

    return transformed


def quarantine_invalid_records(df: DataFrame) -> tuple:
    """
    Separate valid from invalid records.
    Required: legacy_payment_id, loan_account_id (FK resolved), payment_date, total_amount.
    """
    required_fields = ["legacy_payment_id", "loan_account_id", "payment_date", "total_amount"]

    null_condition = F.lit(False)
    for field in required_fields:
        null_condition = null_condition | F.col(field).isNull()

    valid_df = df.filter(~null_condition)
    quarantine_df = df.filter(null_condition)
    return valid_df, quarantine_df


def run_ingestion():
    """Main ingestion entry point. Requires loan_accounts to be loaded first."""
    spark = SparkSession.builder.appName("Ingest CDW_PMT_HIST → payments").getOrCreate()

    print("=" * 60)
    print("INGESTION: CDW_PMT_HIST → loan_warehouse.payments")
    print("=" * 60)

    # Read lookup table
    loan_accounts_df = spark.table("loan_warehouse.loan_accounts")
    print(f"Loan accounts loaded for FK resolution: {loan_accounts_df.count()}")

    legacy_df = read_legacy_payments(spark)
    source_count = legacy_df.count()
    print(f"Source records read: {source_count}")

    transformed_df = transform_payments(legacy_df, loan_accounts_df)
    valid_df, quarantine_df = quarantine_invalid_records(transformed_df)
    quarantine_count = quarantine_df.count()
    valid_count = valid_df.count()

    if quarantine_count > 0:
        print(f"WARNING: {quarantine_count} record(s) quarantined (likely unresolved loan FKs)")
        quarantine_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)
    else:
        print("All records passed validation and FK resolution")

    valid_df.write.mode("overwrite").format("delta").saveAsTable(TARGET_TABLE)
    print(f"Target records written: {valid_count}")
    print(f"Reconciliation: {source_count} → {valid_count} (+{quarantine_count} quarantined)")


if __name__ == "__main__":
    run_ingestion()
