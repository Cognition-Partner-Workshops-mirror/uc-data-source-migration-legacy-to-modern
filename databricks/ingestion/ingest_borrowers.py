"""
Ingestion script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads the legacy borrower master from a CSV/Parquet source file, applies all
column renames, type conversions, and status expansions defined in
data/mappings/column_mappings.md, then writes to the Delta Lake borrowers table.

Usage (Databricks notebook cell):
    %run ./common
    %run ./ingest_borrowers
    ingest_borrowers(spark, source_path="/mnt/landing/cdw_borr_mstr/")
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from databricks.ingestion.common import (
    BORROWER_STATUS_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_int,
    parse_timestamp,
)

logger = logging.getLogger("migration.ingest_borrowers")

TARGET_TABLE = "loan_warehouse.borrowers"
SOURCE_TABLE = "CDW_BORR_MSTR"


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv") -> DataFrame:
    """Read the legacy borrower source file.

    Supports csv (default) and parquet formats.
    """
    if file_format == "parquet":
        return spark.read.parquet(source_path)
    return (
        spark.read.option("header", "true")
        .option("inferSchema", "false")
        .csv(source_path)
    )


def transform(df: DataFrame) -> DataFrame:
    """Apply all borrower transformations per the column mapping spec."""
    quarantine_condition = (
        F.col("BORR_ID").isNull()
        | F.col("BORR_FST_NM").isNull()
        | F.col("BORR_LST_NM").isNull()
    )

    quarantined = df.filter(quarantine_condition)
    if quarantined.count() > 0:
        logger.warning(
            "Quarantined %d borrower records with null required fields (BORR_ID, BORR_FST_NM, BORR_LST_NM)",
            quarantined.count(),
        )
        quarantined.write.mode("append").format("delta").saveAsTable(
            "loan_warehouse._quarantine_borrowers"
        )

    clean = df.filter(~quarantine_condition)

    transformed = clean.select(
        F.col("BORR_ID").alias("external_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_date(F.col("BORR_DOB_DT")).alias("date_of_birth"),
        F.col("BORR_DOB_DT").alias("_raw_dob"),
        F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
        F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
        F.trim(F.col("BORR_CTY_NM")).alias("city"),
        F.trim(F.col("BORR_ST_CD")).alias("state"),
        F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),
        F.trim(F.col("BORR_PH_NBR")).alias("phone"),
        F.trim(F.col("BORR_EMAIL_ADDR")).alias("email"),
        parse_int(F.col("BORR_CRDT_SCR")).alias("credit_score"),
        F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),
        parse_amount(F.col("BORR_ANN_INCM")).alias("annual_income"),
        expand_status(F.col("BORR_STAT_CD"), BORROWER_STATUS_MAP).alias("status"),
        parse_timestamp(F.col("BORR_CRET_DT")).alias("created_at"),
        parse_timestamp(F.col("BORR_UPDT_DT")).alias("updated_at"),
        F.lit(SOURCE_TABLE).alias("_migration_src"),
        F.current_timestamp().alias("_migrated_at"),
    )

    date_parse_failures = transformed.filter(
        F.col("date_of_birth").isNull() & F.col("_raw_dob").isNotNull()
    )
    failure_count = date_parse_failures.count()
    if failure_count > 0:
        logger.warning(
            "Found %d records where BORR_DOB_DT could not be parsed to DATE",
            failure_count,
        )

    return transformed.drop("_raw_dob")


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    """Write transformed borrower data to the Delta Lake target table."""
    df.write.format("delta").mode(mode).partitionBy("state").saveAsTable(TARGET_TABLE)


def ingest_borrowers(
    spark: SparkSession,
    source_path: str,
    file_format: str = "csv",
    write_mode: str = "overwrite",
) -> dict:
    """End-to-end borrower ingestion entry point.

    Returns a dict with source_count and target_count for reconciliation.
    """
    logger.info("Starting borrower ingestion from %s", source_path)

    raw = read_source(spark, source_path, file_format)
    source_count = raw.count()
    logger.info("Read %d records from source", source_count)

    transformed = transform(raw)
    target_count = transformed.count()
    logger.info("Transformed %d records (quarantined %d)", target_count, source_count - target_count)

    write_target(transformed, write_mode)
    logger.info("Wrote %d records to %s", target_count, TARGET_TABLE)

    return {"source_count": source_count, "target_count": target_count}
