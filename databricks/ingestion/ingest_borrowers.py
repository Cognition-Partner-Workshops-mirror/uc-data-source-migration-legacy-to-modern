"""
Ingest legacy CDW_BORR_MSTR into Delta Lake borrowers table.

Source : CSV/Parquet export of CDW_BORR_MSTR
Target : loan_warehouse.borrowers (Delta Lake)

Transformations:
  - BORR_DOB_DT           : MM/DD/YYYY -> DATE
  - BORR_CRDT_SCR         : VARCHAR    -> INT
  - BORR_ANN_INCM         : "92,500"   -> DECIMAL(12,2)
  - BORR_STAT_CD          : ACT/INA    -> ACTIVE/INACTIVE
  - BORR_CRET_DT/UPDT_DT : MM/DD/YYYY -> TIMESTAMP
  - BORR_REC_TYP          : dropped (not needed in modern schema)

Usage (Databricks notebook):
  %run ./ingest_borrowers
  -- or --
  from ingestion.ingest_borrowers import run
  run(spark, source_path="dbfs:/mnt/landing/cdw_borr_mstr/", ...)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from .transforms import (
    parse_date,
    parse_timestamp,
    parse_amount,
    parse_int,
    expand_status,
    add_ingestion_timestamp,
    log_malformed_rows,
    BORROWER_STATUS_MAP,
)

# Required columns that must not be null after transformation
REQUIRED_COLS = ["external_id", "first_name", "last_name"]


def read_source(spark: SparkSession, source_path: str, source_format: str = "csv") -> DataFrame:
    """Read the legacy CDW_BORR_MSTR extract."""
    reader = spark.read.format(source_format)
    if source_format == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(source_path)


def transform(df: DataFrame) -> DataFrame:
    """Apply all column mappings and type conversions."""
    return (
        df
        .select(
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
            expand_status("BORR_STAT_CD", BORROWER_STATUS_MAP, "ACTIVE").alias("status"),
            parse_timestamp("BORR_CRET_DT").alias("created_at"),
            parse_timestamp("BORR_UPDT_DT").alias("updated_at"),
        )
    )


def run(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.borrowers",
    error_path: str = "dbfs:/mnt/quarantine/borrowers/",
    source_format: str = "csv",
    write_mode: str = "append",
) -> dict:
    """
    End-to-end ingestion pipeline for borrowers.

    Returns a summary dict with row counts for monitoring.
    """
    # 1. Read
    raw_df = read_source(spark, source_path, source_format)
    source_count = raw_df.count()
    print(f"[borrowers] Source rows read: {source_count}")

    # 2. Transform
    transformed_df = transform(raw_df)
    transformed_df = add_ingestion_timestamp(transformed_df)

    # 3. Quarantine malformed rows
    valid_df, quarantine_count = log_malformed_rows(
        transformed_df, REQUIRED_COLS, "CDW_BORR_MSTR", error_path
    )
    print(f"[borrowers] Quarantined rows: {quarantine_count}")

    # 4. Write to Delta
    valid_count = valid_df.count()
    (
        valid_df
        .write
        .format("delta")
        .mode(write_mode)
        .option("mergeSchema", "true")
        .saveAsTable(target_table)
    )
    print(f"[borrowers] Rows written to {target_table}: {valid_count}")

    return {
        "table": target_table,
        "source_count": source_count,
        "valid_count": valid_count,
        "quarantine_count": quarantine_count,
    }
