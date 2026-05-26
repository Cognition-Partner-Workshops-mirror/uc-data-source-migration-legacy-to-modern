"""
PySpark ingestion script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads legacy borrower data from CSV/Parquet source files, applies all
transformations defined in data/mappings/column_mappings.md, and writes
to the Delta Lake borrowers table.

Transformations applied:
  - BORR_DOB_DT (MM/DD/YYYY string) → date_of_birth (DATE)
  - BORR_ANN_INCM (comma-formatted string) → annual_income (DECIMAL 12,2)
  - BORR_CRDT_SCR (string) → credit_score (INT)
  - BORR_STAT_CD (ACT/INA) → status (ACTIVE/INACTIVE)
  - BORR_CRET_DT, BORR_UPDT_DT → timestamps
  - BORR_REC_TYP dropped (not needed in modern schema)
  - Null/malformed values tagged, never silently dropped

Usage:
  Run as a Databricks notebook or submit via spark-submit.
  Configure source_path and target_table variables below.
"""

import logging
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    LongType,
)

# Import shared transformation utilities
from transform_utils import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_status_col,
    add_etl_metadata,
    tag_malformed_rows,
    BORROWER_STATUS_MAP,
)

# =============================================================================
# Configuration
# =============================================================================
# Source file path — adjust to your Databricks mount or DBFS path
SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_borr_mstr/"
# Supported formats: "csv" or "parquet"
SOURCE_FORMAT = "csv"
# Target Delta table
TARGET_TABLE = "loan_warehouse.borrowers"
# Write mode: "overwrite" for full refresh, "append" for incremental
WRITE_MODE = "overwrite"

# =============================================================================
# Logging setup
# =============================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_borrowers")

# =============================================================================
# Legacy source schema — all VARCHAR columns as StringType
# =============================================================================
LEGACY_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), True),
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


def read_source(spark):
    """Read the legacy CDW_BORR_MSTR data from the configured source path and format."""
    logger.info(f"Reading source data from {SOURCE_PATH} (format={SOURCE_FORMAT})")
    if SOURCE_FORMAT == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .schema(LEGACY_SCHEMA)
            .csv(SOURCE_PATH)
        )
    elif SOURCE_FORMAT == "parquet":
        df = spark.read.schema(LEGACY_SCHEMA).parquet(SOURCE_PATH)
    else:
        raise ValueError(f"Unsupported source format: {SOURCE_FORMAT}")

    record_count = df.count()
    logger.info(f"Read {record_count} records from legacy CDW_BORR_MSTR")
    return df


def transform(df):
    """
    Apply all column mappings and transformations to convert legacy borrower
    data to the modern borrowers schema.
    """
    logger.info("Applying transformations for CDW_BORR_MSTR → borrowers")

    # Tag rows with potential quality issues before transformation
    df_tagged = tag_malformed_rows(df, [
        (F.col("BORR_ID").isNull(), "NULL_BORR_ID"),
        (F.col("BORR_FST_NM").isNull(), "NULL_FIRST_NAME"),
        (F.col("BORR_LST_NM").isNull(), "NULL_LAST_NAME"),
        (F.col("BORR_DOB_DT").isNotNull() &
         ~F.col("BORR_DOB_DT").rlike(r"^\d{2}/\d{2}/\d{4}$"), "MALFORMED_DOB"),
        (F.col("BORR_CRDT_SCR").isNotNull() &
         ~F.col("BORR_CRDT_SCR").rlike(r"^\d+$"), "MALFORMED_CREDIT_SCORE"),
    ])

    # Log any flagged records
    flagged = df_tagged.filter(F.col("_quality_flags").isNotNull())
    flagged_count = flagged.count()
    if flagged_count > 0:
        logger.warning(
            f"Found {flagged_count} records with quality issues in CDW_BORR_MSTR. "
            "Records are preserved with quality flags — not dropped."
        )
        flagged.select("BORR_ID", "_quality_flags").show(truncate=False)

    # Apply column transformations per the mapping document
    transformed = df_tagged.select(
        # Surrogate key — generated via monotonically_increasing_id
        F.monotonically_increasing_id().alias("borrower_id"),

        # Natural key: direct copy
        F.trim(F.col("BORR_ID")).alias("external_id"),

        # Identity fields: direct copy with trim
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
        F.trim(F.col("BORR_SSN_ENCR")).alias("ssn_hash"),

        # Date of birth: parse MM/DD/YYYY → DATE
        parse_date_col("BORR_DOB_DT", "date_of_birth"),

        # Address fields: direct copy
        F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
        F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
        F.trim(F.col("BORR_CTY_NM")).alias("city"),
        F.trim(F.col("BORR_ST_CD")).alias("state"),
        F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),

        # Contact fields: direct copy
        F.trim(F.col("BORR_PH_NBR")).alias("phone"),
        F.trim(F.col("BORR_EMAIL_ADDR")).alias("email"),

        # Financial profile: type conversions
        parse_int_col("BORR_CRDT_SCR", "credit_score"),
        F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),
        parse_amount_col("BORR_ANN_INCM", "annual_income"),

        # Status: expand abbreviation
        expand_status_col("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),

        # Audit timestamps: parse MM/DD/YYYY → TIMESTAMP
        parse_timestamp_col("BORR_CRET_DT", "created_at"),
        parse_timestamp_col("BORR_UPDT_DT", "updated_at"),

        # Note: BORR_REC_TYP is intentionally dropped per mapping document
    )

    # Add ETL metadata columns
    transformed = add_etl_metadata(transformed, "CDW_BORR_MSTR")

    logger.info(f"Transformation complete. Output row count: {transformed.count()}")
    return transformed


def write_target(df):
    """Write the transformed borrowers DataFrame to the Delta Lake target table."""
    logger.info(f"Writing to {TARGET_TABLE} (mode={WRITE_MODE})")
    (
        df.write
        .format("delta")
        .mode(WRITE_MODE)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info(f"Successfully wrote data to {TARGET_TABLE}")


def main():
    """Main entry point: read → transform → write for borrowers ingestion."""
    spark = SparkSession.builder.appName("Ingest_CDW_BORR_MSTR").getOrCreate()
    logger.info("=" * 70)
    logger.info("Starting borrower ingestion: CDW_BORR_MSTR → loan_warehouse.borrowers")
    logger.info("=" * 70)

    try:
        # Step 1: Read legacy source data
        source_df = read_source(spark)

        # Step 2: Transform to modern schema
        target_df = transform(source_df)

        # Step 3: Write to Delta Lake
        write_target(target_df)

        logger.info("Borrower ingestion completed successfully")
    except Exception as e:
        logger.error(f"Borrower ingestion FAILED: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
