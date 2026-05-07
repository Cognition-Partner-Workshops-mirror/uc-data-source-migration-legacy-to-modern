"""
Ingest loan products from legacy CDW_LN_PROD into the modern ``loan_products`` Delta table.

Expected source: CSV or Parquet export of the CDW_LN_PROD table.

Usage:
    from ingestion.ingest_loan_products import run
    run(spark, source_path="dbfs:/mnt/legacy/cdw_ln_prod/", source_format="csv")
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from .transforms import (
    expand_product_active,
    parse_amount,
    parse_date,
    parse_int,
)

logger = logging.getLogger("ingestion.loan_products")

TARGET_TABLE = "loan_warehouse.loan_products"

LEGACY_SCHEMA = StructType([
    StructField("PROD_CD", StringType(), True),
    StructField("PROD_DESC_TXT", StringType(), True),
    StructField("PROD_TYP_CD", StringType(), True),
    StructField("PROD_TERM_MOS", StringType(), True),
    StructField("PROD_RT_TYP", StringType(), True),
    StructField("PROD_MIN_AMT", StringType(), True),
    StructField("PROD_MAX_AMT", StringType(), True),
    StructField("PROD_STAT_CD", StringType(), True),
    StructField("PROD_EFF_DT", StringType(), True),
    StructField("PROD_EXP_DT", StringType(), True),
])


def read_source(spark: SparkSession, path: str, fmt: str = "csv") -> DataFrame:
    reader = spark.read.schema(LEGACY_SCHEMA)
    if fmt == "csv":
        return reader.option("header", "true").csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform(df: DataFrame) -> DataFrame:
    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_int("PROD_TERM_MOS").alias("term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount("PROD_MIN_AMT").alias("min_amount"),
        parse_amount("PROD_MAX_AMT").alias("max_amount"),
        expand_product_active("PROD_STAT_CD"),
        parse_date("PROD_EFF_DT").alias("effective_date"),
        parse_date("PROD_EXP_DT").alias("expiration_date"),
    )

    transformed = transformed.withColumn(
        "_is_valid",
        F.col("code").isNotNull() & F.col("name").isNotNull(),
    )

    invalid_count = transformed.filter(~F.col("_is_valid")).count()
    if invalid_count > 0:
        logger.warning(
            "Loan product ingestion: %d rows have null code or name", invalid_count
        )

    return transformed


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    output = df.drop("_is_valid")
    (
        output.write
        .format("delta")
        .mode(mode)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info("Wrote %d rows to %s (mode=%s)", output.count(), TARGET_TABLE, mode)


def run(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
    write_mode: str = "overwrite",
) -> DataFrame:
    logger.info("Starting loan product ingestion from %s (%s)", source_path, source_format)
    raw = read_source(spark, source_path, source_format)
    logger.info("Read %d raw loan product records", raw.count())

    result = transform(raw)
    write_target(result, mode=write_mode)
    return result
