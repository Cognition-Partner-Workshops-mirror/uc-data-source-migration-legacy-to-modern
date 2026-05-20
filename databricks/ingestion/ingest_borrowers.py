"""
ingest_borrowers.py — PySpark ingestion script for the borrowers dimension table.

Reads from the legacy CDW_BORR_MSTR source (simulated as CSV/Parquet), applies
all required transformations per column_mappings.md, and writes to the Delta Lake
loan_management.borrowers table.

Source: CDW_BORR_MSTR (legacy all-VARCHAR borrower master)
Target: loan_management.borrowers (typed Delta Lake table)

Transformations:
  - BORR_DOB_DT (MM/DD/YYYY) → date_of_birth (DATE)
  - BORR_CRDT_SCR (VARCHAR) → credit_score (INT)
  - BORR_ANN_INCM ("92,500") → annual_income (DECIMAL(12,2))
  - BORR_STAT_CD (ACT/INA) → status (ACTIVE/INACTIVE)
  - BORR_CRET_DT / BORR_UPDT_DT → created_at / updated_at (TIMESTAMP)
  - BORR_REC_TYP dropped (not needed in modern schema)
"""

from pyspark.sql import SparkSession, functions as F

from common_transforms import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_status_col,
    add_parse_error_flags,
    log_transformation_summary,
    BORROWER_STATUS_MAP,
)

# =============================================================================
# Configuration — update these paths for your Databricks environment
# =============================================================================
# Source path: location of the legacy CDW_BORR_MSTR extract (CSV or Parquet)
SOURCE_PATH = "/mnt/legacy-data/cdw_borr_mstr/"
# Source format: "csv" or "parquet" depending on how the legacy extract is staged
SOURCE_FORMAT = "csv"
# Target Delta table
TARGET_TABLE = "loan_management.borrowers"


def read_source(spark, path=SOURCE_PATH, fmt=SOURCE_FORMAT):
    """
    Read the legacy CDW_BORR_MSTR source data.
    Supports CSV (with header) and Parquet formats.
    All columns are read as strings to match the legacy all-VARCHAR schema.
    """
    if fmt == "csv":
        return (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")  # Keep everything as string
            .csv(path)
        )
    elif fmt == "parquet":
        return spark.read.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform_borrowers(df):
    """
    Apply all transformations to convert legacy CDW_BORR_MSTR columns
    to the modern borrowers schema per column_mappings.md.
    """
    # Rename direct-copy columns from legacy cryptic names to modern names
    transformed = (
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

    # Parse date of birth: MM/DD/YYYY string → DATE
    transformed = parse_date_col(transformed, "BORR_DOB_DT", "date_of_birth")

    # Parse credit score: VARCHAR → INT
    transformed = parse_int_col(transformed, "BORR_CRDT_SCR", "credit_score")

    # Parse annual income: comma-formatted string → DECIMAL(12,2)
    transformed = parse_amount_col(transformed, "BORR_ANN_INCM", "annual_income")

    # Expand status code: ACT → ACTIVE, INA → INACTIVE
    transformed = expand_status_col(
        transformed, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP
    )

    # Parse created/updated dates: MM/DD/YYYY → TIMESTAMP
    transformed = parse_timestamp_col(transformed, "BORR_CRET_DT", "created_at")
    transformed = parse_timestamp_col(transformed, "BORR_UPDT_DT", "updated_at")

    # Add parse error flags for monitoring (dates and amounts that failed parsing)
    transformed = add_parse_error_flags(
        transformed,
        date_cols=[
            ("BORR_DOB_DT", "date_of_birth"),
            ("BORR_CRET_DT", "created_at"),
            ("BORR_UPDT_DT", "updated_at"),
        ],
        amount_cols=[
            ("BORR_ANN_INCM", "annual_income"),
        ],
    )

    # Select only the modern schema columns (drop legacy-only columns like BORR_REC_TYP)
    result = transformed.select(
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
        "_parse_errors",
    )

    return result


def write_target(df, table=TARGET_TABLE, mode="overwrite"):
    """
    Write the transformed borrower data to the Delta Lake target table.
    Uses overwrite mode for initial migration; switch to merge for incremental.
    """
    (
        df
        .drop("_parse_errors")  # Remove internal error tracking before writing
        .write
        .format("delta")
        .mode(mode)
        .saveAsTable(table)
    )


def run(spark=None):
    """
    Main entry point: read legacy borrower data, transform, validate, and write.
    Returns a summary dict with row counts for reconciliation.
    """
    if spark is None:
        spark = SparkSession.builder.appName("IngestBorrowers").getOrCreate()

    print("=" * 60)
    print("Starting borrower ingestion from CDW_BORR_MSTR")
    print("=" * 60)

    # Step 1: Read legacy source
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"Source rows read: {source_count}")

    # Step 2: Transform to modern schema
    transformed_df = transform_borrowers(source_df)

    # Step 3: Log transformation summary (includes parse error details)
    total, errors = log_transformation_summary(transformed_df, "borrowers")

    # Step 4: Write to Delta Lake target
    write_target(transformed_df)
    print(f"Successfully wrote {total} rows to {TARGET_TABLE}")

    return {"source_count": source_count, "target_count": total, "error_count": errors}


# Allow standalone execution in Databricks notebooks or spark-submit
if __name__ == "__main__":
    run()
