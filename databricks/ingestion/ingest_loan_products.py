"""
Ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan products table, converts types and maps status codes
to a boolean is_active flag.

Usage:
    spark-submit ingest_loan_products.py --source /mnt/legacy/CDW_LN_PROD.csv
"""

import argparse
import sys

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    log_rejected_rows,
    logger,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    read_legacy_csv,
    read_legacy_parquet,
    write_delta,
)

TARGET_TABLE = "loan_warehouse.loan_products"


def transform_loan_products(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Transform legacy CDW_LN_PROD records to modern loan_products schema.

    Returns:
        (valid_df, rejected_df)
    """
    logger.info("Starting loan product transformation. Source row count: %d", df.count())

    renamed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        F.col("PROD_TERM_MOS").alias("term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        F.col("PROD_MIN_AMT").alias("min_amount"),
        F.col("PROD_MAX_AMT").alias("max_amount"),
        F.col("PROD_STAT_CD").alias("is_active"),
        F.col("PROD_EFF_DT").alias("effective_date"),
        F.col("PROD_EXP_DT").alias("expiration_date"),
    )

    transformed = renamed.select(
        F.col("code"),
        F.col("name"),
        F.col("type"),
        parse_int_col("term_months"),
        F.col("rate_type"),
        parse_amount_col("min_amount"),
        parse_amount_col("max_amount"),
        F.when(F.col("is_active") == "ACT", F.lit(True))
         .when(F.col("is_active") == "INA", F.lit(False))
         .otherwise(F.lit(True))
         .alias("is_active"),
        parse_date_col("effective_date"),
        parse_date_col("expiration_date"),
    )

    transformed = (
        transformed
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit("CDW_LN_PROD"))
    )

    valid = transformed.filter(
        F.col("code").isNotNull()
        & F.col("name").isNotNull()
        & F.col("type").isNotNull()
        & F.col("term_months").isNotNull()
        & F.col("rate_type").isNotNull()
    )
    rejected = transformed.filter(
        F.col("code").isNull()
        | F.col("name").isNull()
        | F.col("type").isNull()
        | F.col("term_months").isNull()
        | F.col("rate_type").isNull()
    )

    logger.info(
        "Loan product transformation complete. Valid: %d, Rejected: %d",
        valid.count(), rejected.count(),
    )
    return valid, rejected


def run(spark: SparkSession, source_path: str, source_format: str = "csv") -> None:
    """Execute the loan product ingestion pipeline."""
    if source_format == "parquet":
        raw_df = read_legacy_parquet(spark, source_path)
    else:
        raw_df = read_legacy_csv(spark, source_path)

    valid_df, rejected_df = transform_loan_products(raw_df)

    log_rejected_rows(rejected_df, "Missing required fields (code, name, type, term_months, rate_type)", TARGET_TABLE)

    write_delta(valid_df, TARGET_TABLE, mode="overwrite")
    logger.info("Loan product ingestion complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_PROD into Delta Lake loan_products table")
    parser.add_argument("--source", required=True, help="Path to legacy CDW_LN_PROD export (CSV or Parquet)")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_LoanProducts").getOrCreate()
    try:
        run(spark, args.source, args.format)
    except Exception:
        logger.exception("Loan product ingestion failed")
        sys.exit(1)
    finally:
        spark.stop()
