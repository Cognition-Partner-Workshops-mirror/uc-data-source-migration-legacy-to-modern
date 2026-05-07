"""
PySpark Ingestion Script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads legacy loan product data from CSV/Parquet source files,
applies type transformations, and writes to the modern Delta Lake table.

Usage:
    from databricks.ingestion.ingest_loan_products import ingest_loan_products
    ingest_loan_products(spark, source_path, target_table)
"""

import logging
from datetime import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from .transforms import (
    PRODUCT_STATUS_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_integer,
)

logger = logging.getLogger(__name__)


def read_legacy_loan_products(spark: SparkSession, source_path: str) -> DataFrame:
    """Read legacy CDW_LN_PROD data from CSV or Parquet source."""
    if source_path.endswith(".parquet") or source_path.endswith(".parquet/"):
        df = spark.read.parquet(source_path)
    else:
        df = spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)

    logger.info(f"Read {df.count()} rows from legacy loan products source: {source_path}")
    return df


def transform_loan_products(df: DataFrame) -> DataFrame:
    """
    Transform legacy CDW_LN_PROD DataFrame to modern loan_products schema.

    Transformations:
    - PROD_CD -> code (direct copy)
    - PROD_DESC_TXT -> name (direct copy)
    - PROD_TYP_CD -> type (direct copy)
    - PROD_TERM_MOS -> term_months (parse string -> INT)
    - PROD_RT_TYP -> rate_type (direct copy)
    - PROD_MIN_AMT -> min_amount (remove commas, parse -> DECIMAL)
    - PROD_MAX_AMT -> max_amount (remove commas, parse -> DECIMAL)
    - PROD_STAT_CD -> is_active (ACT -> true, INA -> false)
    - PROD_EFF_DT -> effective_date (parse MM/DD/YYYY -> DATE)
    - PROD_EXP_DT -> expiration_date (parse MM/DD/YYYY -> DATE)
    """
    # Build is_active as boolean from status code
    is_active_expr = F.when(
        F.upper(F.trim(F.col("PROD_STAT_CD"))) == "ACT", F.lit(True)
    ).when(
        F.upper(F.trim(F.col("PROD_STAT_CD"))) == "INA", F.lit(False)
    ).otherwise(F.lit(None).cast("boolean"))

    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_integer("PROD_TERM_MOS").alias("term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount("PROD_MIN_AMT", 12, 2).alias("min_amount"),
        parse_amount("PROD_MAX_AMT", 12, 2).alias("max_amount"),
        is_active_expr.alias("is_active"),
        parse_date("PROD_EFF_DT").alias("effective_date"),
        parse_date("PROD_EXP_DT").alias("expiration_date"),
    )

    return transformed


def validate_loan_products(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Validate transformed loan product records.
    Returns (valid_df, rejected_df) tuple.

    Rejection criteria:
    - code is NULL
    - name is NULL
    - term_months is NULL or <= 0
    """
    valid = df.filter(
        F.col("code").isNotNull()
        & F.col("name").isNotNull()
        & F.col("term_months").isNotNull()
        & (F.col("term_months") > 0)
    )

    rejected = df.filter(
        F.col("code").isNull()
        | F.col("name").isNull()
        | F.col("term_months").isNull()
        | (F.col("term_months") <= 0)
    ).withColumn("_rejection_reason", F.lit("Missing required field or invalid term_months"))

    rejected_count = rejected.count()
    if rejected_count > 0:
        logger.warning(f"Rejected {rejected_count} loan product records due to validation failures")

    return valid, rejected


def ingest_loan_products(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.loan_products",
    rejected_path: str = None,
    mode: str = "append",
) -> dict:
    """
    End-to-end ingestion pipeline for loan products.

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
    raw_df = read_legacy_loan_products(spark, source_path)
    metrics["source_count"] = raw_df.count()

    # Transform
    transformed_df = transform_loan_products(raw_df)

    # Validate
    valid_df, rejected_df = validate_loan_products(transformed_df)
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

    logger.info(f"Loan products ingestion complete: {metrics}")
    return metrics


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("CDW_LoanProducts_Ingestion").getOrCreate()

    SOURCE_PATH = spark.conf.get("migration.loan_products.source_path", "/mnt/legacy/cdw_ln_prod/")
    TARGET_TABLE = spark.conf.get("migration.loan_products.target_table", "loan_warehouse.loan_products")
    REJECTED_PATH = spark.conf.get("migration.loan_products.rejected_path", "/mnt/migration/rejected/loan_products/")
    WRITE_MODE = spark.conf.get("migration.write_mode", "overwrite")

    result = ingest_loan_products(spark, SOURCE_PATH, TARGET_TABLE, REJECTED_PATH, WRITE_MODE)
    print(f"Ingestion Result: {result}")
