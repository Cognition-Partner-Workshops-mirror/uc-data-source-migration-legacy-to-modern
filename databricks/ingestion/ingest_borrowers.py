"""
Ingest CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master table exported as CSV/Parquet, applies
type conversions and status expansion, and writes to the modern Delta
Lake borrowers table.

Usage (Databricks notebook or job):
    %run ./transform_utils
    %run ./ingest_borrowers
    -- or --
    from ingestion.ingest_borrowers import run
    report_df = run(spark, source_path="...", source_format="csv")
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from transform_utils import (
    BORROWER_STATUS_MAP,
    collect_bad_value_report,
    drop_flag_columns,
    expand_status_col,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
)

TARGET_TABLE = "loan_warehouse.borrowers"
SOURCE_TABLE = "CDW_BORR_MSTR"


def read_source(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
) -> DataFrame:
    """Read the legacy CDW_BORR_MSTR extract.

    All columns are read as STRING to mirror the all-VARCHAR legacy schema.
    """
    reader = spark.read.format(source_format)
    if source_format == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(source_path)


def transform(df: DataFrame) -> DataFrame:
    """Apply all legacy-to-modern transformations for borrowers."""

    # --- direct renames ---
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

    # --- type conversions ---
    df = parse_date_col(df, "BORR_DOB_DT", "date_of_birth")
    df = parse_int_col(df, "BORR_CRDT_SCR", "credit_score")
    df = parse_amount_col(df, "BORR_ANN_INCM", "annual_income")
    df = parse_timestamp_col(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "BORR_UPDT_DT", "updated_at")

    # --- status expansion ---
    df = expand_status_col(df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)

    # --- drop legacy columns that have been transformed ---
    df = df.drop(
        "BORR_DOB_DT", "BORR_CRDT_SCR", "BORR_ANN_INCM",
        "BORR_CRET_DT", "BORR_UPDT_DT", "BORR_STAT_CD",
        "BORR_REC_TYP",  # dropped per mapping spec
    )

    # --- add lineage metadata ---
    df = df.withColumn("_migration_source", F.lit(SOURCE_TABLE))
    df = df.withColumn("_migrated_at", F.current_timestamp())

    return df


def run(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
    write_mode: str = "overwrite",
) -> DataFrame:
    """End-to-end ingest: read -> transform -> report bad values -> write.

    Returns a DataFrame of bad-value records for downstream quality reporting.
    """
    raw_df = read_source(spark, source_path, source_format)
    source_count = raw_df.count()
    print(f"[{SOURCE_TABLE}] Source row count: {source_count}")

    transformed_df = transform(raw_df)

    # Collect parse-error report before stripping flag columns
    bad_report = collect_bad_value_report(transformed_df, SOURCE_TABLE)
    bad_count = bad_report.count()
    if bad_count > 0:
        print(f"[{SOURCE_TABLE}] WARNING: {bad_count} parse issues detected")
        bad_report.show(truncate=False)

    clean_df = drop_flag_columns(transformed_df)

    # Select final column set in target order
    final_df = clean_df.select(
        "external_id", "first_name", "last_name", "middle_initial",
        "ssn_hash", "date_of_birth", "address_line1", "address_line2",
        "city", "state", "zip_code", "phone", "email", "credit_score",
        "employment_status", "annual_income", "status",
        "created_at", "updated_at",
        "_migration_source", "_migrated_at",
    )

    final_df.write.format("delta").mode(write_mode).saveAsTable(TARGET_TABLE)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[{SOURCE_TABLE}] Target row count: {target_count}")

    if source_count != target_count:
        print(
            f"[{SOURCE_TABLE}] ERROR: Row count mismatch! "
            f"source={source_count}, target={target_count}"
        )

    return bad_report
