"""
Ingestion script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads legacy borrower data from CSV/Parquet source files, applies
transformations per column_mappings.md, and writes to Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from common_transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_integer,
    expand_status_code,
    add_ingestion_metadata,
    flag_null_required_fields,
    log_rejected_records,
    BORROWER_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_BORR_MSTR/"
SOURCE_FORMAT = "csv"  # or "parquet" depending on extract format
TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_PATH = "dbfs:/mnt/legacy-cdw/quarantine/borrowers/"

REQUIRED_FIELDS = ["borrower_id", "first_name", "last_name", "status"]

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "mode": "PERMISSIVE",
    "columnNameOfCorruptRecord": "_corrupt_record",
}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH) -> DataFrame:
    """Read legacy borrower data from source files."""
    return (
        spark.read
        .format(SOURCE_FORMAT)
        .options(**CSV_OPTIONS)
        .load(path)
    )


def transform(df: DataFrame) -> DataFrame:
    """Apply all column mappings and type conversions."""
    transformed = df.select(
        F.trim(F.col("BORR_ID")).alias("borrower_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_legacy_date("BORR_DOB_DT", "date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        parse_legacy_integer("BORR_CRDT_SCR", "credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_legacy_amount("BORR_ANN_INCM", "annual_income"),
        expand_status_code("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),
        parse_legacy_timestamp("BORR_CRET_DT", "created_at"),
        parse_legacy_timestamp("BORR_UPDT_DT", "updated_at"),
    )
    return transformed


def validate_and_split(
    df: DataFrame, spark: SparkSession
) -> tuple:
    """Flag records with null required fields; split into valid and rejected."""
    df = flag_null_required_fields(df, REQUIRED_FIELDS)
    valid_df, rejected_df = log_rejected_records(df, "_has_nulls", "borrowers", spark)
    valid_df = valid_df.drop("_has_nulls")
    return valid_df, rejected_df


def write_target(df: DataFrame) -> None:
    """Write valid records to the borrowers Delta table."""
    (
        df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("status")
        .saveAsTable(TARGET_TABLE)
    )


def write_quarantine(df: DataFrame) -> None:
    """Write rejected records to quarantine for investigation."""
    if df.count() > 0:
        (
            df.write
            .format("delta")
            .mode("append")
            .save(QUARANTINE_PATH)
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession, source_path: str = SOURCE_PATH) -> dict:
    """
    Execute the full borrower ingestion pipeline.
    Returns a summary dict with row counts.
    """
    raw_df = read_source(spark, source_path)
    source_count = raw_df.count()

    transformed_df = transform(raw_df)
    transformed_df = add_ingestion_metadata(transformed_df)

    valid_df, rejected_df = validate_and_split(transformed_df, spark)
    valid_count = valid_df.count()
    rejected_count = rejected_df.count()

    write_target(valid_df)
    write_quarantine(rejected_df)

    summary = {
        "table": "borrowers",
        "source_count": source_count,
        "valid_count": valid_count,
        "rejected_count": rejected_count,
    }
    print(f"[borrowers] Ingested {valid_count}/{source_count} records "
          f"({rejected_count} quarantined)")
    return summary


if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestBorrowers").getOrCreate()
    run(spark)
