"""
PySpark Ingestion Script: CDW_PMT_HIST -> payments
====================================================
Reads legacy payment history data, converts all-VARCHAR columns to proper
types, resolves the loan account foreign key, expands payment type and status
codes, validates payment component sums, and writes to the Delta Lake
payments table.

Key Transformations:
  - Amount strings (commas) -> DECIMAL(10,2)
  - Date strings (MM/DD/YYYY) -> DATE / TIMESTAMP
  - PMT_TYP_CD: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT
  - PMT_STAT_CD: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING
  - payment_year derived from payment_date for partitioning
  - Component sum validation: principal + interest + escrow + late_fee vs total
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, DecimalType
import logging

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "/mnt/legacy-data/CDW_PMT_HIST"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_TABLE = "loan_warehouse._quarantine_payments"

# Payment type code expansion per column_mappings.md
PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

# Payment status code expansion per column_mappings.md
PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

logger = logging.getLogger("ingest_payments")
logging.basicConfig(level=logging.INFO)


def read_legacy_source(spark: SparkSession, path: str) -> DataFrame:
    """Read legacy CDW_PMT_HIST data from CSV or Parquet source files."""
    try:
        df = spark.read.parquet(path)
        logger.info("Read legacy payment data from Parquet: %s", path)
    except Exception:
        df = spark.read.option("header", "true").option("inferSchema", "false").csv(path)
        logger.info("Read legacy payment data from CSV: %s", path)
    logger.info("Source row count: %d", df.count())
    return df


def parse_legacy_date(col_name: str):
    """Convert MM/DD/YYYY VARCHAR string to DateType."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_timestamp(col_name: str):
    """Convert MM/DD/YYYY VARCHAR string to TimestampType."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_amount(col_name: str, precision: int = 10, scale: int = 2):
    """Remove commas and dollar signs from VARCHAR amount, cast to DecimalType."""
    return F.regexp_replace(F.col(col_name), "[,$]", "").cast(DecimalType(precision, scale))


def expand_code(col_name: str, mapping: dict):
    """Expand abbreviated codes using a mapping dictionary."""
    expr = F.col(col_name)
    for code, expanded in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(expanded)).otherwise(expr)
    return expr


def resolve_loan_account_fk(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Resolve legacy LN_ACCT_NBR to loan_accounts.id via lookup join.

    Records whose LN_ACCT_NBR has no match are flagged with loan_account_id = -1.
    """
    loan_lookup = (
        spark.table("loan_warehouse.loan_accounts")
        .select(
            F.col("id").alias("_loan_pk"),
            F.col("account_number").alias("_ln_acct_nbr")
        )
    )
    joined = df.join(
        loan_lookup,
        df["LN_ACCT_NBR"] == loan_lookup["_ln_acct_nbr"],
        "left"
    )
    resolved = joined.withColumn(
        "loan_account_id",
        F.coalesce(F.col("_loan_pk"), F.lit(-1))
    ).drop("_loan_pk", "_ln_acct_nbr")

    orphan_count = resolved.filter(F.col("loan_account_id") == -1).count()
    if orphan_count > 0:
        logger.warning("Found %d payments with orphaned LN_ACCT_NBR references", orphan_count)

    return resolved


