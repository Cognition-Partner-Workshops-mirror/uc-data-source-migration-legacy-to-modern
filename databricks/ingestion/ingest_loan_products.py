"""
Ingest loan products from legacy CDW_LN_PROD into Delta Lake loan_products table.

Source : CSV/Parquet export of CDW_LN_PROD
Target : loan_modernized.loan_products

Transformations applied:
  - Term months string -> INT
  - Min/max amount strings ("50,000") -> DECIMAL(12,2)
  - Product status code -> BOOLEAN (ACT -> true, INA -> false)
  - Date strings (MM/DD/YYYY) -> DATE
"""

import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PRODUCT_STATUS_MAP,
    expand_bool,
    parse_amount,
    parse_date,
    parse_int,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_loan_products")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/cdw/CDW_LN_PROD"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_modernized.loan_products"
QUARANTINE_PATH = "/mnt/landing/cdw/quarantine/loan_products"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "nullValue": "",
    "emptyValue": "",
}


def read_source(spark: SparkSession) -> DataFrame:
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for k, v in CSV_OPTIONS.items():
            reader = reader.option(k, v)
    return reader.load(SOURCE_PATH)


def transform(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    transformed = df.select(
        F.trim(F.col("PROD_CD")).alias("code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.trim(F.col("PROD_TYP_CD")).alias("type"),
        parse_int("PROD_TERM_MOS").alias("term_months"),
        F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
        parse_amount("PROD_MIN_AMT").alias("min_amount"),
        parse_amount("PROD_MAX_AMT").alias("max_amount"),
        expand_bool("PROD_STAT_CD", PRODUCT_STATUS_MAP).alias("is_active"),
        parse_date("PROD_EFF_DT").alias("effective_date"),
        parse_date("PROD_EXP_DT").alias("expiration_date"),
        F.current_timestamp().alias("_migration_ts"),
    )

    quarantine_condition = (
        F.col("code").isNull()
        | F.col("name").isNull()
        | F.col("type").isNull()
        | (F.trim(F.col("code")) == "")
    )
    quarantine_df = transformed.filter(quarantine_condition)
    good_df = transformed.filter(~quarantine_condition)

    return good_df, quarantine_df


def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    source_count = good_df.count() + quarantine_df.count()
    quarantine_count = quarantine_df.count()

    if quarantine_count > 0:
        logger.warning(
            "Quarantined %d loan product records", quarantine_count
        )
        quarantine_df.write.format("delta").mode("overwrite").save(QUARANTINE_PATH)

    good_count = good_df.count()
    logger.info("Writing %d loan product records to %s", good_count, TARGET_TABLE)

    good_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    return {
        "table": TARGET_TABLE,
        "source_count": source_count,
        "written_count": good_count,
        "quarantined_count": quarantine_count,
    }


def run(spark: SparkSession) -> dict:
    logger.info("Starting loan product ingestion from %s", SOURCE_PATH)
    raw = read_source(spark)
    logger.info("Read %d raw loan product records", raw.count())
    good, quarantine = transform(raw)
    stats = write_target(good, quarantine)
    logger.info("Loan product ingestion complete: %s", stats)
    return stats


if __name__ == "__main__":
    spark = SparkSession.builder.appName("ingest_loan_products").getOrCreate()
    result = run(spark)
    print(result)
