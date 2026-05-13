"""
Ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment history table (simulated as CSV/Parquet source)
and transforms it into the modern payments Delta Lake table.

Key transformations:
  - Resolve loan_account_id FK via LN_ACCT_NBR -> loan_accounts.account_number
  - Parse all amount strings (comma-formatted) to DECIMAL
  - Parse all date strings (MM/DD/YYYY) to DATE / TIMESTAMP
  - Expand payment type codes: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment
  - Expand payment status codes: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending
  - Derive partition columns: payment_year, payment_month from payment_date
  - Preserve legacy PMT_SEQ_NBR as external_payment_id for traceability
  - Add surrogate payment_id and ingestion metadata
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
import logging

from transformations import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    expand_status_col,
    add_ingestion_metadata,
    log_bad_records,
    drop_flag_columns,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

logger = logging.getLogger("cdw_migration.ingest_payments")

DEFAULT_SOURCE_PATH = "/mnt/landing/cdw/CDW_PMT_HIST"
DEFAULT_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"


def read_source(spark: SparkSession, source_path: str = DEFAULT_SOURCE_PATH,
                source_format: str = DEFAULT_SOURCE_FORMAT) -> DataFrame:
    """Read legacy CDW_PMT_HIST data from the landing zone."""
    if source_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "")
            .option("emptyValue", "")
            .csv(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from %s (%s)", df.count(), source_path, source_format)
    return df


def resolve_loan_account_fk(df: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Resolve the loan account foreign key by looking up loan_account_id
    from loan_warehouse.loan_accounts using LN_ACCT_NBR -> account_number.

    Unresolved references are flagged with '_unresolved_loan_account_id'.
    """
    accounts_df = spark.table("loan_warehouse.loan_accounts").select(
        F.col("loan_account_id").alias("_resolved_loan_account_id"),
        F.col("account_number").alias("_acct_number"),
    )
    df = df.join(
        accounts_df,
        df["LN_ACCT_NBR"] == accounts_df["_acct_number"],
        "left"
    )
    # Flag unresolved FK references
    df = df.withColumn(
        "_unresolved_loan_account_id",
        F.when(
            F.col("_resolved_loan_account_id").isNull() & F.col("LN_ACCT_NBR").isNotNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    df = df.withColumn("loan_account_id", F.col("_resolved_loan_account_id"))
    # Clean up join helper columns
    df = df.drop("_resolved_loan_account_id", "_acct_number")
    return df


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Apply all transformations to convert legacy CDW_PMT_HIST columns
    to the modern payments schema.
    """
    # --- Generate surrogate key ---
    df = df.withColumn("payment_id", F.monotonically_increasing_id() + 1)

    # --- Preserve legacy sequence number for traceability ---
    df = df.withColumnRenamed("PMT_SEQ_NBR", "external_payment_id")

    # --- Resolve loan account foreign key ---
    df = resolve_loan_account_fk(df, spark)

    # --- Parse financial amounts: comma-formatted strings -> DECIMAL ---
    df = parse_amount_col(df, "PMT_AMT", "total_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)

    # --- Parse dates: MM/DD/YYYY -> DATE ---
    df = parse_date_col(df, "PMT_DT", "payment_date")
    df = parse_date_col(df, "PMT_RECV_DT", "received_date")
    df = parse_date_col(df, "PMT_PROC_DT", "processed_date")

    # --- Parse audit timestamps: MM/DD/YYYY -> TIMESTAMP ---
    df = parse_timestamp_col(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "PMT_UPDT_DT", "updated_at")

    # --- Expand payment type codes ---
    # REG -> Regular, EXT -> Extra, PRT -> Partial, PRE -> Prepayment
    df = expand_status_col(df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)

    # --- Expand payment status codes ---
    # PST -> Posted, REV -> Reversed, NSF -> NSF, PND -> Pending
    df = expand_status_col(df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # --- Derive partition columns from payment_date ---
    df = df.withColumn("payment_year", F.year(F.col("payment_date")))
    df = df.withColumn("payment_month", F.month(F.col("payment_date")))

    # --- Add ingestion metadata ---
    df = add_ingestion_metadata(df, "CDW_PMT_HIST")

    # --- Log data quality issues ---
    log_bad_records(df, TARGET_TABLE)

    # Log unresolved FK counts
    unresolved_accounts = df.filter(F.col("_unresolved_loan_account_id") == True).count()  # noqa: E712
    if unresolved_accounts > 0:
        logger.warning("[%s] %d records with unresolved loan_account FK", TARGET_TABLE, unresolved_accounts)

    # --- Drop flag columns ---
    df = drop_flag_columns(df)
    df = df.drop("_unresolved_loan_account_id")

    # Select target columns in correct order
    target_columns = [
        "payment_id", "external_payment_id", "loan_account_id",
        "payment_date", "total_amount", "principal_amount",
        "interest_amount", "escrow_amount", "late_fee",
        "type", "status", "received_date", "processed_date",
        "created_at", "updated_at", "_ingestion_ts", "_source_system",
        # Partition columns
        "payment_year", "payment_month",
    ]
    df = df.select(*target_columns)

    return df


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    """Write the transformed payments DataFrame to the Delta Lake table."""
    (
        df.write
        .format("delta")
        .mode(mode)
        .partitionBy("payment_year", "payment_month")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info("Wrote %d rows to %s", df.count(), TARGET_TABLE)


def run(spark: SparkSession, source_path: str = DEFAULT_SOURCE_PATH,
        source_format: str = DEFAULT_SOURCE_FORMAT) -> DataFrame:
    """
    Execute the full payments ingestion pipeline.
    REQUIRES: loan_accounts table must be populated first.
    """
    logger.info("Starting payments ingestion from %s", source_path)
    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform(raw_df, spark)
    write_target(transformed_df)
    logger.info("Payments ingestion complete.")
    return transformed_df


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Payments_Ingestion").getOrCreate()
    try:
        src_path = dbutils.widgets.get("source_path")  # noqa: F821
    except Exception:
        src_path = DEFAULT_SOURCE_PATH
    try:
        src_fmt = dbutils.widgets.get("source_format")  # noqa: F821
    except Exception:
        src_fmt = DEFAULT_SOURCE_FORMAT

    run(spark, src_path, src_fmt)
