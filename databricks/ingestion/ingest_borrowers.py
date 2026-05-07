"""
Ingest legacy CDW_BORR_MSTR data into modern Delta Lake borrowers table.

Usage (Databricks notebook or spark-submit):
    %run ./ingest_borrowers

Source: CSV/Parquet export of CDW_BORR_MSTR
Target: loan_warehouse.borrowers (Delta Lake)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transformations import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_status_col,
    flag_parse_failures,
    quarantine_bad_records,
    BORROWER_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy-exports/CDW_BORR_MSTR/"
LEGACY_SOURCE_FORMAT = "csv"  # or "parquet"
TARGET_TABLE = "loan_migration.loan_warehouse.borrowers"
QUARANTINE_PATH = "dbfs:/mnt/migration-quarantine/borrowers/"

# CSV read options (when source is CSV export from legacy)
CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",  # all columns read as STRING to match legacy
    "nullValue": "",
    "emptyValue": "",
}


def read_legacy_borrowers(spark: SparkSession) -> DataFrame:
    """Read legacy borrower data from CSV or Parquet source files."""
    reader = spark.read.format(LEGACY_SOURCE_FORMAT)
    if LEGACY_SOURCE_FORMAT == "csv":
        reader = reader.options(**CSV_OPTIONS)
    return reader.load(LEGACY_SOURCE_PATH)


def transform_borrowers(df: DataFrame) -> DataFrame:
    """Apply all transformations from legacy CDW_BORR_MSTR to modern borrowers schema."""

    # --- Date columns: MM/DD/YYYY -> DateType / TimestampType ---
    df = parse_date_col(df, "BORR_DOB_DT", "date_of_birth")
    df = parse_timestamp_col(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "BORR_UPDT_DT", "updated_at")

    # --- Numeric columns ---
    df = parse_int_col(df, "BORR_CRDT_SCR", "credit_score")
    df = parse_amount_col(df, "BORR_ANN_INCM", "annual_income")

    # --- Status expansion: ACT -> ACTIVE, INA -> INACTIVE ---
    df = expand_status_col(df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)

    # --- Flag parse failures for quarantine ---
    df = flag_parse_failures(df, "BORR_DOB_DT", "date_of_birth", "_bad_dob")
    df = flag_parse_failures(df, "BORR_ANN_INCM", "annual_income", "_bad_income")
    df = flag_parse_failures(df, "BORR_CRDT_SCR", "credit_score", "_bad_credit")

    # --- Direct-copy renames ---
    df = (
        df
        .withColumn("external_id", F.col("BORR_ID"))
        .withColumn("first_name", F.trim(F.col("BORR_FST_NM")))
        .withColumn("last_name", F.trim(F.col("BORR_LST_NM")))
        .withColumn("middle_initial", F.col("BORR_MID_INIT"))
        .withColumn("ssn_hash", F.col("BORR_SSN_ENCR"))
        .withColumn("address_line1", F.col("BORR_ADDR_LN1"))
        .withColumn("address_line2", F.col("BORR_ADDR_LN2"))
        .withColumn("city", F.col("BORR_CTY_NM"))
        .withColumn("state", F.col("BORR_ST_CD"))
        .withColumn("zip_code", F.col("BORR_ZIP_CD"))
        .withColumn("phone", F.col("BORR_PH_NBR"))
        .withColumn("email", F.col("BORR_EMAIL_ADDR"))
        .withColumn("employment_status", F.col("BORR_EMP_STAT"))
    )

    # --- Lineage columns ---
    df = (
        df
        .withColumn("_migration_source", F.lit("CDW_BORR_MSTR"))
        .withColumn("_migrated_at", F.current_timestamp())
    )

    return df


def run_borrower_ingestion(spark: SparkSession) -> dict:
    """Execute full borrower ingestion pipeline. Returns row count stats."""
    print("=" * 60)
    print("BORROWER INGESTION: CDW_BORR_MSTR -> borrowers")
    print("=" * 60)

    # Read
    raw_df = read_legacy_borrowers(spark)
    source_count = raw_df.count()
    print(f"Source records read: {source_count}")

    # Transform
    transformed_df = transform_borrowers(raw_df)

    # Quarantine bad records
    good_df, bad_df = quarantine_bad_records(
        transformed_df, ["_bad_dob", "_bad_income", "_bad_credit"]
    )
    bad_count = bad_df.count()
    if bad_count > 0:
        print(f"WARNING: {bad_count} records quarantined due to parse failures")
        bad_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)
    else:
        print("No records quarantined — all parsed successfully")

    # Select final columns (drop flags and legacy columns)
    final_columns = [
        "external_id", "first_name", "last_name", "middle_initial",
        "ssn_hash", "date_of_birth", "address_line1", "address_line2",
        "city", "state", "zip_code", "phone", "email", "credit_score",
        "employment_status", "annual_income", "status",
        "created_at", "updated_at", "_migration_source", "_migrated_at",
    ]
    output_df = good_df.select(*final_columns)

    # Write to Delta Lake
    (
        output_df
        .write
        .format("delta")
        .mode("overwrite")
        .partitionBy("state")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    target_count = spark.table(TARGET_TABLE).count()
    print(f"Target records written: {target_count}")
    print(f"Quarantined records:    {bad_count}")
    print("Borrower ingestion complete.")

    return {
        "source_count": source_count,
        "target_count": target_count,
        "quarantined_count": bad_count,
    }


# ---------------------------------------------------------------------------
# Entry point (for notebook %run or spark-submit)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_Borrowers").getOrCreate()
    stats = run_borrower_ingestion(spark)
    print(f"\nFinal stats: {stats}")
