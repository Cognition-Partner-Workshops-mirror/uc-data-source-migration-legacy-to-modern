"""
PySpark ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master from a CSV/Parquet source, applies all
column mappings and type conversions per column_mappings.md, and writes
to the modern Delta Lake borrowers table.

Usage (Databricks notebook or spark-submit):
    %run ./transforms
    %run ./ingest_borrowers
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

# When running as a standalone script (spark-submit), import from local module.
# In Databricks notebooks, use %run ./transforms instead.
try:
    from transforms import (
        parse_legacy_date,
        parse_legacy_timestamp,
        parse_legacy_amount,
        parse_legacy_integer,
        expand_status_code,
        flag_nulls,
        flag_parse_failures,
        BORROWER_STATUS_MAP,
    )
except ImportError:
    pass  # Assume Databricks %run has already executed transforms


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LEGACY_SOURCE_PATH = "/mnt/legacy-cdw/CDW_BORR_MSTR"
TARGET_TABLE = "loan_warehouse.borrowers"
SOURCE_FORMAT = "csv"  # Change to "parquet" if legacy export is Parquet

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "quote": '"',
    "escape": '"',
}


def read_legacy_borrowers(spark: SparkSession) -> DataFrame:
    """Read the legacy CDW_BORR_MSTR source file."""
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for k, v in CSV_OPTIONS.items():
            reader = reader.option(k, v)
    return reader.load(LEGACY_SOURCE_PATH)


def transform_borrowers(raw: DataFrame) -> DataFrame:
    """
    Apply all column mappings from CDW_BORR_MSTR -> borrowers:
    - Rename cryptic columns to meaningful names
    - Parse dates, amounts, integers from VARCHAR
    - Expand status codes
    - Drop BORR_REC_TYP (not needed in modern schema)
    - Flag nulls in required fields
    """
    transformed = (
        raw
        .withColumn("external_id", F.trim(F.col("BORR_ID")))
        .withColumn("first_name", F.trim(F.col("BORR_FST_NM")))
        .withColumn("last_name", F.trim(F.col("BORR_LST_NM")))
        .withColumn("middle_initial", F.trim(F.col("BORR_MID_INIT")))
        .withColumn("ssn_hash", F.col("BORR_SSN_ENCR"))
        .withColumn("date_of_birth", parse_legacy_date("BORR_DOB_DT"))
        .withColumn("address_line1", F.col("BORR_ADDR_LN1"))
        .withColumn("address_line2", F.col("BORR_ADDR_LN2"))
        .withColumn("city", F.col("BORR_CTY_NM"))
        .withColumn("state", F.col("BORR_ST_CD"))
        .withColumn("zip_code", F.col("BORR_ZIP_CD"))
        .withColumn("phone", F.col("BORR_PH_NBR"))
        .withColumn("email", F.col("BORR_EMAIL_ADDR"))
        .withColumn("credit_score", parse_legacy_integer("BORR_CRDT_SCR"))
        .withColumn("employment_status", F.col("BORR_EMP_STAT"))
        .withColumn("annual_income", parse_legacy_amount("BORR_ANN_INCM"))
        .withColumn("status", expand_status_code("BORR_STAT_CD", BORROWER_STATUS_MAP))
        .withColumn("created_at", parse_legacy_timestamp("BORR_CRET_DT"))
        .withColumn("updated_at", parse_legacy_timestamp("BORR_UPDT_DT"))
        .withColumn("_legacy_borr_id", F.col("BORR_ID"))
    )

    # Flag required-field nulls
    transformed = flag_nulls(
        transformed,
        columns=["first_name", "last_name", "external_id"],
        record_id_col="external_id",
    )

    # Flag date parse failures
    transformed = flag_parse_failures(
        transformed, "BORR_DOB_DT", "date_of_birth", "external_id"
    )
    transformed = flag_parse_failures(
        transformed, "BORR_ANN_INCM", "annual_income", "external_id"
    )

    # Log warnings (collect to driver — acceptable for CDW volumes)
    _log_warnings(transformed)

    # Select only modern columns
    return transformed.select(
        "external_id", "first_name", "last_name", "middle_initial",
        "ssn_hash", "date_of_birth", "address_line1", "address_line2",
        "city", "state", "zip_code", "phone", "email", "credit_score",
        "employment_status", "annual_income", "status",
        "created_at", "updated_at", "_legacy_borr_id",
    )


def write_borrowers(df: DataFrame, mode: str = "overwrite") -> None:
    """Write transformed borrowers to the Delta Lake target table."""
    (
        df.write
        .format("delta")
        .mode(mode)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )


def _log_warnings(df: DataFrame) -> None:
    """Collect and print warning rows for operator visibility."""
    warn_cols = [c for c in df.columns if c.startswith("_null_warn") or c.startswith("_parse_warn")]
    for wc in warn_cols:
        warnings = (
            df.filter(F.col(wc).isNotNull())
            .select(wc)
            .collect()
        )
        for row in warnings:
            print(f"WARNING [{wc}]: {row[0]}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession = None) -> int:
    """Execute the borrower ingestion pipeline. Returns row count written."""
    if spark is None:
        spark = SparkSession.builder.getOrCreate()

    print("=" * 70)
    print("INGESTION: CDW_BORR_MSTR -> loan_warehouse.borrowers")
    print("=" * 70)

    raw = read_legacy_borrowers(spark)
    source_count = raw.count()
    print(f"Source rows read: {source_count}")

    transformed = transform_borrowers(raw)
    target_count = transformed.count()
    print(f"Target rows to write: {target_count}")

    write_borrowers(transformed)
    print(f"SUCCESS: {target_count} rows written to {TARGET_TABLE}")

    return target_count


if __name__ == "__main__":
    run()
