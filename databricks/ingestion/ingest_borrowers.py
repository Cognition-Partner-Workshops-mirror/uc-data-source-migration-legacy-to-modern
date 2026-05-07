"""
Ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master table (simulated as CSV/Parquet),
applies type conversions and status expansion, then writes to Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from databricks.ingestion.transforms import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_status,
    quarantine_nulls,
    log_row_counts,
    BORROWER_STATUS_MAP,
    logger,
)

TARGET_TABLE = "loan_warehouse.borrowers"
SOURCE_TABLE = "CDW_BORR_MSTR"
REQUIRED_COLS = ["external_id", "first_name", "last_name"]


def read_source(spark: SparkSession, source_path: str, source_format: str = "csv") -> DataFrame:
    """Read legacy borrower data from CSV or Parquet source files.

    Args:
        spark: Active SparkSession.
        source_path: Path to the source file(s) (CSV or Parquet).
        source_format: 'csv' or 'parquet'. Defaults to 'csv'.

    Returns:
        Raw source DataFrame.
    """
    if source_format == "csv":
        df = (
            spark.read.format("csv")
            .option("header", "true")
            .option("inferSchema", "false")
            .load(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from %s (%s)", df.count(), source_path, source_format)
    return df


def transform(df: DataFrame) -> DataFrame:
    """Transform legacy borrower data to modern schema.

    Transformations:
        - Rename cryptic columns to meaningful names
        - Parse DOB and created/updated dates from MM/DD/YYYY strings
        - Parse credit score string to integer
        - Parse annual income string (with commas) to decimal
        - Expand status code abbreviations (ACT -> ACTIVE, INA -> INACTIVE)
        - Drop BORR_REC_TYP (not needed in modern schema)
    """
    # Rename columns
    df = (
        df.withColumnRenamed("BORR_ID", "external_id")
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

    # Parse dates
    df = parse_date_col(df, "BORR_DOB_DT", "date_of_birth")
    df = parse_timestamp_col(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "BORR_UPDT_DT", "updated_at")

    # Parse numerics
    df = parse_int_col(df, "BORR_CRDT_SCR", "credit_score")
    df = parse_amount_col(df, "BORR_ANN_INCM", "annual_income")

    # Expand status codes
    df = expand_status(df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP, default="ACTIVE")

    # Add migration metadata
    df = df.withColumn("_migration_source", F.lit(SOURCE_TABLE))
    df = df.withColumn("_migrated_at", F.current_timestamp())

    # Select final columns in target order
    df = df.select(
        "external_id", "first_name", "last_name", "middle_initial",
        "ssn_hash", "date_of_birth", "address_line1", "address_line2",
        "city", "state", "zip_code", "phone", "email",
        "credit_score", "employment_status", "annual_income",
        "status", "created_at", "updated_at",
        "_migration_source", "_migrated_at",
    )

    return df


def load(df: DataFrame, mode: str = "overwrite"):
    """Write the transformed borrower DataFrame to the Delta Lake target table.

    Args:
        df: Transformed DataFrame.
        mode: Spark write mode ('overwrite' for initial load, 'append' for incremental).
    """
    df.write.format("delta").mode(mode).partitionBy("status").saveAsTable(TARGET_TABLE)
    logger.info("Wrote %d rows to %s", df.count(), TARGET_TABLE)


def run(spark: SparkSession, source_path: str, source_format: str = "csv",
        write_mode: str = "overwrite"):
    """Execute the full borrower ingestion pipeline.

    Args:
        spark: Active SparkSession.
        source_path: Path to legacy borrower source file(s).
        source_format: 'csv' or 'parquet'.
        write_mode: 'overwrite' or 'append'.

    Returns:
        Tuple of (valid_df, quarantine_df) for downstream quality checks.
    """
    logger.info("=== Starting borrower ingestion from %s ===", source_path)

    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform(raw_df)

    valid_df, quarantine_df = quarantine_nulls(transformed_df, REQUIRED_COLS, TARGET_TABLE)
    src_count, tgt_count = log_row_counts(raw_df, valid_df, TARGET_TABLE)

    load(valid_df, mode=write_mode)

    logger.info("=== Borrower ingestion complete: %d/%d rows loaded ===", tgt_count, src_count)
    return valid_df, quarantine_df
