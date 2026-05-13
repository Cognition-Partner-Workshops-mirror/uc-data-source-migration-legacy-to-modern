"""
Ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master table (simulated as CSV/Parquet source)
and transforms it into the modern borrowers Delta Lake table.

Transformations applied:
  - Parse BORR_DOB_DT (MM/DD/YYYY) -> date_of_birth (DATE)
  - Parse BORR_ANN_INCM (comma-formatted) -> annual_income (DECIMAL)
  - Parse BORR_CRDT_SCR (string) -> credit_score (INT)
  - Expand BORR_STAT_CD abbreviations (ACT -> Active, INA -> Inactive)
  - Parse BORR_CRET_DT, BORR_UPDT_DT -> created_at, updated_at (TIMESTAMP)
  - Drop BORR_REC_TYP (not needed in modern schema)
  - Add surrogate borrower_id via monotonically_increasing_id
  - Add ingestion metadata columns
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
import logging

from transformations import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_status_col,
    add_ingestion_metadata,
    log_bad_records,
    drop_flag_columns,
    BORROWER_STATUS_MAP,
)

logger = logging.getLogger("cdw_migration.ingest_borrowers")

# ---------------------------------------------------------------------------
# Source file path — configurable via Databricks widgets or job parameters
# In production, this would point to the extracted CSV/Parquet landing zone.
# ---------------------------------------------------------------------------
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw/CDW_BORR_MSTR"
DEFAULT_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.borrowers"


def read_source(spark: SparkSession, source_path: str = DEFAULT_SOURCE_PATH,
                source_format: str = DEFAULT_SOURCE_FORMAT) -> DataFrame:
    """
    Read the legacy CDW_BORR_MSTR data from the landing zone.
    Supports CSV (with header) and Parquet formats.
    """
    if source_format == "csv":
        # Legacy CSV files: all columns are strings, header row present
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")  # Keep everything as string initially
            .option("nullValue", "")
            .option("emptyValue", "")
            .csv(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from %s (%s)", df.count(), source_path, source_format)
    return df


def transform(df: DataFrame) -> DataFrame:
    """
    Apply all transformations to convert legacy CDW_BORR_MSTR columns
    to the modern borrowers schema.
    """
    # --- Generate surrogate key ---
    df = df.withColumn("borrower_id", F.monotonically_increasing_id() + 1)

    # --- Direct copy columns (rename from legacy cryptic to modern readable) ---
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

    # --- Type conversions ---
    # Parse date of birth: MM/DD/YYYY string -> DATE
    df = parse_date_col(df, "BORR_DOB_DT", "date_of_birth")

    # Parse credit score: string -> INT
    df = parse_int_col(df, "BORR_CRDT_SCR", "credit_score")

    # Parse annual income: comma-formatted string -> DECIMAL(12,2)
    df = parse_amount_col(df, "BORR_ANN_INCM", "annual_income", precision=12, scale=2)

    # Parse created/updated timestamps: MM/DD/YYYY -> TIMESTAMP
    df = parse_timestamp_col(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "BORR_UPDT_DT", "updated_at")

    # --- Status code expansion ---
    # ACT -> Active, INA -> Inactive
    df = expand_status_col(df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)

    # --- Add ingestion metadata ---
    df = add_ingestion_metadata(df, "CDW_BORR_MSTR")

    # --- Log and report any data quality issues ---
    log_bad_records(df, TARGET_TABLE)

    # --- Drop flag columns and legacy source columns ---
    df = drop_flag_columns(df)

    # Select only the target columns in the correct order
    target_columns = [
        "borrower_id", "external_id", "first_name", "last_name",
        "middle_initial", "ssn_hash", "date_of_birth", "address_line1",
        "address_line2", "city", "state", "zip_code", "phone", "email",
        "credit_score", "employment_status", "annual_income", "status",
        "created_at", "updated_at", "_ingestion_ts", "_source_system",
    ]
    df = df.select(*target_columns)

    return df


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    """
    Write the transformed borrowers DataFrame to the Delta Lake target table.
    Uses overwrite mode for initial load; merge/append for incremental loads.
    """
    (
        df.write
        .format("delta")
        .mode(mode)
        .partitionBy("status")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info("Wrote %d rows to %s", df.count(), TARGET_TABLE)


def run(spark: SparkSession, source_path: str = DEFAULT_SOURCE_PATH,
        source_format: str = DEFAULT_SOURCE_FORMAT) -> DataFrame:
    """
    Execute the full borrowers ingestion pipeline: read -> transform -> write.
    Returns the transformed DataFrame for downstream validation.
    """
    logger.info("Starting borrowers ingestion from %s", source_path)
    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform(raw_df)
    write_target(transformed_df)
    logger.info("Borrowers ingestion complete.")
    return transformed_df


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Borrowers_Ingestion").getOrCreate()
    # Configurable via Databricks widgets
    try:
        src_path = dbutils.widgets.get("source_path")  # noqa: F821
    except Exception:
        src_path = DEFAULT_SOURCE_PATH
    try:
        src_fmt = dbutils.widgets.get("source_format")  # noqa: F821
    except Exception:
        src_fmt = DEFAULT_SOURCE_FORMAT

    run(spark, src_path, src_fmt)
