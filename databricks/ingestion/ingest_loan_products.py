"""
Ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan products file, applies type conversions and
status-to-boolean mapping, and writes to the Delta Lake loan_products table.

Usage:
    spark-submit --master local[*] ingest_loan_products.py \
        --source /mnt/landing/cdw_ln_prod.csv \
        --format csv \
        --target loan_catalog.loan_warehouse.loan_products
"""

import argparse
import logging
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import BooleanType

from utils import (
    PRODUCT_STATUS_MAP,
    log_null_counts,
    parse_amount_expr,
    parse_date_expr,
    parse_int_expr,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("cdw_migration.loan_products")


def read_source(spark: SparkSession, path: str, fmt: str):
    if fmt == "csv":
        return spark.read.option("header", "true").option("inferSchema", "false").csv(path)
    elif fmt == "parquet":
        return spark.read.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform(df):
    source_count = df.count()
    logger.info("Source row count: %d", source_count)

    # Build is_active boolean from PROD_STAT_CD
    is_active_expr = (
        F.when(F.upper(F.trim(F.col("PROD_STAT_CD"))) == "ACT", F.lit(True))
        .when(F.upper(F.trim(F.col("PROD_STAT_CD"))) == "INA", F.lit(False))
        .otherwise(F.lit(None).cast(BooleanType()))
    )

    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_int_expr("PROD_TERM_MOS", "term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount_expr("PROD_MIN_AMT", "min_amount"),
        parse_amount_expr("PROD_MAX_AMT", "max_amount"),
        is_active_expr.alias("is_active"),
        parse_date_expr("PROD_EFF_DT", "effective_date"),
        parse_date_expr("PROD_EXP_DT", "expiration_date"),
        F.current_timestamp().alias("_ingestion_ts"),
    )

    required_cols = ["code", "name", "type", "term_months", "rate_type", "is_active"]
    log_null_counts(transformed, "loan_products", required_cols)

    target_count = transformed.count()
    logger.info("Target row count: %d", target_count)
    if source_count != target_count:
        logger.error("ROW COUNT MISMATCH: source=%d, target=%d", source_count, target_count)

    return transformed


def write_target(df, target_table: str, mode: str = "overwrite"):
    logger.info("Writing %d rows to %s (mode=%s)", df.count(), target_table, mode)
    df.write.format("delta").mode(mode).saveAsTable(target_table)
    logger.info("Write complete.")


def main():
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_PROD into loan_products Delta table")
    parser.add_argument("--source", required=True, help="Path to legacy loan products source file")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    parser.add_argument("--target", default="loan_catalog.loan_warehouse.loan_products", help="Target Delta table")
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"], help="Write mode")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_LoanProducts").getOrCreate()

    try:
        raw_df = read_source(spark, args.source, args.format)
        transformed_df = transform(raw_df)
        write_target(transformed_df, args.target, args.mode)
    except Exception:
        logger.exception("Loan products ingestion failed")
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
