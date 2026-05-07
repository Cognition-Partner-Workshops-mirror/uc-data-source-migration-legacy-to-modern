"""
PySpark Ingestion Script: CDW_PMT_HIST -> loan_warehouse.payments

Reads legacy payment history data from CSV/Parquet source files,
applies type transformations, expands type/status codes, and writes
to the modern Delta Lake payments table.

Usage:
    from databricks.ingestion.ingest_payments import ingest_payments
    ingest_payments(spark, source_path, target_table)
"""

import logging
from datetime import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from .transforms import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_timestamp,
)

logger = logging.getLogger(__name__)


def read_legacy_payments(spark: SparkSession, source_path: str) -> DataFrame:
    """Read legacy CDW_PMT_HIST data from CSV or Parquet source."""
    if source_path.endswith(".parquet") or source_path.endswith(".parquet/"):
        df = spark.read.parquet(source_path)
    else:
        df = spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)

    logger.info(f"Read {df.count()} rows from legacy payments source: {source_path}")
    return df


def transform_payments(df: DataFrame) -> DataFrame:
    """
    Transform legacy CDW_PMT_HIST DataFrame to modern payments schema.

    Transformations:
    - PMT_SEQ_NBR -> legacy_sequence_id (preserved for audit trail)
    - LN_ACCT_NBR -> loan_account_number (FK reference via account_number lookup)
    - PMT_DT -> payment_date (parse MM/DD/YYYY -> DATE)
    - PMT_AMT -> total_amount (remove commas, parse -> DECIMAL(10,2))
    - PMT_PRIN_AMT -> principal_amount (remove commas, parse -> DECIMAL(10,2))
    - PMT_INT_AMT -> interest_amount (remove commas, parse -> DECIMAL(10,2))
    - PMT_ESCROW_AMT -> escrow_amount (remove commas, parse -> DECIMAL(10,2))
    - PMT_LATE_FEE -> late_fee (remove commas, parse -> DECIMAL(10,2))
    - PMT_TYP_CD -> type (expand: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT)
    - PMT_STAT_CD -> status (expand: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING)
    - PMT_RECV_DT -> received_date (parse MM/DD/YYYY -> DATE)
    - PMT_PROC_DT -> processed_date (parse MM/DD/YYYY -> DATE)
    - PMT_CRET_DT -> created_at (parse MM/DD/YYYY -> TIMESTAMP)
    - PMT_UPDT_DT -> updated_at (parse MM/DD/YYYY -> TIMESTAMP)
    """
    transformed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_id"),
        F.col("LN_ACCT_NBR").alias("loan_account_number"),
        parse_date("PMT_DT").alias("payment_date"),
        parse_amount("PMT_AMT", 10, 2).alias("total_amount"),
        parse_amount("PMT_PRIN_AMT", 10, 2).alias("principal_amount"),
        parse_amount("PMT_INT_AMT", 10, 2).alias("interest_amount"),
        parse_amount("PMT_ESCROW_AMT", 10, 2).alias("escrow_amount"),
        parse_amount("PMT_LATE_FEE", 10, 2).alias("late_fee"),
        expand_status("PMT_TYP_CD", PAYMENT_TYPE_MAP).alias("type"),
        expand_status("PMT_STAT_CD", PAYMENT_STATUS_MAP).alias("status"),
        parse_date("PMT_RECV_DT").alias("received_date"),
        parse_date("PMT_PROC_DT").alias("processed_date"),
        parse_timestamp("PMT_CRET_DT").alias("created_at"),
        parse_timestamp("PMT_UPDT_DT").alias("updated_at"),
    )

    return transformed


def validate_payments(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Validate transformed payment records.
    Returns (valid_df, rejected_df) tuple.

    Rejection criteria:
    - loan_account_number is NULL
    - payment_date is NULL
    - total_amount is NULL or < 0
    - type is NULL
    - status is NULL
    """
    required_conditions = (
        F.col("loan_account_number").isNotNull()
        & F.col("payment_date").isNotNull()
        & F.col("total_amount").isNotNull()
        & (F.col("total_amount") >= 0)
        & F.col("type").isNotNull()
        & F.col("status").isNotNull()
    )

    valid = df.filter(required_conditions)

    rejected = df.filter(~required_conditions).withColumn(
        "_rejection_reason",
        F.when(F.col("loan_account_number").isNull(), F.lit("Missing loan_account_number"))
        .when(F.col("payment_date").isNull(), F.lit("Missing or invalid payment_date"))
        .when(F.col("total_amount").isNull(), F.lit("Missing total_amount"))
        .when(F.col("total_amount") < 0, F.lit("Negative total_amount"))
        .when(F.col("type").isNull(), F.lit("Missing type"))
        .when(F.col("status").isNull(), F.lit("Missing status"))
        .otherwise(F.lit("Unknown validation failure")),
    )

    rejected_count = rejected.count()
    if rejected_count > 0:
        logger.warning(f"Rejected {rejected_count} payment records due to validation failures")

    return valid, rejected


def ingest_payments(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.payments",
    rejected_path: str = None,
    mode: str = "append",
) -> dict:
    """
    End-to-end ingestion pipeline for payments.

    Args:
        spark: Active SparkSession
        source_path: Path to legacy CSV/Parquet source files
        target_table: Target Delta Lake table name
        rejected_path: Optional path to write rejected records
        mode: Write mode ('append' or 'overwrite')

    Returns:
        Dictionary with ingestion metrics
    """
    start_time = datetime.now()
    metrics = {
        "table": target_table,
        "source_path": source_path,
        "start_time": start_time.isoformat(),
    }

    # Read
    raw_df = read_legacy_payments(spark, source_path)
    metrics["source_count"] = raw_df.count()

    # Transform
    transformed_df = transform_payments(raw_df)

    # Validate
    valid_df, rejected_df = validate_payments(transformed_df)
    metrics["valid_count"] = valid_df.count()
    metrics["rejected_count"] = rejected_df.count()

    # Write valid records to Delta Lake
    valid_df.write.format("delta").mode(mode).saveAsTable(target_table)
    logger.info(f"Wrote {metrics['valid_count']} records to {target_table}")

    # Write rejected records if path provided
    if rejected_path and metrics["rejected_count"] > 0:
        rejected_df.write.format("delta").mode("append").save(rejected_path)
        logger.info(f"Wrote {metrics['rejected_count']} rejected records to {rejected_path}")

    metrics["end_time"] = datetime.now().isoformat()
    metrics["status"] = "SUCCESS" if metrics["rejected_count"] == 0 else "COMPLETED_WITH_REJECTS"

    logger.info(f"Payments ingestion complete: {metrics}")
    return metrics


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("CDW_Payments_Ingestion").getOrCreate()

    SOURCE_PATH = spark.conf.get("migration.payments.source_path", "/mnt/legacy/cdw_pmt_hist/")
    TARGET_TABLE = spark.conf.get("migration.payments.target_table", "loan_warehouse.payments")
    REJECTED_PATH = spark.conf.get("migration.payments.rejected_path", "/mnt/migration/rejected/payments/")
    WRITE_MODE = spark.conf.get("migration.write_mode", "overwrite")

    result = ingest_payments(spark, SOURCE_PATH, TARGET_TABLE, REJECTED_PATH, WRITE_MODE)
    print(f"Ingestion Result: {result}")
