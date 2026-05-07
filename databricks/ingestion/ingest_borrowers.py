"""
Ingestion script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads the legacy borrower master extract (CSV or Parquet), applies type
conversions and code expansions, then writes to the modern Delta Lake table.

Usage (Databricks notebook or job):
    %run ./ingest_borrowers
  or:
    spark-submit ingest_borrowers.py --source /mnt/landing/cdw_borr_mstr/
"""

import argparse
import sys
import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    BORROWER_STATUS_MAP,
    expand_status_code,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_integer,
    parse_legacy_timestamp,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_borrowers")

TARGET_TABLE = "loan_warehouse.borrowers"


def read_source(spark: SparkSession, source_path: str) -> DataFrame:
    """Read the legacy borrower extract. Supports CSV and Parquet."""
    if source_path.endswith(".parquet") or source_path.endswith("/parquet"):
        return spark.read.parquet(source_path)
    return spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)


def transform(df: DataFrame) -> DataFrame:
    """Apply all column mappings and type conversions for borrowers."""
    source_count = df.count()
    logger.info("Source CDW_BORR_MSTR row count: %d", source_count)

    transformed = df.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_legacy_date("BORR_DOB_DT").alias("date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        parse_legacy_integer("BORR_CRDT_SCR").alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_legacy_amount("BORR_ANN_INCM").alias("annual_income"),
        expand_status_code("BORR_STAT_CD", BORROWER_STATUS_MAP).alias("status"),
        parse_legacy_timestamp("BORR_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("BORR_UPDT_DT").alias("updated_at"),
        F.lit("CDW_BORR_MSTR").alias("_migration_source"),
        F.current_timestamp().alias("_migrated_at"),
    )

    # Log records with null required fields (don't drop them)
    null_first = transformed.filter(F.col("first_name").isNull()).count()
    null_last = transformed.filter(F.col("last_name").isNull()).count()
    null_ext_id = transformed.filter(F.col("external_id").isNull()).count()

    if null_first > 0:
        logger.warning("Records with NULL first_name: %d", null_first)
    if null_last > 0:
        logger.warning("Records with NULL last_name: %d", null_last)
    if null_ext_id > 0:
        logger.warning("Records with NULL external_id: %d", null_ext_id)

    # Flag records where date parsing failed but source had a value
    bad_dob = transformed.join(
        df.select("BORR_ID", "BORR_DOB_DT"), transformed["external_id"] == df["BORR_ID"]
    ).filter(
        F.col("date_of_birth").isNull() & F.col("BORR_DOB_DT").isNotNull()
    ).count()

    if bad_dob > 0:
        logger.warning("Records with unparseable date_of_birth: %d", bad_dob)

    target_count = transformed.count()
    logger.info("Transformed row count: %d", target_count)
    if source_count != target_count:
        logger.error(
            "ROW COUNT MISMATCH: source=%d, transformed=%d", source_count, target_count
        )

    return transformed


def write_target(df: DataFrame) -> None:
    """Write the transformed borrower data to Delta Lake."""
    df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).partitionBy("state").saveAsTable(TARGET_TABLE)
    logger.info("Successfully wrote %d rows to %s", df.count(), TARGET_TABLE)


def main(source_path: str) -> None:
    spark = SparkSession.builder.appName("Ingest_CDW_BORR_MSTR").getOrCreate()
    try:
        raw_df = read_source(spark, source_path)
        transformed_df = transform(raw_df)
        write_target(transformed_df)
    except Exception:
        logger.exception("Borrower ingestion failed")
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_BORR_MSTR to Delta Lake")
    parser.add_argument("--source", required=True, help="Path to legacy borrower CSV/Parquet")
    args = parser.parse_args()
    main(args.source)
