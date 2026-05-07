"""Ingest legacy CDW_BORR_MSTR into Delta Lake ``loan_warehouse.borrowers``.

Reads from a CSV/Parquet source file that mirrors the legacy CDW_BORR_MSTR
table structure. Applies type conversions, status-code expansion, and null
auditing before writing to the target Delta table.

Usage (Databricks notebook or job):
    %run ./utils
    %run ./ingest_borrowers
    -- or --
    from databricks.ingestion.ingest_borrowers import run
    run(spark, source_path="...", target_table="loan_warehouse.borrowers")
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from databricks.ingestion.utils import (
    BORROWER_STATUS_MAP,
    add_ingestion_metadata,
    expand_status,
    log_null_counts,
    parse_amount,
    parse_date,
    parse_int,
    parse_timestamp,
)

# Columns expected in the source file (mirrors CDW_BORR_MSTR)
EXPECTED_COLUMNS = [
    "BORR_ID", "BORR_FST_NM", "BORR_LST_NM", "BORR_MID_INIT",
    "BORR_SSN_ENCR", "BORR_DOB_DT", "BORR_ADDR_LN1", "BORR_ADDR_LN2",
    "BORR_CTY_NM", "BORR_ST_CD", "BORR_ZIP_CD", "BORR_PH_NBR",
    "BORR_EMAIL_ADDR", "BORR_CRDT_SCR", "BORR_EMP_STAT", "BORR_ANN_INCM",
    "BORR_CRET_DT", "BORR_UPDT_DT", "BORR_STAT_CD", "BORR_REC_TYP",
]

REQUIRED_FIELDS = ["BORR_ID", "BORR_FST_NM", "BORR_LST_NM"]


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv") -> DataFrame:
    """Read the legacy borrower extract.

    Supports ``csv`` (default) and ``parquet`` formats.
    """
    if file_format == "parquet":
        return spark.read.parquet(source_path)
    return spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)


def validate_schema(df: DataFrame) -> DataFrame:
    """Ensure all expected columns are present. Raise on missing columns."""
    missing = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Source is missing expected columns: {sorted(missing)}")
    return df


def quarantine_bad_rows(df: DataFrame) -> tuple:
    """Split into good and quarantined DataFrames based on required-field nulls.

    Returns (good_df, quarantine_df).
    """
    condition = F.lit(True)
    for col_name in REQUIRED_FIELDS:
        condition = condition & F.col(col_name).isNotNull() & (F.trim(F.col(col_name)) != "")
    good_df = df.filter(condition)
    quarantine_df = df.filter(~condition)

    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        print(f"[WARN] Quarantined {quarantine_count} borrower rows with missing required fields.")

    return good_df, quarantine_df


def transform(df: DataFrame) -> DataFrame:
    """Apply all column transformations for the borrowers table."""
    # Date conversions
    df = parse_date(df, "BORR_DOB_DT", "date_of_birth")
    df = parse_timestamp(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp(df, "BORR_UPDT_DT", "updated_at")

    # Numeric conversions
    df = parse_int(df, "BORR_CRDT_SCR", "credit_score")
    df = parse_amount(df, "BORR_ANN_INCM", "annual_income", precision=12, scale=2)

    # Status expansion
    df = expand_status(df, "BORR_STAT_CD", BORROWER_STATUS_MAP, "status")

    # Rename direct-copy columns
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

    # Add audit columns
    df = add_ingestion_metadata(df, "CDW_BORR_MSTR")

    # Select final column set (drop BORR_REC_TYP and raw audit cols for target)
    final_columns = [
        "external_id", "first_name", "last_name", "middle_initial",
        "ssn_hash", "date_of_birth", "address_line1", "address_line2",
        "city", "state", "zip_code", "phone", "email", "credit_score",
        "employment_status", "annual_income", "status",
        "created_at", "updated_at",
        "_ingestion_ts", "_source_system",
    ]
    return df.select(*final_columns)


def write_target(df: DataFrame, target_table: str, mode: str = "overwrite") -> None:
    """Write the transformed DataFrame to the Delta target table."""
    df.write.format("delta").mode(mode).partitionBy("state").saveAsTable(target_table)
    row_count = df.count()
    print(f"[INFO] Wrote {row_count} rows to {target_table}.")


def run(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.borrowers",
    file_format: str = "csv",
    quarantine_path: str | None = None,
) -> dict:
    """End-to-end ingestion entry point.

    Returns a summary dict with row counts for downstream orchestration.
    """
    print(f"[INFO] Starting borrower ingestion from {source_path}")

    raw_df = read_source(spark, source_path, file_format)
    raw_df = validate_schema(raw_df)
    raw_count = raw_df.count()
    print(f"[INFO] Source row count: {raw_count}")

    good_df, quarantine_df = quarantine_bad_rows(raw_df)

    # Null audit on good rows before transformation
    log_null_counts(good_df, "CDW_BORR_MSTR (pre-transform)", EXPECTED_COLUMNS)

    transformed_df = transform(good_df)
    write_target(transformed_df, target_table)

    # Persist quarantined rows for review
    quarantine_count = quarantine_df.count()
    if quarantine_count > 0 and quarantine_path:
        quarantine_df.write.format("delta").mode("overwrite").save(quarantine_path)
        print(f"[WARN] {quarantine_count} quarantined rows written to {quarantine_path}")

    return {
        "source_count": raw_count,
        "loaded_count": raw_count - quarantine_count,
        "quarantined_count": quarantine_count,
        "target_table": target_table,
    }
