"""
PySpark ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master table (exported as CSV/Parquet) and transforms
all-VARCHAR columns into properly typed Delta Lake columns per column_mappings.md.

Key transformations:
- Parse date strings (MM/DD/YYYY) to DateType/TimestampType
- Parse comma-formatted income strings to DecimalType
- Parse credit score strings to IntegerType with range validation (300-850)
- Expand borrower status codes (ACT -> ACTIVE, INA -> INACTIVE)
- Drop BORR_REC_TYP (not needed in modern schema)
- Flag and log all parse errors without dropping records
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    read_legacy_csv,
    read_legacy_parquet,
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_integer,
    expand_status_code,
    add_pipeline_metadata,
    log_parse_errors,
    BORROWER_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration — adjust these paths per environment
# ---------------------------------------------------------------------------
# Source path: location of the legacy CDW_BORR_MSTR export (CSV or Parquet)
SOURCE_PATH = "/mnt/landing/cdw/CDW_BORR_MSTR/"
# Target Delta table in the catalog
TARGET_TABLE = "loan_warehouse.borrowers"
# Source format: "csv" or "parquet"
SOURCE_FORMAT = "csv"


def read_source(spark: SparkSession) -> DataFrame:
    """Read the legacy borrower data from the landing zone."""
    if SOURCE_FORMAT == "parquet":
        return read_legacy_parquet(spark, SOURCE_PATH)
    return read_legacy_csv(spark, SOURCE_PATH)


def transform(df: DataFrame) -> DataFrame:
    """
    Apply all transformations from CDW_BORR_MSTR to modern borrowers schema.

    Transformation order follows dependency: simple renames first, then type
    conversions, then derived/expanded columns, then metadata.
    """
    # --- Step 1: Rename columns from cryptic legacy names to modern names ---
    renamed = (
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

    # --- Step 2: Parse date of birth string to DateType ---
    renamed = parse_legacy_date(renamed, "BORR_DOB_DT", "date_of_birth")

    # --- Step 3: Parse credit score string to IntegerType with range validation ---
    renamed = parse_legacy_integer(renamed, "BORR_CRDT_SCR", "credit_score")
    # Flag out-of-range credit scores (valid FICO range: 300-850)
    renamed = renamed.withColumn(
        "credit_score_out_of_range",
        F.when(
            F.col("credit_score").isNotNull()
            & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850)),
            True
        ).otherwise(False)
    )

    # --- Step 4: Parse annual income (comma-formatted string -> Decimal) ---
    renamed = parse_legacy_amount(renamed, "BORR_ANN_INCM", "annual_income")

    # --- Step 5: Expand borrower status code (ACT -> ACTIVE, etc.) ---
    renamed = expand_status_code(
        renamed, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP
    )

    # --- Step 6: Parse audit timestamps (date string -> Timestamp at midnight) ---
    renamed = parse_legacy_timestamp(renamed, "BORR_CRET_DT", "created_at")
    renamed = parse_legacy_timestamp(renamed, "BORR_UPDT_DT", "updated_at")

    # --- Step 7: Add pipeline metadata columns ---
    renamed = add_pipeline_metadata(renamed, "CDW_BORR_MSTR")

    # --- Step 8: Select only modern schema columns (drop legacy intermediates) ---
    result = renamed.select(
        "external_id",
        "first_name",
        "last_name",
        "middle_initial",
        "ssn_hash",
        "date_of_birth",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "zip_code",
        "phone",
        "email",
        "credit_score",
        "employment_status",
        "annual_income",
        "status",
        "created_at",
        "updated_at",
        "_ingested_at",
        "_source_system",
    )

    return result


def load(df: DataFrame):
    """Write the transformed borrower data to the Delta Lake target table."""
    (
        df.write
        .format("delta")
        .mode("overwrite")  # Full refresh for initial migration; switch to merge for incremental
        .option("overwriteSchema", "true")
        .partitionBy("state")
        .saveAsTable(TARGET_TABLE)
    )


def run(spark: SparkSession):
    """
    Main entry point: read -> transform -> load for borrower ingestion.

    Logs parse error counts before writing so issues are visible in Spark driver logs.
    """
    raw_df = read_source(spark)

    transformed_df = transform(raw_df)

    # Log any parse/mapping issues before loading (non-blocking)
    log_parse_errors(transformed_df, "borrowers", [
        "date_of_birth_parse_error",
        "credit_score_parse_error",
        "credit_score_out_of_range",
        "annual_income_parse_error",
        "status_unmapped",
        "created_at_parse_error",
        "updated_at_parse_error",
    ])

    load(transformed_df)
    print(f"[borrowers] Ingestion complete. Rows written: {transformed_df.count()}")


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_BORR_MSTR_Ingestion").getOrCreate()
    run(spark)
