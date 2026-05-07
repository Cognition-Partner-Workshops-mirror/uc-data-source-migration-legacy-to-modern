"""
Ingestion script: CDW_PMT_HIST → loan_warehouse.payments

Reads the legacy payment history table, applies column renames, type
conversions, status and type code expansion, and resolves the loan account FK.

Requires that loan_accounts is already populated for FK resolution.

Usage (Databricks notebook cell):
    ingest_payments(spark, source_path="/mnt/landing/cdw_pmt_hist/")
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from databricks.ingestion.common import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_timestamp,
)

logger = logging.getLogger("migration.ingest_payments")

TARGET_TABLE = "loan_warehouse.payments"
SOURCE_TABLE = "CDW_PMT_HIST"


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv") -> DataFrame:
    if file_format == "parquet":
        return spark.read.parquet(source_path)
    return (
        spark.read.option("header", "true")
        .option("inferSchema", "false")
        .csv(source_path)
    )


def transform(spark: SparkSession, df: DataFrame) -> DataFrame:
    quarantine_condition = (
        F.col("PMT_SEQ_NBR").isNull()
        | F.col("LN_ACCT_NBR").isNull()
        | F.col("PMT_DT").isNull()
    )

    quarantined = df.filter(quarantine_condition)
    if quarantined.count() > 0:
        logger.warning(
            "Quarantined %d payment records with null required fields",
            quarantined.count(),
        )
        quarantined.write.mode("append").format("delta").saveAsTable(
            "loan_warehouse._quarantine_payments"
        )

    clean = df.filter(~quarantine_condition)

    # Resolve loan account FK: legacy LN_ACCT_NBR → modern loan_accounts.id
    loan_accounts = spark.table("loan_warehouse.loan_accounts").select(
        F.col("id").alias("_loan_account_id"),
        F.col("account_number").alias("_ln_acct_nbr"),
    )

    joined = clean.join(
        loan_accounts, clean["LN_ACCT_NBR"] == loan_accounts["_ln_acct_nbr"], "left"
    )

    unresolved = joined.filter(F.col("_loan_account_id").isNull())
    if unresolved.count() > 0:
        logger.warning(
            "Found %d payment records with unresolved loan account FK",
            unresolved.count(),
        )

    payment_date_col = parse_date(F.col("PMT_DT"))

    transformed = joined.select(
        F.col("PMT_SEQ_NBR").alias("legacy_payment_id"),
        F.col("_loan_account_id").alias("loan_account_id"),
        payment_date_col.alias("payment_date"),
        parse_amount(F.col("PMT_AMT"), 10, 2).alias("total_amount"),
        parse_amount(F.col("PMT_PRIN_AMT"), 10, 2).alias("principal_amount"),
        parse_amount(F.col("PMT_INT_AMT"), 10, 2).alias("interest_amount"),
        parse_amount(F.col("PMT_ESCROW_AMT"), 10, 2).alias("escrow_amount"),
        parse_amount(F.col("PMT_LATE_FEE"), 10, 2).alias("late_fee"),
        expand_status(F.col("PMT_TYP_CD"), PAYMENT_TYPE_MAP).alias("type"),
        expand_status(F.col("PMT_STAT_CD"), PAYMENT_STATUS_MAP).alias("status"),
        parse_date(F.col("PMT_RECV_DT")).alias("received_date"),
        parse_date(F.col("PMT_PROC_DT")).alias("processed_date"),
        parse_timestamp(F.col("PMT_CRET_DT")).alias("created_at"),
        parse_timestamp(F.col("PMT_UPDT_DT")).alias("updated_at"),
        F.year(payment_date_col).alias("payment_year"),
        F.lit(SOURCE_TABLE).alias("_migration_src"),
        F.current_timestamp().alias("_migrated_at"),
    )

    return transformed


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    df.write.format("delta").mode(mode).partitionBy("payment_year").saveAsTable(TARGET_TABLE)


def ingest_payments(
    spark: SparkSession,
    source_path: str,
    file_format: str = "csv",
    write_mode: str = "overwrite",
) -> dict:
    logger.info("Starting payment ingestion from %s", source_path)

    raw = read_source(spark, source_path, file_format)
    source_count = raw.count()
    logger.info("Read %d records from source", source_count)

    transformed = transform(spark, raw)
    target_count = transformed.count()
    logger.info("Transformed %d records (quarantined %d)", target_count, source_count - target_count)

    write_target(transformed, write_mode)
    logger.info("Wrote %d records to %s", target_count, TARGET_TABLE)

    return {"source_count": source_count, "target_count": target_count}
