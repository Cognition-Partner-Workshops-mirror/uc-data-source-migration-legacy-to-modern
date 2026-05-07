"""
Ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master extract (CSV or Parquet), applies column
renaming, type conversions, and status expansion, then writes to the Delta
Lake borrowers table.

Usage (Databricks notebook or spark-submit):
    %run ./ingest_borrowers
    -- or --
    spark-submit ingest_borrowers.py --source /mnt/landing/cdw_borr_mstr/
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    BORROWER_STATUS_MAP,
    expand_codes,
    parse_amount,
    parse_int,
    parse_legacy_date,
    parse_legacy_timestamp,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "/mnt/landing/cdw_borr_mstr/"
TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_PATH = "/mnt/quarantine/cdw_borr_mstr/"
BAD_RECORDS_PATH = "/mnt/quarantine/cdw_borr_mstr_bad/"


def read_source(spark: SparkSession, path: str) -> DataFrame:
    """Read legacy borrower extract. Supports CSV and Parquet auto-detection."""
    try:
        return spark.read.parquet(path)
    except Exception:
        return spark.read.option("header", "true").option("inferSchema", "false").csv(path)


def transform_borrowers(raw: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Apply all column mappings and type conversions.

    Returns:
        (good_df, quarantine_df) - records that parsed successfully and those
        that had critical parse failures.
    """
    transformed = raw.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_legacy_date("BORR_DOB_DT", "date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        parse_int("BORR_CRDT_SCR", "credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount("BORR_ANN_INCM", "annual_income"),
        parse_legacy_timestamp("BORR_CRET_DT", "created_at"),
        parse_legacy_timestamp("BORR_UPDT_DT", "updated_at"),
        expand_codes("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),
        F.col("BORR_REC_TYP").alias("_legacy_record_type"),
        # keep raw values for quarantine analysis
        F.col("BORR_DOB_DT").alias("_raw_dob"),
        F.col("BORR_ANN_INCM").alias("_raw_income"),
        F.col("BORR_CRDT_SCR").alias("_raw_credit_score"),
    )

    # Tag records with critical parse failures
    transformed = transformed.withColumn(
        "_has_error",
        (
            F.col("external_id").isNull()
            | F.col("first_name").isNull()
            | F.col("last_name").isNull()
        ),
    )

    good_df = transformed.filter(~F.col("_has_error")).drop(
        "_has_error", "_raw_dob", "_raw_income", "_raw_credit_score"
    )
    quarantine_df = transformed.filter(F.col("_has_error")).drop("_has_error")

    return good_df, quarantine_df


def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    """Write results to Delta Lake and quarantine bad records."""
    source_count = good_df.count() + quarantine_df.count()

    # Add ingestion timestamp
    good_df = good_df.withColumn("_ingestion_ts", F.current_timestamp())

    good_df.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    target_count = good_df.count()
    quarantine_count = quarantine_df.count()

    if quarantine_count > 0:
        quarantine_df.write.format("delta").mode("append").save(QUARANTINE_PATH)
        print(
            f"WARNING: {quarantine_count} borrower records quarantined to {QUARANTINE_PATH}"
        )

    return {
        "table": "borrowers",
        "source_count": source_count,
        "target_count": target_count,
        "quarantine_count": quarantine_count,
    }


def run(spark: SparkSession | None = None) -> dict:
    """Main entry point."""
    if spark is None:
        spark = SparkSession.builder.appName("IngestBorrowers").getOrCreate()

    print("--- Ingesting CDW_BORR_MSTR -> borrowers ---")
    raw = read_source(spark, SOURCE_PATH)
    print(f"Source record count: {raw.count()}")

    good_df, quarantine_df = transform_borrowers(raw)
    stats = write_target(good_df, quarantine_df)

    print(f"Target records written: {stats['target_count']}")
    print(f"Quarantined records:    {stats['quarantine_count']}")
    return stats


if __name__ == "__main__":
    run()
