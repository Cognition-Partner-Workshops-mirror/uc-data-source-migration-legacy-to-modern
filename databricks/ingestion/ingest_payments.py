"""
PySpark ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment history table and transforms all-VARCHAR columns into
properly typed Delta Lake columns per column_mappings.md.

Key transformations:
- Resolve loan_account_id FK via LN_ACCT_NBR -> loan_accounts.account_number lookup
- Parse all amount strings (comma-formatted) to DecimalType
- Parse all date strings (MM/DD/YYYY) to DateType/TimestampType
- Expand payment type codes (REG -> REGULAR, EXT -> EXTRA, PRT -> PARTIAL, PRE -> PREPAYMENT)
- Expand payment status codes (PST -> POSTED, REV -> REVERSED, NSF -> NSF, PND -> PENDING)
- Derive payment_year partition column from payment_date
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    read_legacy_csv,
    read_legacy_parquet,
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    expand_status_code,
    add_pipeline_metadata,
    log_parse_errors,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/cdw/CDW_PMT_HIST/"
TARGET_TABLE = "loan_warehouse.payments"
SOURCE_FORMAT = "csv"


def read_source(spark: SparkSession) -> DataFrame:
    """Read the legacy payment history data from the landing zone."""
    if SOURCE_FORMAT == "parquet":
        return read_legacy_parquet(spark, SOURCE_PATH)
    return read_legacy_csv(spark, SOURCE_PATH)


def resolve_loan_account_ids(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Resolve legacy LN_ACCT_NBR strings to modern loan_account surrogate keys.

    Joins against the already-loaded loan_accounts table using account_number.
    Unresolved account numbers are flagged (orphaned payments) for quality reporting.
    """
    accounts = spark.table("loan_warehouse.loan_accounts").select(
        F.col("id").alias("loan_account_id"),
        F.col("account_number"),
    )
    joined = df.join(
        accounts,
        df["LN_ACCT_NBR"] == accounts["account_number"],
        "left"
    )
    # Flag rows where the loan account lookup failed (orphaned payments)
    joined = joined.withColumn(
        "loan_account_id_unresolved",
        F.col("loan_account_id").isNull() & F.col("LN_ACCT_NBR").isNotNull()
    )
    return joined.drop("account_number")


def transform(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Apply all transformations from CDW_PMT_HIST to modern payments schema.

    Must be called after loan_accounts table is loaded because FK resolution
    depends on the target table existing.
    """
    # --- Step 1: Resolve FK references (loan_account_id) ---
    resolved = resolve_loan_account_ids(spark, df)

    # --- Step 2: Rename legacy payment ID column ---
    resolved = resolved.withColumnRenamed("PMT_SEQ_NBR", "legacy_payment_id")

    # --- Step 3: Parse amount strings to DecimalType ---
    resolved = parse_legacy_amount(resolved, "PMT_AMT", "total_amount", precision=10, scale=2)
    resolved = parse_legacy_amount(resolved, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
    resolved = parse_legacy_amount(resolved, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
    resolved = parse_legacy_amount(resolved, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
    resolved = parse_legacy_amount(resolved, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)

    # --- Step 4: Parse date strings to DateType ---
    resolved = parse_legacy_date(resolved, "PMT_DT", "payment_date")
    resolved = parse_legacy_date(resolved, "PMT_RECV_DT", "received_date")
    resolved = parse_legacy_date(resolved, "PMT_PROC_DT", "processed_date")

    # --- Step 5: Parse audit timestamps ---
    resolved = parse_legacy_timestamp(resolved, "PMT_CRET_DT", "created_at")
    resolved = parse_legacy_timestamp(resolved, "PMT_UPDT_DT", "updated_at")

    # --- Step 6: Expand payment type code (REG -> REGULAR, etc.) ---
    resolved = expand_status_code(resolved, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)

    # --- Step 7: Expand payment status code (PST -> POSTED, etc.) ---
    resolved = expand_status_code(resolved, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # --- Step 8: Derive partition column (payment_year from payment_date) ---
    resolved = resolved.withColumn(
        "payment_year",
        F.year(F.col("payment_date"))
    )

    # --- Step 9: Add pipeline metadata ---
    resolved = add_pipeline_metadata(resolved, "CDW_PMT_HIST")

    # --- Step 10: Select final columns ---
    result = resolved.select(
        "legacy_payment_id",
        "loan_account_id",
        "payment_date",
        "received_date",
        "processed_date",
        "total_amount",
        "principal_amount",
        "interest_amount",
        "escrow_amount",
        "late_fee",
        "type",
        "status",
        "created_at",
        "updated_at",
        "payment_year",
        "_ingested_at",
        "_source_system",
    )

    return result


def load(df: DataFrame):
    """Write the transformed payment data to the Delta Lake target table."""
    (
        df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("payment_year")
        .saveAsTable(TARGET_TABLE)
    )


def run(spark: SparkSession):
    """Main entry point: read -> transform (with FK resolution) -> load."""
    raw_df = read_source(spark)
    transformed_df = transform(spark, raw_df)

    # Log parse/resolution issues before loading
    log_parse_errors(transformed_df, "payments", [
        "loan_account_id_unresolved",
        "total_amount_parse_error",
        "principal_amount_parse_error",
        "interest_amount_parse_error",
        "escrow_amount_parse_error",
        "late_fee_parse_error",
        "payment_date_parse_error",
        "received_date_parse_error",
        "processed_date_parse_error",
        "type_unmapped",
        "status_unmapped",
        "created_at_parse_error",
        "updated_at_parse_error",
    ])

    load(transformed_df)
    print(f"[payments] Ingestion complete. Rows written: {transformed_df.count()}")


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_PMT_HIST_Ingestion").getOrCreate()
    run(spark)
