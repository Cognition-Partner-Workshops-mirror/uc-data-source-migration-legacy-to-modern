"""Ingest legacy CDW_LN_PROD into modern loan_products Delta table.

Expected source: CSV or Parquet file at the configured landing path with columns
matching the CDW_LN_PROD schema (all VARCHAR/string).
"""

import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    PRODUCT_STATUS_MAP,
    drop_flag_columns,
    log_parse_errors,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
)

logger = logging.getLogger("ingestion.loan_products")
logging.basicConfig(level=logging.INFO)

SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_ln_prod"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"


def read_source(spark: SparkSession, path: str = SOURCE_PATH, fmt: str = SOURCE_FORMAT) -> DataFrame:
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(path)


def transform(df: DataFrame) -> DataFrame:
    """Apply all column mappings and type conversions for loan products."""
    # Direct renames
    df = (
        df
        .withColumnRenamed("PROD_CD", "code")
        .withColumnRenamed("PROD_DESC_TXT", "name")
        .withColumnRenamed("PROD_TYP_CD", "type")
        .withColumnRenamed("PROD_RT_TYP", "rate_type")
    )

    # Integer parsing
    df = parse_int_col(df, "PROD_TERM_MOS", "term_months")

    # Amount parsing
    df = parse_amount_col(df, "PROD_MIN_AMT", "min_amount")
    df = parse_amount_col(df, "PROD_MAX_AMT", "max_amount")

    # Status to boolean
    status_map = F.create_map(
        *[item for kv in PRODUCT_STATUS_MAP.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    df = (
        df
        .withColumn(
            "is_active",
            F.coalesce(status_map[F.col("PROD_STAT_CD")], F.lit(False)),
        )
        .withColumn(
            "_flag_is_active_unknown_code",
            F.when(
                F.col("PROD_STAT_CD").isNotNull() & status_map[F.col("PROD_STAT_CD")].isNull(),
                F.lit(True),
            ).otherwise(F.lit(False)),
        )
    )

    # Date parsing
    df = parse_date_col(df, "PROD_EFF_DT", "effective_date")
    df = parse_date_col(df, "PROD_EXP_DT", "expiration_date")

    # Drop replaced legacy columns
    df = df.drop(
        "PROD_TERM_MOS",
        "PROD_MIN_AMT",
        "PROD_MAX_AMT",
        "PROD_STAT_CD",
        "PROD_EFF_DT",
        "PROD_EXP_DT",
    )

    return df


def write_target(df: DataFrame, table: str = TARGET_TABLE) -> None:
    (
        df
        .write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(table)
    )


def run(spark: SparkSession) -> int:
    logger.info("Reading legacy loan product data from %s", SOURCE_PATH)
    raw_df = read_source(spark)
    source_count = raw_df.count()
    logger.info("Source row count: %d", source_count)

    logger.info("Applying transformations")
    transformed_df = transform(raw_df)

    log_parse_errors(transformed_df, "loan_products", logger)
    clean_df = drop_flag_columns(transformed_df)

    logger.info("Writing to %s", TARGET_TABLE)
    write_target(clean_df)

    target_count = spark.table(TARGET_TABLE).count()
    logger.info("Target row count: %d", target_count)

    if source_count != target_count:
        logger.error(
            "Row count mismatch! source=%d target=%d", source_count, target_count
        )

    return source_count


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest_LoanProducts").getOrCreate()
    run(spark)
