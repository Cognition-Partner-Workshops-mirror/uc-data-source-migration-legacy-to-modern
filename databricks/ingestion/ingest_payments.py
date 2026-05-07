"""
Ingest payment history from legacy CDW_PMT_HIST into the modern ``payments`` Delta table.

This script:
- Resolves LN_ACCT_NBR → loan_account_id via lookup against the loan_accounts table
- Expands payment type and status codes to full descriptions
- Preserves the original PMT_SEQ_NBR for audit traceability

Expected source: CSV or Parquet export of the CDW_PMT_HIST table.

Usage:
    from ingestion.ingest_payments import run
    run(spark, source_path="dbfs:/mnt/legacy/cdw_pmt_hist/", source_format="csv")
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

# Import shared transformation helpers for legacy VARCHAR → typed column conversions
from .transforms import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_timestamp,
)

logger = logging.getLogger("ingestion.payments")

# Target Delta Lake table, partitioned by payment_year for time-range analytics
TARGET_TABLE = "loan_warehouse.payments"

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


def read_source(spark: SparkSession, path: str, fmt: str = "csv") -> DataFrame:
    reader = spark.read.schema(LEGACY_SCHEMA)
    if fmt == "csv":
        return reader.option("header", "true").csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def _load_loan_lookup(spark: SparkSession) -> DataFrame:
    """Load account_number → loan_account_id mapping."""
    return spark.table("loan_warehouse.loan_accounts").select(
        F.col("loan_account_id"),
        F.col("account_number"),
    )


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    # Load FK lookup from already-ingested loan_accounts table
    loan_lkp = _load_loan_lookup(spark)

    # Map legacy columns to modern names with type conversions
    base = df.select(
        # Preserve original sequence number for audit traceability
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),
        F.col("LN_ACCT_NBR").alias("_acct_nbr"),  # temporary column for FK join
        parse_date("PMT_DT").alias("payment_date"),
        parse_amount("PMT_AMT", 10, 2).alias("total_amount"),
        parse_amount("PMT_PRIN_AMT", 10, 2).alias("principal_amount"),
        parse_amount("PMT_INT_AMT", 10, 2).alias("interest_amount"),
        parse_amount("PMT_ESCROW_AMT", 10, 2).alias("escrow_amount"),
        parse_amount("PMT_LATE_FEE", 10, 2).alias("late_fee"),
        # Expand payment type: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
        expand_status("PMT_TYP_CD", PAYMENT_TYPE_MAP, alias="type"),
        # Expand payment status: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
        expand_status("PMT_STAT_CD", PAYMENT_STATUS_MAP, alias="status"),
        parse_date("PMT_RECV_DT").alias("received_date"),
        parse_date("PMT_PROC_DT").alias("processed_date"),
        parse_timestamp("PMT_CRET_DT").alias("created_at"),
        parse_timestamp("PMT_UPDT_DT").alias("updated_at"),
    )

    # Resolve loan account FK: join LN_ACCT_NBR against loan_accounts.account_number
    with_loan = base.join(
        loan_lkp,
        base["_acct_nbr"] == loan_lkp["account_number"],
        "left",
    ).drop("account_number")

    unresolved = with_loan.filter(F.col("loan_account_id").isNull()).count()
    if unresolved > 0:
        logger.warning(
            "Payment ingestion: %d rows have unresolved loan_account_id",
            unresolved,
        )

    # Flag rows with missing PKs or unresolved FKs; invalid rows are kept, not dropped
    result = with_loan.withColumn(
        "_is_valid",
        F.col("legacy_sequence_nbr").isNotNull()
        & F.col("loan_account_id").isNotNull()
        & F.col("payment_date").isNotNull(),
    ).drop("_acct_nbr")  # drop temporary join column

    return result


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    output = df.drop("_is_valid")
    (
        output.write
        .format("delta")
        .mode(mode)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info("Wrote %d rows to %s (mode=%s)", output.count(), TARGET_TABLE, mode)


def run(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
    write_mode: str = "overwrite",
) -> DataFrame:
    logger.info("Starting payment ingestion from %s (%s)", source_path, source_format)
    raw = read_source(spark, source_path, source_format)
    logger.info("Read %d raw payment records", raw.count())

    result = transform(raw, spark)
    write_target(result, mode=write_mode)
    return result
