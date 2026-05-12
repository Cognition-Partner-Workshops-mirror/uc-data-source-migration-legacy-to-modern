"""
Ingestion script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads the legacy borrower master table (simulated as CSV/Parquet),
applies all transformations from column_mappings.md, and writes
to the modern Delta Lake borrowers table.

Execution order: Run FIRST — borrowers is the dimension table
referenced by loan_accounts.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_integer,
    parse_legacy_amount,
    expand_borrower_status,
)

# =============================================================================
# Configuration — adjust paths for your Databricks environment
# =============================================================================
LEGACY_SOURCE_PATH = "/mnt/legacy-data/CDW_BORR_MSTR"  # CSV or Parquet
LEGACY_SOURCE_FORMAT = "csv"  # Change to "parquet" if source is Parquet
TARGET_TABLE = "loan_warehouse.borrowers"
# Quarantine table for records that fail validation
QUARANTINE_PATH = "/mnt/migration/quarantine/borrowers"


def read_legacy_borrowers(spark: SparkSession) -> DataFrame:
    """
    Read legacy borrower data from source files.
    All columns are read as STRING to match the legacy VARCHAR-everything pattern.
    """
    return (
        spark.read
        .format(LEGACY_SOURCE_FORMAT)
        .option("header", "true")
        .option("inferSchema", "false")  # Read everything as string to match legacy schema
        .load(LEGACY_SOURCE_PATH)
    )


def transform_borrowers(df: DataFrame) -> DataFrame:
    """
    Apply all transformations documented in column_mappings.md § CDW_BORR_MSTR → borrowers.
    Drops the BORR_REC_TYP column (not needed in modern schema).
    """
    transformed = df.select(
        # Direct copy fields
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),

        # Date parsing: MM/DD/YYYY string → DATE / TIMESTAMP
        parse_legacy_date(F.col("BORR_DOB_DT")).alias("date_of_birth"),

        # Address fields — direct copy
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),

        # Contact fields — direct copy
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),

        # Numeric parsing: VARCHAR → INT / DECIMAL
        parse_legacy_integer(F.col("BORR_CRDT_SCR")).alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_legacy_amount(F.col("BORR_ANN_INCM")).alias("annual_income"),

        # Status expansion: ACT→ACTIVE, INA→INACTIVE
        expand_borrower_status(F.col("BORR_STAT_CD")).alias("status"),

        # Timestamps
        parse_legacy_timestamp(F.col("BORR_CRET_DT")).alias("created_at"),
        parse_legacy_timestamp(F.col("BORR_UPDT_DT")).alias("updated_at"),
    )

    return transformed


def quarantine_invalid_records(df: DataFrame) -> tuple:
    """
    Separate valid records from invalid ones.
    Invalid records (null required fields after transformation) are written to quarantine
    instead of being silently dropped.

    Returns (valid_df, quarantine_df) tuple.
    """
    # Required fields that must be non-null after transformation
    required_fields = ["external_id", "first_name", "last_name", "ssn_hash"]

    # Build condition: any required field is null
    null_condition = F.lit(False)
    for field in required_fields:
        null_condition = null_condition | F.col(field).isNull()

    valid_df = df.filter(~null_condition)
    quarantine_df = df.filter(null_condition)

    return valid_df, quarantine_df


def run_ingestion():
    """Main ingestion entry point for Databricks notebook execution."""
    spark = SparkSession.builder.appName("Ingest CDW_BORR_MSTR → borrowers").getOrCreate()

    print("=" * 60)
    print("INGESTION: CDW_BORR_MSTR → loan_warehouse.borrowers")
    print("=" * 60)

    # Step 1: Read legacy source
    legacy_df = read_legacy_borrowers(spark)
    source_count = legacy_df.count()
    print(f"Source records read: {source_count}")

    # Step 2: Transform
    transformed_df = transform_borrowers(legacy_df)

    # Step 3: Quarantine invalid records
    valid_df, quarantine_df = quarantine_invalid_records(transformed_df)
    quarantine_count = quarantine_df.count()
    valid_count = valid_df.count()

    if quarantine_count > 0:
        print(f"WARNING: {quarantine_count} record(s) quarantined due to null required fields")
        quarantine_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)
    else:
        print("All records passed required-field validation")

    # Step 4: Write to Delta Lake target
    valid_df.write.mode("overwrite").format("delta").saveAsTable(TARGET_TABLE)
    print(f"Target records written: {valid_count}")
    print(f"Source→Target reconciliation: {source_count} → {valid_count} (+{quarantine_count} quarantined)")


# Databricks notebook entry point
if __name__ == "__main__":
    run_ingestion()
