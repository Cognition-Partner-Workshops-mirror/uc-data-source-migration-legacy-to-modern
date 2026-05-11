"""
ingest_borrowers.py — PySpark ingestion script for CDW_BORR_MSTR → borrowers.

Reads the legacy borrower data from a CSV/Parquet source file (simulating the
CDW extract), applies all transformations defined in column_mappings.md, and
writes the result to the Delta Lake `loan_warehouse.borrowers` table.

Transformation summary:
  - Date strings (MM/DD/YYYY) → DateType / TimestampType
  - Amount strings with commas → DecimalType
  - Credit score string → IntegerType
  - Status code expansion (ACT → ACTIVE, INA → INACTIVE)
  - BORR_REC_TYP column dropped (not needed in modern schema)
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
import logging

from common_transforms import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_code_col,
    log_null_counts,
    add_ingestion_metadata,
    BORROWER_STATUS_MAP,
)

logger = logging.getLogger("cdw_migration.borrowers")

# ---------------------------------------------------------------------------
# Configuration — override via Databricks widgets or job parameters
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/legacy-extract/CDW_BORR_MSTR"  # CSV or Parquet
SOURCE_FORMAT = "csv"  # Change to "parquet" if the extract is Parquet
TARGET_TABLE = "loan_warehouse.borrowers"


def read_source(spark: SparkSession) -> "DataFrame":
    """Read the legacy CDW_BORR_MSTR extract.

    Supports both CSV (with header) and Parquet formats. CSV is the default
    because the legacy system exports comma-delimited files.
    """
    if SOURCE_FORMAT == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")  # keep everything as string initially
            .option("nullValue", "NULL")
            .option("emptyValue", "")
            .csv(SOURCE_PATH)
        )
    else:
        df = spark.read.parquet(SOURCE_PATH)

    logger.info("Read %d rows from %s (%s)", df.count(), SOURCE_PATH, SOURCE_FORMAT)
    return df


def transform(df: "DataFrame") -> "DataFrame":
    """Apply all column mappings and type conversions for borrowers."""

    # --- Date columns: MM/DD/YYYY → DATE or TIMESTAMP ---
    df = parse_date_col(df, "BORR_DOB_DT", "date_of_birth")
    df = parse_timestamp_col(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "BORR_UPDT_DT", "updated_at")

    # --- Numeric columns ---
    df = parse_int_col(df, "BORR_CRDT_SCR", "credit_score")
    df = parse_amount_col(df, "BORR_ANN_INCM", "annual_income", precision=12, scale=2)

    # --- Status code expansion ---
    df = expand_code_col(df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)

    # --- Direct-copy renames (no type change needed) ---
    df = (
        df
        .withColumnRenamed("BORR_ID", "external_id")
        .withColumnRenamed("BORR_FST_NM", "first_name")
        .withColumnRenamed("BORR_LST_NM", "last_name")
        .withColumnRenamed("BORR_MID_INIT", "middle_initial")
        .withColumnRenamed("BORR_SSN_ENCR", "ssn_hash")
        .withColumnRenamed("BORR_ADDR_LN1", "address_line1")
        .withColumnRenamed("BORR_ADDR_LN2", "address_line2")
        .withColumnRenamed("BORR_CTY_NM", "city")
        .withColumnRenamed("BORR_ST_CD", "state")
        .withColumnRenamed("BORR_ZIP_CD", "zip_code")
        .withColumnRenamed("BORR_PH_NBR", "phone")
        .withColumnRenamed("BORR_EMAIL_ADDR", "email")
        .withColumnRenamed("BORR_EMP_STAT", "employment_status")
    )

    # --- Drop columns not needed in modern schema ---
    df = df.drop("BORR_REC_TYP", "BORR_DOB_DT", "BORR_CRET_DT", "BORR_UPDT_DT",
                 "BORR_CRDT_SCR", "BORR_ANN_INCM", "BORR_STAT_CD")

    # --- Add ingestion metadata ---
    df = add_ingestion_metadata(df, "CDW_BORR_MSTR")

    # --- Select final column order ---
    df = df.select(
        "external_id", "first_name", "last_name", "middle_initial",
        "ssn_hash", "date_of_birth",
        "address_line1", "address_line2", "city", "state", "zip_code",
        "phone", "email",
        "credit_score", "employment_status", "annual_income",
        "status",
        "created_at", "updated_at",
        "_ingestion_ts", "_source_system",
    )

    return df


def validate_pre_write(df: "DataFrame") -> None:
    """Pre-write validation — log NULL counts for critical fields.

    Does NOT drop records. Quality checks are handled separately by the
    data quality framework after ingestion.
    """
    critical_cols = [
        "external_id", "first_name", "last_name", "date_of_birth",
        "credit_score", "annual_income", "status",
    ]
    log_null_counts(df, critical_cols, TARGET_TABLE)


def write_target(df: "DataFrame") -> None:
    """Write the transformed borrower data to Delta Lake.

    Uses MERGE (upsert) semantics keyed on external_id so the pipeline is
    idempotent — re-running the same extract does not create duplicates.
    """
    from delta.tables import DeltaTable

    # Check if the target table already exists
    spark = df.sparkSession
    if DeltaTable.isDeltaTable(spark, TARGET_TABLE):
        target = DeltaTable.forName(spark, TARGET_TABLE)
        (
            target.alias("tgt")
            .merge(
                df.alias("src"),
                "tgt.external_id = src.external_id"
            )
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )
        logger.info("MERGE completed into %s", TARGET_TABLE)
    else:
        # First run — create the table from the DataFrame
        (
            df.write
            .format("delta")
            .mode("overwrite")
            .saveAsTable(TARGET_TABLE)
        )
        logger.info("Initial load completed into %s", TARGET_TABLE)


def main():
    """Entry point — orchestrates read → transform → validate → write."""
    spark = SparkSession.builder.appName("CDW Migration — Borrowers").getOrCreate()
    logger.info("Starting borrower ingestion from %s", SOURCE_PATH)

    # Step 1: Read legacy extract
    raw_df = read_source(spark)

    # Step 2: Transform
    transformed_df = transform(raw_df)

    # Step 3: Pre-write validation (log issues, do NOT drop records)
    validate_pre_write(transformed_df)

    # Step 4: Write to Delta Lake
    write_target(transformed_df)

    logger.info("Borrower ingestion complete. Rows written: %d", transformed_df.count())


if __name__ == "__main__":
    main()
