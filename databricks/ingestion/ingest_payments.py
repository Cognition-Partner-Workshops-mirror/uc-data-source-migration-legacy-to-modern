"""
PySpark ingestion script: CDW_PMT_HIST → loan_warehouse.payments

Reads legacy payment history data from CSV/Parquet source files, applies all
transformations defined in data/mappings/column_mappings.md, and writes
to the Delta Lake payments table.

Key transformations:
  - LN_ACCT_NBR resolved to loan_account_id via lookup against loan_accounts table
  - PMT_SEQ_NBR preserved as legacy_payment_id for audit trail
  - All amount VARCHARs → DECIMAL, all date VARCHARs → DATE
  - PMT_TYP_CD expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
  - PMT_STAT_CD expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
  - payment_year extracted from payment_date for partitioning

Prerequisites:
  - loan_accounts table must be populated first (for FK lookup)

Usage:
  Run as a Databricks notebook or submit via spark-submit.
"""

import logging
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
)

# Import shared transformation utilities
from transform_utils import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    expand_status_col,
    add_etl_metadata,
    tag_malformed_rows,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

# =============================================================================
# Configuration
# =============================================================================
SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_pmt_hist/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
WRITE_MODE = "overwrite"

# =============================================================================
# Logging setup
# =============================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_payments")

# =============================================================================
# Legacy source schema — all VARCHAR columns as StringType
# =============================================================================
LEGACY_SCHEMA = StructType([
    StructField("PMT_SEQ_NBR", StringType(), True),
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("PMT_DT", StringType(), True),
    StructField("PMT_AMT", StringType(), True),
    StructField("PMT_PRIN_AMT", StringType(), True),
    StructField("PMT_INT_AMT", StringType(), True),
    StructField("PMT_ESCROW_AMT", StringType(), True),
    StructField("PMT_LATE_FEE", StringType(), True),
    StructField("PMT_TYP_CD", StringType(), True),
    StructField("PMT_STAT_CD", StringType(), True),
    StructField("PMT_RECV_DT", StringType(), True),
    StructField("PMT_PROC_DT", StringType(), True),
    StructField("PMT_CRET_DT", StringType(), True),
    StructField("PMT_UPDT_DT", StringType(), True),
])


def read_source(spark):
    """Read the legacy CDW_PMT_HIST data from the configured source path and format."""
    logger.info(f"Reading source data from {SOURCE_PATH} (format={SOURCE_FORMAT})")
    if SOURCE_FORMAT == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .schema(LEGACY_SCHEMA)
            .csv(SOURCE_PATH)
        )
    elif SOURCE_FORMAT == "parquet":
        df = spark.read.schema(LEGACY_SCHEMA).parquet(SOURCE_PATH)
    else:
        raise ValueError(f"Unsupported source format: {SOURCE_FORMAT}")

    record_count = df.count()
    logger.info(f"Read {record_count} records from legacy CDW_PMT_HIST")
    return df


def resolve_foreign_keys(spark, df):
    """
    Resolve legacy LN_ACCT_NBR to loan_account_id via lookup against the
    already-populated loan_accounts table.

    Records with unresolvable FKs are logged but NOT dropped.
    """
    logger.info("Resolving foreign key: LN_ACCT_NBR → loan_account_id")

    # Load loan account lookup (account_number → loan_account_id)
    loan_lookup = (
        spark.table("loan_warehouse.loan_accounts")
        .select(
            F.col("account_number").alias("_acct_nbr"),
            F.col("loan_account_id").alias("_resolved_loan_account_id"),
        )
    )

    # Left join to resolve loan account FK
    df_with_fk = df.join(
        loan_lookup,
        F.trim(df["LN_ACCT_NBR"]) == loan_lookup["_acct_nbr"],
        "left",
    )

    # Log unresolved FKs
    unresolved = df_with_fk.filter(F.col("_resolved_loan_account_id").isNull()).count()
    if unresolved > 0:
        logger.warning(f"{unresolved} payments have unresolvable LN_ACCT_NBR")

    return df_with_fk


