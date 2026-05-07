"""
Ingestion script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads legacy borrower data from CSV/Parquet source, transforms all
VARCHAR columns to proper types, expands status codes, and writes
to the Delta Lake borrowers table.

Usage (Databricks notebook):
    %run ./common
    %run ./ingest_borrowers
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

from common import (
    BORROWER_STATUS_MAP,
    expand_status,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_int,
    parse_legacy_timestamp,
    tag_ingestion_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "dbfs:/mnt/legacy-extracts/cdw_borr_mstr/"
TARGET_TABLE = "loan_warehouse.borrowers"
SOURCE_FORMAT = "csv"  # Change to "parquet" if source is Parquet

# Legacy schema — all columns are VARCHAR in CDW
LEGACY_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_REC_TYP", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_MID_INIT", StringType(), True),
    StructField("BORR_SSN_ENCR", StringType(), True),
    StructField("BORR_DOB_DT", StringType(), True),
    StructField("BORR_ADDR_LN1", StringType(), True),
    StructField("BORR_ADDR_LN2", StringType(), True),
    StructField("BORR_CTY_NM", StringType(), True),
    StructField("BORR_ST_CD", StringType(), True),
    StructField("BORR_ZIP_CD", StringType(), True),
    StructField("BORR_PH_NBR", StringType(), True),
    StructField("BORR_EMAIL_ADDR", StringType(), True),
    StructField("BORR_CRDT_SCR", StringType(), True),
    StructField("BORR_EMP_STAT", StringType(), True),
    StructField("BORR_ANN_INCM", StringType(), True),
    StructField("BORR_STAT_CD", StringType(), True),
    StructField("BORR_CRET_DT", StringType(), True),
    StructField("BORR_UPDT_DT", StringType(), True),
])


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def extract(spark: SparkSession) -> DataFrame:
    """Read legacy borrower data from source files."""
    reader = spark.read.format(SOURCE_FORMAT).schema(LEGACY_SCHEMA)
    if SOURCE_FORMAT == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(SOURCE_PATH)
    row_count = df.count()
    print(f"[ingest_borrowers] Extracted {row_count} rows from {SOURCE_PATH}")
    return df


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame) -> DataFrame:
    """Apply all type conversions, status expansions, and null handling."""
    transformed = df.select(
        F.trim(F.col("BORR_ID")).alias("external_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
        F.trim(F.col("BORR_SSN_ENCR")).alias("ssn_hash"),
        parse_legacy_date("BORR_DOB_DT").alias("date_of_birth"),
        F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
        F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
        F.trim(F.col("BORR_CTY_NM")).alias("city"),
        F.upper(F.trim(F.col("BORR_ST_CD"))).alias("state"),
        F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),
        F.trim(F.col("BORR_PH_NBR")).alias("phone"),
        F.lower(F.trim(F.col("BORR_EMAIL_ADDR"))).alias("email"),
        parse_legacy_int("BORR_CRDT_SCR").alias("credit_score"),
        F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),
        parse_legacy_amount("BORR_ANN_INCM").alias("annual_income"),
        expand_status("BORR_STAT_CD", BORROWER_STATUS_MAP).alias("status"),
        parse_legacy_timestamp("BORR_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("BORR_UPDT_DT").alias("updated_at"),
    )

    # Tag ingestion metadata
    transformed = tag_ingestion_metadata(transformed, "CDW_BORR_MSTR")

    # Quarantine: log rows with null required fields (don't drop them)
    quarantined = transformed.withColumn(
        "_quarantine_reason",
        F.when(F.col("external_id").isNull(), "missing BORR_ID")
        .when(F.col("first_name").isNull(), "missing BORR_FST_NM")
        .when(F.col("last_name").isNull(), "missing BORR_LST_NM")
        .otherwise(None),
    ).withColumn(
        "_quarantine",
        F.col("_quarantine_reason").isNotNull(),
    )

    quarantine_count = quarantined.filter(F.col("_quarantine")).count()
    if quarantine_count > 0:
        print(f"[ingest_borrowers] WARNING: {quarantine_count} rows flagged for quarantine")
        quarantined.filter(F.col("_quarantine")).select(
            "external_id", "_quarantine_reason"
        ).show(truncate=False)

    # Return only clean rows for the main table
    clean = quarantined.filter(~F.col("_quarantine")).drop("_quarantine", "_quarantine_reason")

    print(f"[ingest_borrowers] Transformed {clean.count()} clean rows")
    return clean


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load(df: DataFrame):
    """Write transformed data to Delta Lake borrowers table."""
    df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).partitionBy("status").saveAsTable(TARGET_TABLE)
    print(f"[ingest_borrowers] Loaded data into {TARGET_TABLE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession):
    """Execute the full ETL pipeline for borrowers."""
    raw = extract(spark)
    clean = transform(raw)
    load(clean)
    print("[ingest_borrowers] Pipeline complete")


if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestBorrowers").getOrCreate()
    run(spark)
