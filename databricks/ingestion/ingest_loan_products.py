"""
Ingestion script: CDW_LN_PROD → loan_warehouse.loan_products

Reads the legacy loan products table from a CSV/Parquet source, applies
column renames, type conversions, and status-to-boolean mapping, then
writes to the Delta Lake loan_products table.

Usage (Databricks notebook cell):
    ingest_loan_products(spark, source_path="/mnt/landing/cdw_ln_prod/")
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from databricks.ingestion.common import (
    PRODUCT_STATUS_MAP,
    expand_status_to_bool,
    parse_amount,
    parse_date,
    parse_int,
)

logger = logging.getLogger("migration.ingest_loan_products")

TARGET_TABLE = "loan_warehouse.loan_products"
SOURCE_TABLE = "CDW_LN_PROD"


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv") -> DataFrame:
    if file_format == "parquet":
        return spark.read.parquet(source_path)
    return (
        spark.read.option("header", "true")
        .option("inferSchema", "false")
        .csv(source_path)
    )


def transform(df: DataFrame) -> DataFrame:
    quarantine_condition = (
        F.col("PROD_CD").isNull()
        | F.col("PROD_DESC_TXT").isNull()
    )

    quarantined = df.filter(quarantine_condition)
    if quarantined.count() > 0:
        logger.warning(
            "Quarantined %d loan product records with null required fields",
            quarantined.count(),
        )
        quarantined.write.mode("append").format("delta").saveAsTable(
            "loan_warehouse._quarantine_loan_products"
        )

    clean = df.filter(~quarantine_condition)

    transformed = clean.select(
        F.trim(F.col("PROD_CD")).alias("code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.trim(F.col("PROD_TYP_CD")).alias("type"),
        parse_int(F.col("PROD_TERM_MOS")).alias("term_months"),
        F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
        parse_amount(F.col("PROD_MIN_AMT")).alias("min_amount"),
        parse_amount(F.col("PROD_MAX_AMT")).alias("max_amount"),
        expand_status_to_bool(F.col("PROD_STAT_CD"), PRODUCT_STATUS_MAP).alias("is_active"),
        parse_date(F.col("PROD_EFF_DT")).alias("effective_date"),
        parse_date(F.col("PROD_EXP_DT")).alias("expiration_date"),
        F.lit(SOURCE_TABLE).alias("_migration_src"),
        F.current_timestamp().alias("_migrated_at"),
    )

    return transformed


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    df.write.format("delta").mode(mode).saveAsTable(TARGET_TABLE)


def ingest_loan_products(
    spark: SparkSession,
    source_path: str,
    file_format: str = "csv",
    write_mode: str = "overwrite",
) -> dict:
    logger.info("Starting loan product ingestion from %s", source_path)

    raw = read_source(spark, source_path, file_format)
    source_count = raw.count()
    logger.info("Read %d records from source", source_count)

    transformed = transform(raw)
    target_count = transformed.count()
    logger.info("Transformed %d records (quarantined %d)", target_count, source_count - target_count)

    write_target(transformed, write_mode)
    logger.info("Wrote %d records to %s", target_count, TARGET_TABLE)

    return {"source_count": source_count, "target_count": target_count}
