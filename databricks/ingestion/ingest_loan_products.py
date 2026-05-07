"""
Ingest CDW_LN_PROD (legacy) -> loan_products (Delta Lake).

Source: CSV or Parquet export of the CDW_LN_PROD table.
Target: loan_warehouse.loan_products Delta table.

Transformations applied:
  - Rename cryptic column names to modern names
  - Parse term_months string to IntegerType
  - Parse comma-formatted min/max amount strings to DecimalType
  - Map product status code to boolean is_active (ACT -> true, INA -> false)
  - Parse MM/DD/YYYY date strings for effective/expiration dates
  - Generate surrogate id
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from databricks.ingestion.transformations import (
    add_row_quality_flag,
    expand_product_status_col,
    log_null_counts,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
)
from databricks.schemas.loan_products import (
    LOAN_PRODUCTS_PARTITION_COLS,
    LOAN_PRODUCTS_PATH,
)

logger = logging.getLogger("loan_migration.ingest_loan_products")

REQUIRED_COLS = ["code", "name", "type", "term_months", "rate_type"]

SOURCE_FILE_DEFAULT = "/mnt/legacy/CDW_LN_PROD"


def read_source(spark: SparkSession, path: str = SOURCE_FILE_DEFAULT, fmt: str = "csv") -> DataFrame:
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def transform(source_df: DataFrame) -> DataFrame:
    transformed = source_df.select(
        F.monotonically_increasing_id().alias("id"),
        F.col("PROD_CD").alias("code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_int_col("PROD_TERM_MOS", "term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount_col("PROD_MIN_AMT", "min_amount"),
        parse_amount_col("PROD_MAX_AMT", "max_amount"),
        expand_product_status_col("PROD_STAT_CD", "is_active"),
        parse_date_col("PROD_EFF_DT", "effective_date"),
        parse_date_col("PROD_EXP_DT", "expiration_date"),
    )
    return add_row_quality_flag(transformed, REQUIRED_COLS)


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    clean_df = df.drop("_has_quality_issue")
    writer = clean_df.write.format("delta").mode(mode)
    if LOAN_PRODUCTS_PARTITION_COLS:
        writer = writer.partitionBy(*LOAN_PRODUCTS_PARTITION_COLS)
    writer.save(LOAN_PRODUCTS_PATH)
    logger.info("Wrote loan_products to %s", LOAN_PRODUCTS_PATH)


def run(spark: SparkSession, source_path: str = SOURCE_FILE_DEFAULT, fmt: str = "csv") -> dict:
    logger.info("Starting loan_products ingestion from %s", source_path)

    source_df = read_source(spark, source_path, fmt)
    source_count = source_df.count()
    logger.info("Source row count: %d", source_count)

    transformed_df = transform(source_df)
    target_count = transformed_df.count()

    null_issues = log_null_counts(transformed_df, "loan_products", REQUIRED_COLS)
    quality_issues = transformed_df.filter(F.col("_has_quality_issue")).count()

    write_target(transformed_df)

    summary = {
        "table": "loan_products",
        "source_count": source_count,
        "target_count": target_count,
        "records_with_quality_issues": quality_issues,
        "null_counts": null_issues,
    }
    logger.info("Loan products ingestion complete: %s", summary)
    return summary
