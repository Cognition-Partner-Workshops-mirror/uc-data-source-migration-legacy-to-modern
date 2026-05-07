"""
PySpark Ingestion Script: Payments
====================================
Reads legacy CDW_PMT_HIST data (simulated as CSV/Parquet source),
transforms columns to proper types, resolves the loan_account FK,
expands payment type and status codes, and writes to the modern
Delta Lake payments table.

Source: CDW_PMT_HIST (all-VARCHAR legacy table)
Target: loan_warehouse.payments (Delta Lake with proper types)
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, to_date, to_timestamp, regexp_replace, trim, when, lit, year
)
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DecimalType, DateType
)
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_payments")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/legacy/cdw_pmt_hist/"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_PATH = "/mnt/quarantine/payments/"
LEGACY_DATE_FORMAT = "MM/dd/yyyy"

# ---------------------------------------------------------------------------
# Code expansion mappings
# ---------------------------------------------------------------------------
# Payment type codes (CDW_PMT_HIST.PMT_TYP_CD)
PAYMENT_TYPE_MAP = {
    "REG": "Regular",
    "EXT": "Extra",
    "PRT": "Partial",
    "PRE": "Prepayment"
}

# Payment status codes (CDW_PMT_HIST.PMT_STAT_CD)
PAYMENT_STATUS_MAP = {
    "PST": "Posted",
    "REV": "Reversed",
    "NSF": "NSF",
    "PND": "Pending"
}


def create_spark_session():
    """Initialize SparkSession with Delta Lake support."""
    return (
        SparkSession.builder
        .appName("LoanMigration_IngestPayments")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )


def define_source_schema():
    """
    Define explicit schema for legacy CSV export.
    All columns are StringType matching the legacy all-VARCHAR design.
    """
    return StructType([
        StructField("PMT_SEQ_NBR", StringType(), nullable=False),
        StructField("LN_ACCT_NBR", StringType(), nullable=True),
        StructField("PMT_DT", StringType(), nullable=True),
        StructField("PMT_AMT", StringType(), nullable=True),
        StructField("PMT_PRIN_AMT", StringType(), nullable=True),
        StructField("PMT_INT_AMT", StringType(), nullable=True),
        StructField("PMT_ESCROW_AMT", StringType(), nullable=True),
        StructField("PMT_LATE_FEE", StringType(), nullable=True),
        StructField("PMT_TYP_CD", StringType(), nullable=True),
        StructField("PMT_STAT_CD", StringType(), nullable=True),
        StructField("PMT_RECV_DT", StringType(), nullable=True),
        StructField("PMT_PROC_DT", StringType(), nullable=True),
        StructField("PMT_CRET_DT", StringType(), nullable=True),
        StructField("PMT_UPDT_DT", StringType(), nullable=True),
    ])


def parse_amount_string(column):
    """Remove commas from amount strings and cast to decimal(10,2)."""
    return regexp_replace(col(column), ",", "").cast(DecimalType(10, 2))


def expand_payment_type(column):
    """
    Expand payment type abbreviations to full readable values.
    REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment.
    """
    return (
        when(col(column) == "REG", lit("Regular"))
        .when(col(column) == "EXT", lit("Extra"))
        .when(col(column) == "PRT", lit("Partial"))
        .when(col(column) == "PRE", lit("Prepayment"))
        .otherwise(col(column))  # Preserve unknown codes
    )


def expand_payment_status(column):
    """
    Expand payment status abbreviations to full readable values.
    PST→Posted, REV→Reversed, NSF→NSF, PND→Pending.
    """
    return (
        when(col(column) == "PST", lit("Posted"))
        .when(col(column) == "REV", lit("Reversed"))
        .when(col(column) == "NSF", lit("NSF"))
        .when(col(column) == "PND", lit("Pending"))
        .otherwise(col(column))  # Preserve unknown codes
    )


def read_source(spark, source_path, schema):
    """Read legacy payment data from CSV source with error handling."""
    logger.info(f"Reading source data from: {source_path}")

    df = (
        spark.read
        .option("header", "true")
        .option("mode", "PERMISSIVE")
        .option("columnNameOfCorruptRecord", "_corrupt_record")
        .schema(schema.add(StructField("_corrupt_record", StringType(), nullable=True)))
        .csv(source_path)
    )

    total_count = df.count()
    logger.info(f"Total records read from source: {total_count}")
    return df


def quarantine_malformed(df, quarantine_path):
    """Separate malformed records for manual review."""
    malformed = df.filter(
        col("_corrupt_record").isNotNull() |
        col("PMT_SEQ_NBR").isNull() |
        (trim(col("PMT_SEQ_NBR")) == "") |
        col("LN_ACCT_NBR").isNull()
    )

    malformed_count = malformed.count()
    if malformed_count > 0:
        logger.warning(f"Quarantining {malformed_count} malformed records to: {quarantine_path}")
        malformed.write.mode("append").json(quarantine_path)
    else:
        logger.info("No malformed records found.")

    valid = df.filter(
        col("_corrupt_record").isNull() &
        col("PMT_SEQ_NBR").isNotNull() &
        (trim(col("PMT_SEQ_NBR")) != "") &
        col("LN_ACCT_NBR").isNotNull()
    ).drop("_corrupt_record")

    logger.info(f"Valid records for transformation: {valid.count()}")
    return valid


def resolve_foreign_keys(spark, df):
    """
    Resolve LN_ACCT_NBR to loan_accounts.id via account_number lookup.
    """
    logger.info("Resolving foreign keys...")

    # Load loan accounts lookup table
    loan_accounts_lookup = (
        spark.table("loan_warehouse.loan_accounts")
        .select(col("id").alias("loan_account_id"), col("account_number"))
    )

    # Join to resolve loan account FK
    df = df.join(
        loan_accounts_lookup,
        df["LN_ACCT_NBR"] == loan_accounts_lookup["account_number"],
        "left"
    )

    # Log any unresolved references
    unresolved = df.filter(col("loan_account_id").isNull()).count()
    if unresolved > 0:
        logger.warning(f"WARNING: {unresolved} payments have unresolved loan_account_id")

    # Drop the join key column
    df = df.drop("account_number")

    return df


def transform(df):
    """
    Apply all transformations for CDW_PMT_HIST → payments:
    - Keep legacy_payment_id for traceability
    - Parse amounts from comma-formatted strings to DecimalType
    - Parse dates from MM/DD/YYYY to DateType/TimestampType
    - Expand payment type and status codes
    """
    logger.info("Applying transformations...")

    transformed = (
        df
        # Preserve legacy payment ID for audit trail
        .withColumnRenamed("PMT_SEQ_NBR", "legacy_payment_id")

        # Parse payment date
        .withColumn("payment_date", to_date(col("PMT_DT"), LEGACY_DATE_FORMAT))

        # Parse payment amounts (remove commas, cast to decimal)
        .withColumn("total_amount", parse_amount_string("PMT_AMT"))
        .withColumn("principal_amount", parse_amount_string("PMT_PRIN_AMT"))
        .withColumn("interest_amount", parse_amount_string("PMT_INT_AMT"))
        .withColumn("escrow_amount", parse_amount_string("PMT_ESCROW_AMT"))
        .withColumn("late_fee", parse_amount_string("PMT_LATE_FEE"))

        # Expand payment type and status codes
        .withColumn("type", expand_payment_type("PMT_TYP_CD"))
        .withColumn("status", expand_payment_status("PMT_STAT_CD"))

        # Parse processing dates
        .withColumn("received_date", to_date(col("PMT_RECV_DT"), LEGACY_DATE_FORMAT))
        .withColumn("processed_date", to_date(col("PMT_PROC_DT"), LEGACY_DATE_FORMAT))

        # Parse audit timestamps
        .withColumn("created_at", to_timestamp(col("PMT_CRET_DT"), LEGACY_DATE_FORMAT))
        .withColumn("updated_at", to_timestamp(col("PMT_UPDT_DT"), LEGACY_DATE_FORMAT))

        # Drop original columns that have been transformed
        .drop("LN_ACCT_NBR", "PMT_DT", "PMT_AMT", "PMT_PRIN_AMT", "PMT_INT_AMT",
               "PMT_ESCROW_AMT", "PMT_LATE_FEE", "PMT_TYP_CD", "PMT_STAT_CD",
               "PMT_RECV_DT", "PMT_PROC_DT", "PMT_CRET_DT", "PMT_UPDT_DT")
    )

    logger.info("Transformations applied successfully.")
    return transformed


def write_to_delta(df, target_table):
    """Write transformed data to Delta Lake target table."""
    logger.info(f"Writing to Delta table: {target_table}")

    df.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .saveAsTable(target_table)

    final_count = df.count()
    logger.info(f"Successfully wrote {final_count} records to {target_table}")
    return final_count


def main():
    """
    Main entry point for the payments ingestion pipeline.
    Must be run AFTER loan_accounts ingestion to resolve FKs.
    """
    logger.info("=" * 60)
    logger.info("Starting Payments Ingestion Pipeline")
    logger.info("=" * 60)
    logger.info("NOTE: This script depends on loan_accounts table")
    logger.info("      being already populated for FK resolution.")

    spark = create_spark_session()
    schema = define_source_schema()

    # Step 1: Read source data
    raw_df = read_source(spark, SOURCE_PATH, schema)
    source_count = raw_df.count()

    # Step 2: Quarantine malformed records
    valid_df = quarantine_malformed(raw_df, QUARANTINE_PATH)

    # Step 3: Resolve foreign keys (loan_account_id)
    resolved_df = resolve_foreign_keys(spark, valid_df)

    # Step 4: Transform to modern schema
    transformed_df = transform(resolved_df)

    # Step 5: Write to Delta Lake
    target_count = write_to_delta(transformed_df, TARGET_TABLE)

    # Step 6: Log reconciliation summary
    logger.info("=" * 60)
    logger.info("Payments Ingestion Summary")
    logger.info(f"  Source records read:    {source_count}")
    logger.info(f"  Records quarantined:    {source_count - target_count}")
    logger.info(f"  Records written:        {target_count}")
    logger.info("=" * 60)

    spark.stop()


if __name__ == "__main__":
    main()
