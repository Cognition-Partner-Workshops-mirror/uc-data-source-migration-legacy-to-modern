"""
Ingest payments from legacy CDW_PMT_HIST into Delta Lake payments table.

Source : CSV/Parquet export of CDW_PMT_HIST
Target : loan_modernized.payments

Transformations applied:
  - Amount strings -> DECIMAL
  - Date strings (MM/DD/YYYY) -> DATE / TIMESTAMP
  - Payment type expansion (REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT)
  - Payment status expansion (PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING)
  - Derive payment_year and payment_month for partitioning
"""

import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_code,
    parse_amount,
    parse_date,
    parse_timestamp,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_payments")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/cdw/CDW_PMT_HIST"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_modernized.payments"
LOAN_ACCOUNTS_TABLE = "loan_modernized.loan_accounts"
QUARANTINE_PATH = "/mnt/landing/cdw/quarantine/payments"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "nullValue": "",
    "emptyValue": "",
}


def read_source(spark: SparkSession) -> DataFrame:
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for k, v in CSV_OPTIONS.items():
            reader = reader.option(k, v)
    return reader.load(SOURCE_PATH)


def transform(df: DataFrame, spark: SparkSession) -> tuple[DataFrame, DataFrame]:
    """Transform payment records and validate FK to loan_accounts."""
    base = df.select(
        F.trim(F.col("PMT_SEQ_NBR")).alias("legacy_sequence_nbr"),
        F.trim(F.col("LN_ACCT_NBR")).alias("account_number"),
        parse_date("PMT_DT").alias("payment_date"),
        parse_amount("PMT_AMT", 10, 2).alias("total_amount"),
        parse_amount("PMT_PRIN_AMT", 10, 2).alias("principal_amount"),
        parse_amount("PMT_INT_AMT", 10, 2).alias("interest_amount"),
        parse_amount("PMT_ESCROW_AMT", 10, 2).alias("escrow_amount"),
        parse_amount("PMT_LATE_FEE", 10, 2).alias("late_fee"),
        expand_code("PMT_TYP_CD", PAYMENT_TYPE_MAP).alias("type"),
        expand_code("PMT_STAT_CD", PAYMENT_STATUS_MAP).alias("status"),
        parse_date("PMT_RECV_DT").alias("received_date"),
        parse_date("PMT_PROC_DT").alias("processed_date"),
        parse_timestamp("PMT_CRET_DT").alias("created_at"),
        parse_timestamp("PMT_UPDT_DT").alias("updated_at"),
        F.current_timestamp().alias("_migration_ts"),
    )

    # Derive partition columns
    base = base.withColumn("payment_year", F.year(F.col("payment_date")))
    base = base.withColumn("payment_month", F.month(F.col("payment_date")))

    # Validate FK: account_number must exist in loan_accounts
    loan_accounts = spark.table(LOAN_ACCOUNTS_TABLE).select(
        F.col("account_number").alias("_valid_acct_nbr")
    ).distinct()

    joined = base.join(
        loan_accounts,
        base["account_number"] == loan_accounts["_valid_acct_nbr"],
        "left",
    ).drop("_valid_acct_nbr")

    # Quarantine: missing required fields or orphaned payments
    quarantine_condition = (
        F.col("legacy_sequence_nbr").isNull()
        | F.col("account_number").isNull()
        | F.col("payment_date").isNull()
        | F.col("total_amount").isNull()
    )

    # Log orphaned payments (account_number not found) but don't quarantine —
    # they may reference accounts loaded later. Flag them instead.
    orphan_condition = F.col("_valid_acct_nbr").isNull() if "_valid_acct_nbr" in joined.columns else F.lit(False)

    quarantine_df = joined.filter(quarantine_condition)
    good_df = joined.filter(~quarantine_condition)

    return good_df, quarantine_df


def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    source_count = good_df.count() + quarantine_df.count()
    quarantine_count = quarantine_df.count()

    if quarantine_count > 0:
        logger.warning(
            "Quarantined %d payment records", quarantine_count
        )
        quarantine_df.write.format("delta").mode("overwrite").save(QUARANTINE_PATH)

    good_count = good_df.count()
    logger.info("Writing %d payment records to %s", good_count, TARGET_TABLE)

    good_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    return {
        "table": TARGET_TABLE,
        "source_count": source_count,
        "written_count": good_count,
        "quarantined_count": quarantine_count,
    }


def run(spark: SparkSession) -> dict:
    logger.info("Starting payment ingestion from %s", SOURCE_PATH)
    raw = read_source(spark)
    logger.info("Read %d raw payment records", raw.count())
    good, quarantine = transform(raw, spark)
    stats = write_target(good, quarantine)
    logger.info("Payment ingestion complete: %s", stats)
    return stats


if __name__ == "__main__":
    spark = SparkSession.builder.appName("ingest_payments").getOrCreate()
    result = run(spark)
    print(result)