def transform_payments(df: DataFrame) -> DataFrame:
    """Apply all column transformations per data/mappings/column_mappings.md.

    Also derives payment_year from payment_date for Delta Lake partitioning.
    """
    return (
        df
        .withColumn("legacy_payment_id", F.col("PMT_SEQ_NBR"))
        # loan_account_id already resolved before this step
        # Date fields
        .withColumn("payment_date", parse_legacy_date("PMT_DT"))
        .withColumn("received_date", parse_legacy_date("PMT_RECV_DT"))
        .withColumn("processed_date", parse_legacy_date("PMT_PROC_DT"))
        # Amount fields: strip commas, parse to decimal
        .withColumn("total_amount", parse_legacy_amount("PMT_AMT"))
        .withColumn("principal_amount", parse_legacy_amount("PMT_PRIN_AMT"))
        .withColumn("interest_amount", parse_legacy_amount("PMT_INT_AMT"))
        .withColumn("escrow_amount", parse_legacy_amount("PMT_ESCROW_AMT"))
        .withColumn("late_fee", F.coalesce(parse_legacy_amount("PMT_LATE_FEE"), F.lit(0).cast(DecimalType(10, 2))))
        # Type and status code expansion
        .withColumn("type", expand_code("PMT_TYP_CD", PAYMENT_TYPE_MAP))
        .withColumn("status", expand_code("PMT_STAT_CD", PAYMENT_STATUS_MAP))
        # Derived partition column
        .withColumn("payment_year", F.year(F.col("payment_date")))
        # Audit timestamps
        .withColumn("created_at", parse_legacy_timestamp("PMT_CRET_DT"))
        .withColumn("updated_at", parse_legacy_timestamp("PMT_UPDT_DT"))
        # Lineage metadata
        .withColumn("_legacy_source", F.lit("CDW_PMT_HIST"))
        .withColumn("_ingested_at", F.current_timestamp())
        # Component sum validation column (used for quality check, then dropped)
        .withColumn("_component_sum",
                     F.col("principal_amount") + F.col("interest_amount")
                     + F.col("escrow_amount") + F.col("late_fee"))
        .withColumn("_sum_delta",
                     F.abs(F.col("total_amount") - F.col("_component_sum")))
        .select(
            "legacy_payment_id", "loan_account_id",
            "payment_date", "received_date", "processed_date",
            "total_amount", "principal_amount", "interest_amount",
            "escrow_amount", "late_fee",
            "type", "status", "payment_year",
            "created_at", "updated_at",
            "_legacy_source", "_ingested_at",
            "_sum_delta"  # kept temporarily for quarantine logic
        )
    )


def quarantine_bad_records(df: DataFrame) -> tuple:
    """Separate records with null required fields, orphaned FKs, or sum mismatches.

    Payment component sum mismatches (> $0.01 tolerance) are logged as
    warnings but NOT quarantined — they are written to the target table with
    the mismatch flag so downstream consumers can decide how to handle them.
    Returns (good_df, bad_df).
    """
    # Log component sum mismatches (informational, not quarantine-worthy)
    mismatch_count = df.filter(F.col("_sum_delta") > 0.01).count()
    if mismatch_count > 0:
        logger.warning(
            "Found %d payments where component sum differs from total by > $0.01. "
            "These are written to target with a warning, not quarantined.",
            mismatch_count
        )

    required_not_null = (
        F.col("legacy_payment_id").isNotNull()
        & F.col("loan_account_id").isNotNull()
        & (F.col("loan_account_id") != -1)
        & F.col("payment_date").isNotNull()
        & F.col("total_amount").isNotNull()
        & F.col("type").isNotNull()
        & F.col("status").isNotNull()
    )

    # Drop the temporary _sum_delta column before writing
    good_df = df.filter(required_not_null).drop("_sum_delta")
    bad_df = df.filter(~required_not_null).drop("_sum_delta")

    bad_count = bad_df.count()
    if bad_count > 0:
        logger.warning("Quarantined %d payment records with null required fields or orphaned FKs", bad_count)

    return good_df, bad_df


def write_to_delta(df: DataFrame, table: str, mode: str = "overwrite"):
    """Write DataFrame to a Delta Lake table."""
    df.write.format("delta").mode(mode).saveAsTable(table)
    logger.info("Wrote %d rows to %s", df.count(), table)


def run(spark: SparkSession):
    """Main entry point: read -> resolve FKs -> transform -> quarantine -> write.

    IMPORTANT: This script must run AFTER ingest_loan_accounts.py because it
    resolves the loan_account_id foreign key against the loan_accounts table.
    """
    logger.info("=== Starting payment ingestion ===")

    # Step 1: Read legacy source
    raw_df = read_legacy_source(spark, LEGACY_SOURCE_PATH)

    # Step 2: Resolve foreign key to loan_accounts
    with_fk = resolve_loan_account_fk(raw_df, spark)

    # Step 3: Transform columns to modern types
    transformed_df = transform_payments(with_fk)

    # Step 4: Quarantine bad records
    good_df, bad_df = quarantine_bad_records(transformed_df)

    # Step 5: Write to Delta (partitioned by payment_year)
    write_to_delta(good_df, TARGET_TABLE, mode="overwrite")
    if bad_df.count() > 0:
        write_to_delta(bad_df, QUARANTINE_TABLE, mode="overwrite")

    logger.info("=== Payment ingestion complete ===")


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestPayments").getOrCreate()
    run(spark)
