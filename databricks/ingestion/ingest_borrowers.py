"""
Ingest borrowers from legacy CDW_BORR_MSTR into Delta Lake borrowers table.

Source : CSV/Parquet export of CDW_BORR_MSTR
Target : loan_modernized.borrowers

Transformations applied:
  - Date strings (MM/DD/YYYY) -> DATE / TIMESTAMP
  - Annual income string ("92,500") -> DECIMAL(12,2)
  - Credit score string -> INT
  - Status code expansion (ACT -> ACTIVE, INA -> INACTIVE)
  - BORR_REC_TYP preserved in _legacy_record_type for audit, then dropped
"""

import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    BORROWER_STATUS_MAP,
    expand_code,
    parse_amount,
    parse_date,
    parse_int,
    parse_timestamp,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_borrowers")

# ---------------------------------------------------------------------------
# Configuration — adjust these paths per environment
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/cdw/CDW_BORR_MSTR"  # CSV or Parquet
SOURCE_FORMAT = "csv"  # change to "parquet" if applicable
TARGET_TABLE = "loan_modernized.borrowers"
QUARANTINE_PATH = "/mnt/landing/cdw/quarantine/borrowers"

# CSV read options (ignored when SOURCE_FORMAT != "csv")
CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "nullValue": "",
    "emptyValue": "",
}


def read_source(spark: SparkSession) -> DataFrame:
    """Read the legacy borrower source file."""
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for k, v in CSV_OPTIONS.items():
            reader = reader.option(k, v)
    return reader.load(SOURCE_PATH)


def transform(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Apply all column mappings and type conversions.

    Returns
    -------
    good_df : DataFrame
        Records that passed transformation with no critical nulls.
    quarantine_df : DataFrame
        Records with NULL first_name or last_name (required fields).
    """
    transformed = df.select(
        F.trim(F.col("BORR_ID")).alias("external_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
        F.trim(F.col("BORR_SSN_ENCR")).alias("ssn_hash"),
        parse_date("BORR_DOB_DT").alias("date_of_birth"),
        F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
        F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
        F.trim(F.col("BORR_CTY_NM")).alias("city"),
        F.trim(F.col("BORR_ST_CD")).alias("state"),
        F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),
        F.trim(F.col("BORR_PH_NBR")).alias("phone"),
        F.trim(F.col("BORR_EMAIL_ADDR")).alias("email"),
        parse_int("BORR_CRDT_SCR").alias("credit_score"),
        F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),
        parse_amount("BORR_ANN_INCM").alias("annual_income"),
        expand_code("BORR_STAT_CD", BORROWER_STATUS_MAP).alias("status"),
        parse_timestamp("BORR_CRET_DT").alias("created_at"),
        parse_timestamp("BORR_UPDT_DT").alias("updated_at"),
        F.trim(F.col("BORR_REC_TYP")).alias("_legacy_record_type"),
        F.current_timestamp().alias("_migration_ts"),
    )

    # Quarantine records missing required fields
    quarantine_condition = (
        F.col("external_id").isNull()
        | F.col("first_name").isNull()
        | F.col("last_name").isNull()
        | (F.trim(F.col("first_name")) == "")
        | (F.trim(F.col("last_name")) == "")
    )
    quarantine_df = transformed.filter(quarantine_condition)
    good_df = transformed.filter(~quarantine_condition)

    return good_df, quarantine_df


def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    """Write good records to Delta and quarantine bad ones."""
    source_count = good_df.count() + quarantine_df.count()
    quarantine_count = quarantine_df.count()

    if quarantine_count > 0:
        logger.warning(
            "Quarantined %d borrower records with missing required fields",
            quarantine_count,
        )
        quarantine_df.write.format("delta").mode("overwrite").save(QUARANTINE_PATH)

    good_count = good_df.count()
    logger.info("Writing %d borrower records to %s", good_count, TARGET_TABLE)

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
    """End-to-end ingestion entry point."""
    logger.info("Starting borrower ingestion from %s", SOURCE_PATH)
    raw = read_source(spark)
    logger.info("Read %d raw borrower records", raw.count())
    good, quarantine = transform(raw)
    stats = write_target(good, quarantine)
    logger.info("Borrower ingestion complete: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("ingest_borrowers").getOrCreate()
    result = run(spark)
    print(result)
