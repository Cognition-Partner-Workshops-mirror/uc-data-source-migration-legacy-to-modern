"""
Ingest CDW_BORR_MSTR (legacy) -> borrowers (Delta Lake).

Source: CSV or Parquet export of the CDW_BORR_MSTR table.
Target: loan_warehouse.borrowers Delta table.

Transformations applied:
  - Rename cryptic column names to modern names
  - Parse MM/DD/YYYY date strings to DateType / TimestampType
  - Parse comma-formatted amount strings to DecimalType
  - Parse credit score string to IntegerType
  - Expand borrower status codes (ACT -> ACTIVE, INA -> INACTIVE)
  - Drop BORR_REC_TYP (not needed in modern schema)
  - Generate surrogate id (monotonically_increasing_id)
  - Flag rows with quality issues instead of dropping them
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from databricks.ingestion.transformations import (
    BORROWER_STATUS_MAP,
    add_row_quality_flag,
    expand_status_col,
    log_null_counts,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
)
from databricks.schemas.borrowers import (
    BORROWERS_PARTITION_COLS,
    BORROWERS_PATH,
)

logger = logging.getLogger("loan_migration.ingest_borrowers")

REQUIRED_COLS = ["external_id", "first_name", "last_name", "status"]

SOURCE_FILE_DEFAULT = "/mnt/legacy/CDW_BORR_MSTR"


def read_source(spark: SparkSession, path: str = SOURCE_FILE_DEFAULT, fmt: str = "csv") -> DataFrame:
    """Read the legacy borrower master source file."""
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def transform(source_df: DataFrame) -> DataFrame:
    """Apply all column-level transformations to produce the modern borrowers table."""
    transformed = source_df.select(
        F.monotonically_increasing_id().alias("id"),
        F.col("BORR_ID").alias("external_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_date_col("BORR_DOB_DT", "date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        parse_int_col("BORR_CRDT_SCR", "credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount_col("BORR_ANN_INCM", "annual_income"),
        expand_status_col("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),
        parse_timestamp_col("BORR_CRET_DT", "created_at"),
        parse_timestamp_col("BORR_UPDT_DT", "updated_at"),
        # BORR_REC_TYP intentionally dropped
    )
    return add_row_quality_flag(transformed, REQUIRED_COLS)


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    """Write the transformed borrowers DataFrame to Delta Lake."""
    clean_df = df.drop("_has_quality_issue")
    writer = clean_df.write.format("delta").mode(mode)
    if BORROWERS_PARTITION_COLS:
        writer = writer.partitionBy(*BORROWERS_PARTITION_COLS)
    writer.save(BORROWERS_PATH)
    logger.info("Wrote borrowers to %s", BORROWERS_PATH)


def run(spark: SparkSession, source_path: str = SOURCE_FILE_DEFAULT, fmt: str = "csv") -> dict:
    """
    End-to-end ingestion: read -> transform -> validate -> write.
    Returns a summary dict with row counts and quality info.
    """
    logger.info("Starting borrower ingestion from %s", source_path)

    source_df = read_source(spark, source_path, fmt)
    source_count = source_df.count()
    logger.info("Source row count: %d", source_count)

    transformed_df = transform(source_df)
    target_count = transformed_df.count()

    null_issues = log_null_counts(transformed_df, "borrowers", REQUIRED_COLS)
    quality_issues = transformed_df.filter(F.col("_has_quality_issue")).count()

    write_target(transformed_df)

    summary = {
        "table": "borrowers",
        "source_count": source_count,
        "target_count": target_count,
        "records_with_quality_issues": quality_issues,
        "null_counts": null_issues,
    }
    logger.info("Borrower ingestion complete: %s", summary)
    return summary
