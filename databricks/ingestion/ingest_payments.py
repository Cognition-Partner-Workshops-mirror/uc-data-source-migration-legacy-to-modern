"""
Ingest legacy CDW_PMT_HIST → modern payments Delta Lake table.

Source : CSV/Parquet export of CDW_PMT_HIST
Target : loan_warehouse.payments (Delta Lake)

Transformations:
  - Parse date strings (MM/DD/YYYY) → DateType / TimestampType
  - Parse amount strings (with commas) → DecimalType
  - Expand payment type codes (REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment)
  - Expand payment status codes (PST→Posted, REV→Reversed, NSF→NSF, PND→Pending)
  - Resolve loan_account_key FK via lookup on loan_accounts.account_number
  - Derive payment_year partition column from payment_date
  - Preserve legacy PMT_SEQ_NBR for audit traceability
"""

import logging
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType,
)

from transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    expand_status_code,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_payments")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

LEGACY_SCHEMA = StructType([
    StructField("PMT_SEQ_NBR", StringType(), False),
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

SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_pmt_hist/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_PATH = "dbfs:/mnt/quarantine/payments/"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH, fmt: str = SOURCE_FORMAT) -> DataFrame:
    reader = spark.read.schema(LEGACY_SCHEMA)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.format(fmt).load(path)


# ---------------------------------------------------------------------------
# FK lookup
# ---------------------------------------------------------------------------

def load_loan_account_lookup(spark: SparkSession) -> DataFrame:
    """Load loan account key lookup: account_number → loan_account_key."""
    return (
        spark.read.table("loan_warehouse.loan_accounts")
        .select(
            F.col("loan_account_key"),
            F.col("account_number").alias("_acct_nbr"),
        )
    )


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame, loan_lkp: DataFrame) -> tuple[DataFrame, DataFrame]:
    mapped = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_id"),
        F.col("LN_ACCT_NBR").alias("_ln_acct_nbr"),
        parse_legacy_date("PMT_DT").alias("payment_date"),
        parse_legacy_amount("PMT_AMT", 10, 2).alias("total_amount"),
        parse_legacy_amount("PMT_PRIN_AMT", 10, 2).alias("principal_amount"),
        parse_legacy_amount("PMT_INT_AMT", 10, 2).alias("interest_amount"),
        parse_legacy_amount("PMT_ESCROW_AMT", 10, 2).alias("escrow_amount"),
        parse_legacy_amount("PMT_LATE_FEE", 10, 2).alias("late_fee"),
        expand_status_code("PMT_TYP_CD", PAYMENT_TYPE_MAP, "Unknown").alias("type"),
        expand_status_code("PMT_STAT_CD", PAYMENT_STATUS_MAP, "Unknown").alias("status"),
        parse_legacy_date("PMT_RECV_DT").alias("received_date"),
        parse_legacy_date("PMT_PROC_DT").alias("processed_date"),
        parse_legacy_timestamp("PMT_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("PMT_UPDT_DT").alias("updated_at"),
        F.current_timestamp().alias("_migration_ts"),
        F.lit("CDW_PMT_HIST").alias("_source_system"),
    )

    # Resolve loan account FK
    with_loan = mapped.join(
        loan_lkp,
        mapped["_ln_acct_nbr"] == loan_lkp["_acct_nbr"],
        "left",
    ).drop("_acct_nbr", "_ln_acct_nbr")

    # Derive partition column
    with_partition = with_loan.withColumn(
        "payment_year",
        F.year(F.col("payment_date")),
    )

    # Validation
    valid_condition = (
        F.col("loan_account_key").isNotNull()
        & F.col("payment_date").isNotNull()
        & F.col("total_amount").isNotNull()
        & F.col("type").isNotNull()
        & F.col("status").isNotNull()
        & F.col("payment_year").isNotNull()
    )

    good_df = with_partition.filter(valid_condition)
    quarantine_df = with_partition.filter(~valid_condition)

    return good_df, quarantine_df


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    good_count = good_df.count()
    quarantine_count = quarantine_df.count()

    logger.info("Payments — good: %d, quarantined: %d", good_count, quarantine_count)

    if quarantine_count > 0:
        logger.warning("Writing %d quarantined payment records to %s", quarantine_count, QUARANTINE_PATH)
        quarantine_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)

    good_df.write.mode("overwrite").format("delta").saveAsTable(TARGET_TABLE)

    logger.info("Payment ingestion complete → %s", TARGET_TABLE)
    return {"good": good_count, "quarantined": quarantine_count}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession) -> dict:
    logger.info("Starting payment ingestion from %s", SOURCE_PATH)

    raw_df = read_source(spark)
    source_count = raw_df.count()
    logger.info("Source record count: %d", source_count)

    loan_lkp = load_loan_account_lookup(spark)

    good_df, quarantine_df = transform(raw_df, loan_lkp)
    result = write_target(good_df, quarantine_df)
    result["source_count"] = source_count
    return result


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest_CDW_PMT_HIST").getOrCreate()
    run(spark)
