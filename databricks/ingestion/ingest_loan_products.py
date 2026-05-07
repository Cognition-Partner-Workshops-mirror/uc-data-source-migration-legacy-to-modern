"""
Ingestion script: CDW_LN_PROD → loan_warehouse.loan_products

Reads the legacy loan product extract, applies type conversions and maps the
product status code to a boolean is_active flag.

Usage:
    spark-submit ingest_loan_products.py --source /mnt/landing/cdw_ln_prod/
"""

import argparse
import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PRODUCT_STATUS_MAP,
    expand_status_to_boolean,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_integer,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_loan_products")

TARGET_TABLE = "loan_warehouse.loan_products"


def read_source(spark: SparkSession, source_path: str) -> DataFrame:
    """Read the legacy loan product extract."""
    if source_path.endswith(".parquet") or source_path.endswith("/parquet"):
        return spark.read.parquet(source_path)
    return spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)


def transform(df: DataFrame) -> DataFrame:
    """Apply all column mappings and type conversions for loan products."""
    source_count = df.count()
    logger.info("Source CDW_LN_PROD row count: %d", source_count)

    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_legacy_integer("PROD_TERM_MOS").alias("term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_legacy_amount("PROD_MIN_AMT").alias("min_amount"),
        parse_legacy_amount("PROD_MAX_AMT").alias("max_amount"),
        expand_status_to_boolean("PROD_STAT_CD", PRODUCT_STATUS_MAP).alias("is_active"),
        parse_legacy_date("PROD_EFF_DT").alias("effective_date"),
        parse_legacy_date("PROD_EXP_DT").alias("expiration_date"),
        F.lit("CDW_LN_PROD").alias("_migration_source"),
        F.current_timestamp().alias("_migrated_at"),
    )

    # Log validation warnings
    null_code = transformed.filter(F.col("code").isNull()).count()
    null_name = transformed.filter(F.col("name").isNull()).count()
    null_term = transformed.filter(F.col("term_months").isNull()).count()

    if null_code > 0:
        logger.warning("Records with NULL code: %d", null_code)
    if null_name > 0:
        logger.warning("Records with NULL name: %d", null_name)
    if null_term > 0:
        logger.warning("Records with NULL term_months (parse failure): %d", null_term)

    target_count = transformed.count()
    logger.info("Transformed row count: %d", target_count)
    if source_count != target_count:
        logger.error(
            "ROW COUNT MISMATCH: source=%d, transformed=%d", source_count, target_count
        )

    return transformed


def write_target(df: DataFrame) -> None:
    """Write the transformed loan products to Delta Lake."""
    df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)
    logger.info("Successfully wrote %d rows to %s", df.count(), TARGET_TABLE)


def main(source_path: str) -> None:
    spark = SparkSession.builder.appName("Ingest_CDW_LN_PROD").getOrCreate()
    try:
        raw_df = read_source(spark, source_path)
        transformed_df = transform(raw_df)
        write_target(transformed_df)
    except Exception:
        logger.exception("Loan product ingestion failed")
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_PROD to Delta Lake")
    parser.add_argument("--source", required=True, help="Path to legacy loan product CSV/Parquet")
    args = parser.parse_args()
    main(args.source)
