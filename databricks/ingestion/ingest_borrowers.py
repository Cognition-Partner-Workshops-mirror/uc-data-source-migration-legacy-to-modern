"""
Ingest legacy CDW_BORR_MSTR → modern borrowers Delta Lake table.

Source : CSV/Parquet export of CDW_BORR_MSTR
Target : loan_warehouse.borrowers (Delta Lake)

Transformations:
  - Parse date strings (MM/DD/YYYY) → DateType / TimestampType
  - Parse amount strings (with commas) → DecimalType
  - Parse credit score string → IntegerType
  - Expand status codes (ACT → Active, INA → Inactive)
  - Drop legacy BORR_REC_TYP (not needed in modern schema)
  - Log and quarantine malformed records
"""

import logging
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType,
)

from transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_int,
    expand_status_code,
    BORROWER_STATUS_MAP,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_borrowers")

# ---------------------------------------------------------------------------
# Schema for reading the legacy CSV export
# ---------------------------------------------------------------------------

LEGACY_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), False),
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
    StructField("BORR_CRET_DT", StringType(), True),
    StructField("BORR_UPDT_DT", StringType(), True),
    StructField("BORR_STAT_CD", StringType(), True),
    StructField("BORR_REC_TYP", StringType(), True),
])


# ---------------------------------------------------------------------------
# Configuration — override via Databricks widgets or job parameters
# ---------------------------------------------------------------------------

SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_borr_mstr/"
SOURCE_FORMAT = "csv"  # or "parquet"
TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_PATH = "dbfs:/mnt/quarantine/borrowers/"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH, fmt: str = SOURCE_FORMAT) -> DataFrame:
    """Read the legacy borrower source file."""
    reader = spark.read.schema(LEGACY_SCHEMA)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.format(fmt).load(path)


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Apply all column mappings and type conversions.

    Returns:
        (good_df, quarantine_df) — records that passed / failed validation.
    """
    transformed = df.select(
        F.col("BORR_ID").alias("external_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
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
        parse_legacy_amount("BORR_ANN_INCM", 12, 2).alias("annual_income"),
        expand_status_code("BORR_STAT_CD", BORROWER_STATUS_MAP, "Unknown").alias("status"),
        parse_legacy_timestamp("BORR_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("BORR_UPDT_DT").alias("updated_at"),
        F.current_timestamp().alias("_migration_ts"),
        F.lit("CDW_BORR_MSTR").alias("_source_system"),
    )

    # Required-field validation: external_id, first_name, last_name must be non-null
    valid_condition = (
        F.col("external_id").isNotNull()
        & F.col("first_name").isNotNull()
        & F.col("last_name").isNotNull()
    )

    good_df = transformed.filter(valid_condition)
    quarantine_df = transformed.filter(~valid_condition)

    return good_df, quarantine_df


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    """Write good records to Delta and quarantine rejects."""
    good_count = good_df.count()
    quarantine_count = quarantine_df.count()

    logger.info("Borrowers — good records: %d, quarantined: %d", good_count, quarantine_count)

    if quarantine_count > 0:
        logger.warning("Writing %d quarantined borrower records to %s", quarantine_count, QUARANTINE_PATH)
        quarantine_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)

    good_df.write.mode("overwrite").format("delta").saveAsTable(TARGET_TABLE)

    logger.info("Borrower ingestion complete → %s", TARGET_TABLE)
    return {"good": good_count, "quarantined": quarantine_count}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession) -> dict:
    """Execute the full borrower ingestion pipeline."""
    logger.info("Starting borrower ingestion from %s", SOURCE_PATH)
    raw_df = read_source(spark)
    source_count = raw_df.count()
    logger.info("Source record count: %d", source_count)

    good_df, quarantine_df = transform(raw_df)
    result = write_target(good_df, quarantine_df)
    result["source_count"] = source_count
    return result


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest_CDW_BORR_MSTR").getOrCreate()
    run(spark)
