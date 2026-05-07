"""
Ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master table (simulated as CSV/Parquet source),
applies type conversions and status expansion, and writes to the modern
Delta Lake borrowers table.

Usage (Databricks notebook or spark-submit):
    spark-submit --master local[*] ingest_borrowers.py \
        --source-path /mnt/legacy/cdw_borr_mstr \
        --source-format csv \
        --target-table loan_warehouse.borrowers \
        --error-path /mnt/migration/errors/borrowers
"""

import argparse
import logging
import sys
from datetime import datetime

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    BORROWER_STATUS_MAP,
    expand_status_col,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_borrowers")


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    """Read legacy CDW_BORR_MSTR from CSV or Parquet source."""
    reader = spark.read.option("header", "true")
    if fmt == "csv":
        reader = reader.option("inferSchema", "false")  # keep everything as string
    return reader.format(fmt).load(path)


def transform(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Apply all transformations from legacy to modern schema.

    Returns:
        (good_df, error_df) where error_df contains rows that failed
        required-field validation.
    """
    run_ts = datetime.utcnow().isoformat()

    transformed = df.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_date_col("BORR_DOB_DT").alias("date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        parse_int_col("BORR_CRDT_SCR").alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount_col("BORR_ANN_INCM").alias("annual_income"),
        expand_status_col("BORR_STAT_CD", BORROWER_STATUS_MAP).alias("status"),
        parse_timestamp_col("BORR_CRET_DT").alias("created_at"),
        parse_timestamp_col("BORR_UPDT_DT").alias("updated_at"),
        F.lit("CDW_BORR_MSTR").alias("_migration_source"),
        F.lit(run_ts).cast("timestamp").alias("_migrated_at"),
    )

    # Validate required fields
    required_cols = ["external_id", "first_name", "last_name"]
    error_condition = F.lit(False)
    for col_name in required_cols:
        error_condition = error_condition | F.col(col_name).isNull()

    error_df = transformed.filter(error_condition).withColumn(
        "_error_reason",
        F.concat_ws(
            "; ",
            *[
                F.when(F.col(c).isNull(), F.lit(f"{c} is NULL"))
                for c in required_cols
            ],
        ),
    )

    good_df = transformed.filter(~error_condition)

    return good_df, error_df


def write_target(df: DataFrame, table: str) -> None:
    """Write transformed borrower data to Delta Lake table."""
    df.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(table)


def write_errors(df: DataFrame, path: str) -> None:
    """Write rejected records to error path for review."""
    if df.count() > 0:
        df.write.format("delta").mode("append").save(path)
        logger.warning("Wrote %d error records to %s", df.count(), path)
    else:
        logger.info("No error records to write.")


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest CDW_BORR_MSTR -> borrowers")
    parser.add_argument("--source-path", required=True, help="Path to legacy source data")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--target-table", default="loan_warehouse.borrowers")
    parser.add_argument("--error-path", default="/mnt/migration/errors/borrowers")
    opts = parser.parse_args(args)

    spark = SparkSession.builder.appName("Ingest_Borrowers").getOrCreate()

    logger.info("Reading legacy borrowers from %s (%s)", opts.source_path, opts.source_format)
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
        "Borrower ingestion complete. Source=%d, Loaded=%d, Errors=%d",
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
