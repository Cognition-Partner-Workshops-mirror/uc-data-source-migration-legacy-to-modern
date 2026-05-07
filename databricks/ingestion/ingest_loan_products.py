"""
Ingest legacy CDW_LN_PROD into Delta Lake loan_products table.

Reads loan product reference data, converts amount strings and dates,
maps status codes to boolean is_active flag, and writes to
loan_warehouse.loan_products.

Usage:
    spark-submit ingest_loan_products.py [--source /mnt/landing/cdw_ln_prod.csv]
"""

import sys
import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import BooleanType

from transform_utils import (
    PRODUCT_STATUS_MAP,
    collect_parse_errors,
    drop_parse_error_columns,
    parse_amount_column,
    parse_date_column,
    parse_int_column,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_loan_products")

DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_ln_prod"
DEFAULT_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(path)
    logger.info("Read %d rows from source %s (%s)", df.count(), path, fmt)
    return df


def transform_loan_products(df: DataFrame) -> DataFrame:
    """Apply all transformations for CDW_LN_PROD -> loan_products."""
    logger.info("Starting loan product transformations")

    # -- Date fields --------------------------------------------------------
    df = parse_date_column(df, "PROD_EFF_DT", "effective_date")
    df = parse_date_column(df, "PROD_EXP_DT", "expiration_date")

    # -- Numeric fields -----------------------------------------------------
    df = parse_int_column(df, "PROD_TERM_MOS", "term_months")
    df = parse_amount_column(df, "PROD_MIN_AMT", "min_amount")
    df = parse_amount_column(df, "PROD_MAX_AMT", "max_amount")

    # -- Status to boolean --------------------------------------------------
    status_map = F.create_map([F.lit(x) for pair in PRODUCT_STATUS_MAP.items() for x in (pair[0], str(pair[1]))])
    df = (
        df.withColumn(
            "is_active",
            F.when(
                status_map[F.upper(F.trim(F.col("PROD_STAT_CD")))].isNotNull(),
                status_map[F.upper(F.trim(F.col("PROD_STAT_CD")))].cast(BooleanType()),
            ).otherwise(F.lit(None).cast(BooleanType())),
        )
        .withColumn(
            "_is_active_unmapped",
            F.when(
                F.col("PROD_STAT_CD").isNotNull()
                & status_map[F.upper(F.trim(F.col("PROD_STAT_CD")))].isNull(),
                True,
            ).otherwise(False),
        )
    )

    # -- Direct-copy renames ------------------------------------------------
    df = (
        df.withColumnRenamed("PROD_CD", "code")
          .withColumnRenamed("PROD_DESC_TXT", "name")
          .withColumnRenamed("PROD_TYP_CD", "type")
          .withColumnRenamed("PROD_RT_TYP", "rate_type")
    )

    # -- Lineage metadata ---------------------------------------------------
    df = (
        df.withColumn("_migration_source", F.lit("CDW_LN_PROD"))
          .withColumn("_migrated_at", F.current_timestamp())
    )

    return df


def validate_and_log_errors(df: DataFrame) -> DataFrame:
    error_summary = collect_parse_errors(df, "loan_products")
    if error_summary.count() > 0:
        logger.warning("Loan product parse errors detected:")
        error_summary.show(truncate=False)
    else:
        logger.info("No parse errors in loan product data")
    return drop_parse_error_columns(df)


def select_target_columns(df: DataFrame) -> DataFrame:
    return df.select(
        "code",
        "name",
        "type",
        "term_months",
        "rate_type",
        "min_amount",
        "max_amount",
        "is_active",
        "effective_date",
        "expiration_date",
        "_migration_source",
        "_migrated_at",
    )


def write_to_delta(df: DataFrame, mode: str = "overwrite") -> None:
    record_count = df.count()
    logger.info("Writing %d loan product records to %s", record_count, TARGET_TABLE)
    (
        df.write
          .format("delta")
          .mode(mode)
          .option("mergeSchema", "true")
          .saveAsTable(TARGET_TABLE)
    )
    logger.info("Successfully wrote %d records to %s", record_count, TARGET_TABLE)


def run(source_path: str = DEFAULT_SOURCE_PATH, source_format: str = DEFAULT_SOURCE_FORMAT) -> None:
    spark = SparkSession.builder.appName("CDW_LoanProduct_Ingestion").getOrCreate()

    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform_loan_products(raw_df)
    clean_df = validate_and_log_errors(transformed_df)
    final_df = select_target_columns(clean_df)
    write_to_delta(final_df)

    logger.info("Loan product ingestion complete")


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE_PATH
    fmt = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SOURCE_FORMAT
    run(source_path=source, source_format=fmt)
