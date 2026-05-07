"""
Ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan products reference table, applies type conversions
and status-to-boolean transformation, and writes to the modern Delta Lake table.

Usage:
    spark-submit --master local[*] ingest_loan_products.py \
        --source-path /mnt/legacy/cdw_ln_prod \
        --source-format csv \
        --target-table loan_warehouse.loan_products \
        --error-path /mnt/migration/errors/loan_products
"""

import argparse
import logging
import sys
from datetime import datetime

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PRODUCT_STATUS_MAP,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_loan_products")


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.option("header", "true")
    if fmt == "csv":
        reader = reader.option("inferSchema", "false")
    return reader.format(fmt).load(path)


def transform(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    run_ts = datetime.utcnow().isoformat()

    # Build the is_active boolean from PROD_STAT_CD
    is_active_expr = F.lit(None).cast("boolean")
    for code, val in PRODUCT_STATUS_MAP.items():
        is_active_expr = F.when(F.col("PROD_STAT_CD") == code, F.lit(val)).otherwise(
            is_active_expr
        )

    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_int_col("PROD_TERM_MOS").alias("term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount_col("PROD_MIN_AMT").alias("min_amount"),
        parse_amount_col("PROD_MAX_AMT").alias("max_amount"),
        is_active_expr.alias("is_active"),
        parse_date_col("PROD_EFF_DT").alias("effective_date"),
        parse_date_col("PROD_EXP_DT").alias("expiration_date"),
        F.lit("CDW_LN_PROD").alias("_migration_source"),
        F.lit(run_ts).cast("timestamp").alias("_migrated_at"),
    )

    required_cols = ["code", "name", "type", "term_months", "rate_type"]
    error_condition = F.lit(False)
    for col_name in required_cols:
        error_condition = error_condition | F.col(col_name).isNull()

    error_df = transformed.filter(error_condition).withColumn(
        "_error_reason",
        F.concat_ws(
            "; ",
            *[F.when(F.col(c).isNull(), F.lit(f"{c} is NULL")) for c in required_cols],
        ),
    )
    good_df = transformed.filter(~error_condition)

    return good_df, error_df


def write_target(df: DataFrame, table: str) -> None:
    df.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(table)


def write_errors(df: DataFrame, path: str) -> None:
    if df.count() > 0:
        df.write.format("delta").mode("append").save(path)
        logger.warning("Wrote %d error records to %s", df.count(), path)
    else:
        logger.info("No error records to write.")


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_PROD -> loan_products")
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--target-table", default="loan_warehouse.loan_products")
    parser.add_argument("--error-path", default="/mnt/migration/errors/loan_products")
    opts = parser.parse_args(args)

    spark = SparkSession.builder.appName("Ingest_LoanProducts").getOrCreate()

    logger.info("Reading legacy loan products from %s (%s)", opts.source_path, opts.source_format)
    source_df = read_source(spark, opts.source_path, opts.source_format)
    source_count = source_df.count()
    logger.info("Source row count: %d", source_count)

    good_df, error_df = transform(source_df)
    good_count = good_df.count()
    error_count = error_df.count()
    logger.info("Transformed: %d good, %d errors", good_count, error_count)

    write_target(good_df, opts.target_table)
    write_errors(error_df, opts.error_path)

    logger.info(
        "Loan products ingestion complete. Source=%d, Loaded=%d, Errors=%d",
        source_count,
        good_count,
        error_count,
    )

    if source_count != good_count + error_count:
        logger.error(
            "ROW COUNT MISMATCH: source=%d != good(%d) + error(%d)",
            source_count,
            good_count,
            error_count,
        )
        sys.exit(1)

    spark.stop()


if __name__ == "__main__":
    main()
