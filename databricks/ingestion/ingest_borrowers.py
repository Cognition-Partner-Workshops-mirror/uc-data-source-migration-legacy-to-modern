"""
PySpark Ingestion Script: Borrowers
Source: CDW_BORR_MSTR (legacy CSV/Parquet extract)
Target: loan_warehouse.borrowers (Delta Lake)

Transformations applied:
  - BORR_DOB_DT (MM/DD/YYYY string) -> date_of_birth (DateType)
  - BORR_CRDT_SCR (string) -> credit_score (IntegerType)
  - BORR_ANN_INCM (comma-formatted string) -> annual_income (DecimalType)
  - BORR_CRET_DT / BORR_UPDT_DT -> created_at / updated_at (TimestampType)
  - BORR_STAT_CD (ACT/INA) -> status (Active/Inactive)
  - BORR_REC_TYP -> dropped (not needed in modern schema)
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from utils import (
    BORROWER_STATUS_MAP,
    col_expand_status,
    col_parse_amount,
    col_parse_date,
    col_parse_int,
    col_parse_timestamp,
    log_row_counts,
    quarantine_malformed_rows,
    tag_migration_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/legacy-extracts/CDW_BORR_MSTR/"
SOURCE_FORMAT = "csv"  # Change to "parquet" if source is Parquet
TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_TABLE = "loan_warehouse._quarantine_borrowers"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "quote": '"',
    "escape": '"',
}


def read_source(spark: SparkSession):
    """Read the legacy CDW_BORR_MSTR extract."""
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for key, val in CSV_OPTIONS.items():
            reader = reader.option(key, val)
    return reader.load(SOURCE_PATH)


def transform(df):
    """Apply all column mappings and type conversions."""
    transformed = df.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        col_parse_date("BORR_DOB_DT", "date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        col_parse_int("BORR_CRDT_SCR", "credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        col_parse_amount("BORR_ANN_INCM", "annual_income"),
        col_expand_status("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),
        col_parse_timestamp("BORR_CRET_DT", "created_at"),
        col_parse_timestamp("BORR_UPDT_DT", "updated_at"),
        # BORR_REC_TYP intentionally dropped per mapping spec
    )
    return transformed


def run(spark: SparkSession):
    """Execute the full borrower ingestion pipeline."""
    print(f"[MIGRATION] Starting borrower ingestion from {SOURCE_PATH}")

    # Read
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"[MIGRATION] Read {source_count} rows from CDW_BORR_MSTR")

    # Transform
    transformed_df = transform(source_df)

    # Add migration metadata
    transformed_df = tag_migration_metadata(transformed_df, "CDW_BORR_MSTR")

    # Quarantine rows with NULL in required fields
    required_cols = ["external_id", "first_name", "last_name"]
    valid_df, quarantine_df = quarantine_malformed_rows(
        transformed_df, required_cols, "CDW_BORR_MSTR", spark
    )

    # Write quarantined rows
    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        print(f"[MIGRATION] WARNING: {quarantine_count} rows quarantined for borrowers")
        quarantine_df.write.format("delta").mode("append").saveAsTable(QUARANTINE_TABLE)

    # Deduplicate on external_id (keep latest updated_at)
    from pyspark.sql.window import Window
    dedup_window = Window.partitionBy("external_id").orderBy(F.col("updated_at").desc())
    valid_df = (
        valid_df
        .withColumn("_row_num", F.row_number().over(dedup_window))
        .filter(F.col("_row_num") == 1)
        .drop("_row_num")
    )

    # Write to Delta Lake target
    target_count = valid_df.count()
    valid_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    # Reconciliation
    stats = log_row_counts(spark, source_count, target_count, quarantine_count, "borrowers")
    print(f"[MIGRATION] Borrower ingestion complete")
    return stats


# ---------------------------------------------------------------------------
# Entry point for Databricks notebook or spark-submit
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_Borrowers").getOrCreate()
    try:
        run(spark)
    finally:
        spark.stop()
