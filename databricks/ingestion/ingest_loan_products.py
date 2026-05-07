"""
Ingest CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan products table and writes a cleaned reference
dimension to the Delta Lake target.

Usage:
    spark-submit ingest_loan_products.py --source /mnt/landing/cdw_ln_prod --format csv
"""

import logging
from argparse import ArgumentParser

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PRODUCT_STATUS_MAP,
    expand_status_to_boolean,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_int,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ingest_loan_products")

TARGET_TABLE = "loan_warehouse.loan_products"


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform(df: DataFrame) -> DataFrame:
    source_count = df.count()
    logger.info("Source CDW_LN_PROD row count: %d", source_count)

    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_legacy_int("PROD_TERM_MOS").alias("term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_legacy_amount("PROD_MIN_AMT").alias("min_amount"),
        parse_legacy_amount("PROD_MAX_AMT").alias("max_amount"),
        expand_status_to_boolean("PROD_STAT_CD", PRODUCT_STATUS_MAP, default=False).alias(
            "is_active"
        ),
        parse_legacy_date("PROD_EFF_DT").alias("effective_date"),
        parse_legacy_date("PROD_EXP_DT").alias("expiration_date"),
        F.col("PROD_CD").alias("_legacy_prod_cd"),
        F.current_timestamp().alias("_ingestion_ts"),
    )

    # Quality: log rows missing required fields
    null_required = transformed.filter(
        F.col("code").isNull() | F.col("name").isNull() | F.col("type").isNull()
    )
    null_count = null_required.count()
    if null_count > 0:
        logger.warning(
            "Found %d loan product rows with NULL required fields (code/name/type).",
            null_count,
        )

    bad_term = transformed.filter(F.col("term_months").isNull())
    if bad_term.count() > 0:
        logger.warning(
            "Found %d rows where PROD_TERM_MOS could not be parsed to INT.",
            bad_term.count(),
        )

    good = transformed.filter(
        F.col("code").isNotNull() & F.col("name").isNotNull() & F.col("type").isNotNull()
    )
    quarantine = transformed.filter(
        F.col("code").isNull() | F.col("name").isNull() | F.col("type").isNull()
    )

    logger.info(
        "Transform complete: %d good rows, %d quarantined (source: %d)",
        good.count(),
        quarantine.count(),
        source_count,
    )
    return good, quarantine


def write_target(good: DataFrame, quarantine: DataFrame, quarantine_path: str) -> None:
    good.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)
    logger.info("Wrote %d rows to %s", good.count(), TARGET_TABLE)

    if quarantine.count() > 0:
        quarantine.write.format("delta").mode("overwrite").save(quarantine_path)
        logger.info("Wrote %d quarantined rows to %s", quarantine.count(), quarantine_path)


def main(source_path: str, source_format: str, quarantine_path: str) -> None:
    spark = SparkSession.builder.appName("CDW_LN_PROD_Ingestion").getOrCreate()

    logger.info("Reading source from %s (format=%s)", source_path, source_format)
    raw = read_source(spark, source_path, source_format)

    good, quarantine = transform(raw)
    write_target(good, quarantine, quarantine_path)
    logger.info("Loan product ingestion complete.")


if __name__ == "__main__":
    parser = ArgumentParser(description="Ingest CDW_LN_PROD into loan_products Delta table")
    parser.add_argument("--source", required=True, help="Path to source data")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument(
        "--quarantine",
        default="/mnt/quarantine/loan_products",
        help="Path for quarantined records",
    )
    args = parser.parse_args()
    main(args.source, args.format, args.quarantine)
