"""
PySpark Ingestion Script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads legacy borrower data from CSV/Parquet source files,
applies type transformations, expands status codes, and writes
to the modern Delta Lake borrowers table.

Usage (Databricks notebook or job):
    %run ./transforms
    %run ./ingest_borrowers
    -- or --
    from databricks.ingestion.ingest_borrowers import ingest_borrowers
    ingest_borrowers(spark, source_path, target_table)
"""

import logging
from datetime import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from .transforms import (
    BORROWER_STATUS_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_integer,
    parse_timestamp,
)

logger = logging.getLogger(__name__)


def read_legacy_borrowers(spark: SparkSession, source_path: str) -> DataFrame:
    """
    Read legacy CDW_BORR_MSTR data from CSV or Parquet source.
    Supports both formats based on file extension.
    """
    if source_path.endswith(".parquet") or source_path.endswith(".parquet/"):
        df = spark.read.parquet(source_path)
    else:
        df = spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)

    logger.info(f"Read {df.count()} rows from legacy borrower source: {source_path}")
    return df


def transform_borrowers(df: DataFrame) -> DataFrame:
    """
    Transform legacy CDW_BORR_MSTR DataFrame to modern borrowers schema.

    Transformations:
    - BORR_ID -> external_id (direct copy)
    - BORR_FST_NM -> first_name (direct copy)
    - BORR_LST_NM -> last_name (direct copy)
    - BORR_MID_INIT -> middle_initial (direct copy)
    - BORR_SSN_ENCR -> ssn_hash (direct copy)
    - BORR_DOB_DT -> date_of_birth (parse MM/DD/YYYY -> DATE)
    - BORR_ADDR_LN1 -> address_line1 (direct copy)
    - BORR_ADDR_LN2 -> address_line2 (direct copy)
    - BORR_CTY_NM -> city (direct copy)
    - BORR_ST_CD -> state (direct copy)
    - BORR_ZIP_CD -> zip_code (direct copy)
    - BORR_PH_NBR -> phone (direct copy)
    - BORR_EMAIL_ADDR -> email (direct copy)
    - BORR_CRDT_SCR -> credit_score (parse string -> INT)
    - BORR_EMP_STAT -> employment_status (direct copy)
    - BORR_ANN_INCM -> annual_income (remove commas, parse -> DECIMAL)
    - BORR_CRET_DT -> created_at (parse MM/DD/YYYY -> TIMESTAMP)
    - BORR_UPDT_DT -> updated_at (parse MM/DD/YYYY -> TIMESTAMP)
    - BORR_STAT_CD -> status (expand ACT->ACTIVE, INA->INACTIVE)
    - BORR_REC_TYP -> dropped (not needed in modern schema)
    """
    transformed = df.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_date("BORR_DOB_DT").alias("date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        parse_integer("BORR_CRDT_SCR").alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount("BORR_ANN_INCM", 12, 2).alias("annual_income"),
        expand_status("BORR_STAT_CD", BORROWER_STATUS_MAP).alias("status"),
        parse_timestamp("BORR_CRET_DT").alias("created_at"),
        parse_timestamp("BORR_UPDT_DT").alias("updated_at"),
    )

    return transformed


def validate_borrowers(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Validate transformed borrower records.
    Returns (valid_df, rejected_df) tuple.

    Rejection criteria:
    - external_id is NULL
    - first_name is NULL
    - last_name is NULL
    """
    valid = df.filter(
        F.col("external_id").isNotNull()
        & F.col("first_name").isNotNull()
        & F.col("last_name").isNotNull()
    )

    rejected = df.filter(
        F.col("external_id").isNull()
        | F.col("first_name").isNull()
        | F.col("last_name").isNull()
    ).withColumn("_rejection_reason", F.lit("Missing required field (external_id, first_name, or last_name)"))

    rejected_count = rejected.count()
    if rejected_count > 0:
        logger.warning(f"Rejected {rejected_count} borrower records due to validation failures")

    return valid, rejected


def ingest_borrowers(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.borrowers",
    rejected_path: str = None,
    mode: str = "append",
) -> dict:
    """
    End-to-end ingestion pipeline for borrowers.

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
    raw_df = read_legacy_borrowers(spark, source_path)
    metrics["source_count"] = raw_df.count()

    # Transform
    transformed_df = transform_borrowers(raw_df)

    # Validate
    valid_df, rejected_df = validate_borrowers(transformed_df)
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

    logger.info(f"Borrower ingestion complete: {metrics}")
    return metrics


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("CDW_Borrower_Ingestion").getOrCreate()

    # Configuration - override via Databricks widgets or job parameters
    SOURCE_PATH = spark.conf.get("migration.borrowers.source_path", "/mnt/legacy/cdw_borr_mstr/")
    TARGET_TABLE = spark.conf.get("migration.borrowers.target_table", "loan_warehouse.borrowers")
    REJECTED_PATH = spark.conf.get("migration.borrowers.rejected_path", "/mnt/migration/rejected/borrowers/")
    WRITE_MODE = spark.conf.get("migration.write_mode", "overwrite")

    result = ingest_borrowers(spark, SOURCE_PATH, TARGET_TABLE, REJECTED_PATH, WRITE_MODE)
    print(f"Ingestion Result: {result}")