def transform(spark, df):
    """
    Apply all column mappings and transformations to convert legacy payment
    data to the modern payments schema.
    """
    logger.info("Applying transformations for CDW_PMT_HIST → payments")

    # Tag rows with potential quality issues
    df_tagged = tag_malformed_rows(df, [
        (F.col("PMT_SEQ_NBR").isNull(), "NULL_PMT_SEQ"),
        (F.col("LN_ACCT_NBR").isNull(), "NULL_ACCT_NBR"),
        (F.col("PMT_DT").isNull(), "NULL_PMT_DT"),
        (F.col("PMT_AMT").isNull(), "NULL_PMT_AMT"),
        (F.col("PMT_DT").isNotNull() &
         ~F.col("PMT_DT").rlike(r"^\d{2}/\d{2}/\d{4}$"), "MALFORMED_PMT_DT"),
    ])

    # Log flagged records
    flagged = df_tagged.filter(F.col("_quality_flags").isNotNull())
    flagged_count = flagged.count()
    if flagged_count > 0:
        logger.warning(
            f"Found {flagged_count} records with quality issues in CDW_PMT_HIST. "
            "Records preserved — not dropped."
        )
        flagged.select("PMT_SEQ_NBR", "_quality_flags").show(truncate=False)

    # Resolve foreign keys via lookup
    df_with_fk = resolve_foreign_keys(spark, df_tagged)

    # Apply column transformations per the mapping document
    transformed = df_with_fk.select(
        # Surrogate key
        F.monotonically_increasing_id().alias("payment_id"),

        # Legacy identifier preserved for audit trail
        F.trim(F.col("PMT_SEQ_NBR")).alias("legacy_payment_id"),

        # Resolved foreign key
        F.col("_resolved_loan_account_id").alias("loan_account_id"),

        # Payment date: parse MM/DD/YYYY → DATE
        parse_date_col("PMT_DT", "payment_date"),

        # Amount fields: remove commas, parse to decimal
        parse_amount_col("PMT_AMT", "total_amount", precision=10, scale=2),
        parse_amount_col("PMT_PRIN_AMT", "principal_amount", precision=10, scale=2),
        parse_amount_col("PMT_INT_AMT", "interest_amount", precision=10, scale=2),
        parse_amount_col("PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2),
        parse_amount_col("PMT_LATE_FEE", "late_fee", precision=10, scale=2),

        # Type and status: expand abbreviations
        expand_status_col("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        expand_status_col("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),

        # Processing dates: parse MM/DD/YYYY → DATE
        parse_date_col("PMT_RECV_DT", "received_date"),
        parse_date_col("PMT_PROC_DT", "processed_date"),

        # Audit timestamps: parse MM/DD/YYYY → TIMESTAMP
        parse_timestamp_col("PMT_CRET_DT", "created_at"),
        parse_timestamp_col("PMT_UPDT_DT", "updated_at"),
    )

    # Add ETL metadata
    transformed = add_etl_metadata(transformed, "CDW_PMT_HIST")

    # Add partition column: extract year from payment_date
    transformed = transformed.withColumn(
        "payment_year",
        F.year(F.col("payment_date"))
    )

    logger.info(f"Transformation complete. Output row count: {transformed.count()}")
    return transformed


def write_target(df):
    """
    Write the transformed payments DataFrame to the Delta Lake target table.
    Partitioned by payment_year as defined in the DDL.
    """
    logger.info(f"Writing to {TARGET_TABLE} (mode={WRITE_MODE}), partitioned by payment_year")
    (
        df.write
        .format("delta")
        .mode(WRITE_MODE)
        .option("mergeSchema", "true")
        .partitionBy("payment_year")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info(f"Successfully wrote data to {TARGET_TABLE}")


def main():
    """Main entry point: read → transform → write for payments ingestion."""
    spark = SparkSession.builder.appName("Ingest_CDW_PMT_HIST").getOrCreate()
    logger.info("=" * 70)
    logger.info("Starting payment ingestion: CDW_PMT_HIST → loan_warehouse.payments")
    logger.info("=" * 70)

    try:
        source_df = read_source(spark)
        target_df = transform(spark, source_df)
        write_target(target_df)
        logger.info("Payment ingestion completed successfully")
    except Exception as e:
        logger.error(f"Payment ingestion FAILED: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
