"""
Ingest CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master table (exported as CSV/Parquet) and writes
a cleaned, typed borrower dimension to the Delta Lake target.

Usage (Databricks notebook or spark-submit):
    %run ./transforms
    %run ./ingest_borrowers
    -- or --
    spark-submit ingest_borrowers.py --source /mnt/landing/cdw_borr_mstr --format csv
"""

import logging
import sys
from argparse import ArgumentParser

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    BORROWER_STATUS_MAP,
    expand_status_code_preserving,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_int,
    parse_legacy_timestamp,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ingest_borrowers")

TARGET_TABLE = "loan_warehouse.borrowers"


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    """Read the legacy CDW_BORR_MSTR export."""
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


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
        parse_legacy_int("BORR_CRDT_SCR").alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_legacy_amount("BORR_ANN_INCM").alias("annual_income"),
        expand_status_code_preserving("BORR_STAT_CD", BORROWER_STATUS_MAP).alias("status"),
        parse_legacy_timestamp("BORR_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("BORR_UPDT_DT").alias("updated_at"),
        F.col("BORR_ID").alias("_legacy_borr_id"),
        F.current_timestamp().alias("_ingestion_ts"),
    )

    # ---- Quality gates ----
    # Log rows with null required fields (first_name, last_name, external_id)
    null_required = transformed.filter(
        F.col("external_id").isNull()
        | F.col("first_name").isNull()
        | F.col("last_name").isNull()
    )
    null_count = null_required.count()
    if null_count > 0:
        logger.warning(
            "Found %d rows with NULL required fields (external_id/first_name/last_name). "
            "These rows will be quarantined.",
            null_count,
        )

    # Log rows where date parsing failed
    bad_dates = transformed.filter(
        F.col("date_of_birth").isNull() & F.col("_legacy_borr_id").isNotNull()
    )
    bad_date_count = bad_dates.count()
    if bad_date_count > 0:
        logger.warning(
            "Found %d rows where BORR_DOB_DT could not be parsed to DATE.", bad_date_count
        )

    # Log rows where amount parsing failed
    bad_income = transformed.filter(
        F.col("annual_income").isNull() & F.col("_legacy_borr_id").isNotNull()
    )
    bad_income_count = bad_income.count()
    if bad_income_count > 0:
        logger.warning(
            "Found %d rows where BORR_ANN_INCM could not be parsed to DECIMAL.",
            bad_income_count,
        )

    # Quarantine bad records to a separate path; keep good records
    good = transformed.filter(
        F.col("external_id").isNotNull()
        & F.col("first_name").isNotNull()
        & F.col("last_name").isNotNull()
    )

    quarantine = transformed.filter(
        F.col("external_id").isNull()
        | F.col("first_name").isNull()
        | F.col("last_name").isNull()
    )

    good_count = good.count()
    quarantine_count = quarantine.count()
    logger.info(
        "Transform complete: %d good rows, %d quarantined rows (source: %d)",
        good_count,
        quarantine_count,
        source_count,
    )

    return good, quarantine


def write_target(good: DataFrame, quarantine: DataFrame, quarantine_path: str) -> None:
    """Write good records to Delta and quarantine records to a separate location."""
    good.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)
    logger.info("Wrote %d rows to %s", good.count(), TARGET_TABLE)

    if quarantine.count() > 0:
        quarantine.write.format("delta").mode("overwrite").save(quarantine_path)
        logger.info("Wrote %d quarantined rows to %s", quarantine.count(), quarantine_path)


def main(source_path: str, source_format: str, quarantine_path: str) -> None:
    spark = SparkSession.builder.appName("CDW_BORR_MSTR_Ingestion").getOrCreate()

    logger.info("Reading source from %s (format=%s)", source_path, source_format)
    raw = read_source(spark, source_path, source_format)

    good, quarantine = transform(raw)
    write_target(good, quarantine, quarantine_path)

    logger.info("Borrower ingestion complete.")


if __name__ == "__main__":
    parser = ArgumentParser(description="Ingest CDW_BORR_MSTR into borrowers Delta table")
    parser.add_argument("--source", required=True, help="Path to source data")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument(
        "--quarantine",
        default="/mnt/quarantine/borrowers",
        help="Path for quarantined records",
    )
    args = parser.parse_args()
    main(args.source, args.format, args.quarantine)
