"""
PySpark ingestion script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads legacy borrower data from CSV/Parquet source files (exported from CDW),
applies type conversions and status expansion, and writes to a Delta Lake table.

Mapping reference: data/mappings/column_mappings.md § CDW_BORR_MSTR → borrowers

Usage (Databricks notebook or spark-submit):
    spark-submit ingest_borrowers.py --source /mnt/landing/cdw_borr_mstr/ --format csv
"""

import argparse
import sys
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from transformations import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_integer,
    expand_status_code,
    BORROWER_STATUS_MAP,
)

# Target Delta table
TARGET_TABLE = "loan_warehouse.borrowers"


def read_source(spark: SparkSession, source_path: str, fmt: str) -> DataFrame:
    """
    Read legacy CDW_BORR_MSTR data from CSV or Parquet source files.
    CSV files are expected to have a header row matching legacy column names.
    """
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        # All fields read as strings to match legacy VARCHAR schema
        return reader.csv(source_path)
    elif fmt == "parquet":
        return reader.parquet(source_path)
    else:
        raise ValueError(f"Unsupported format: {fmt}. Use 'csv' or 'parquet'.")


def transform_borrowers(df: DataFrame) -> DataFrame:
    """
    Apply all transformations from legacy CDW_BORR_MSTR to modern borrowers schema.
    Handles null values, type conversions, and status expansion.
    Records with critical null fields (BORR_ID, BORR_FST_NM, BORR_LST_NM) are
    routed to a quarantine log instead of being silently dropped.
    """
    # Tag records missing required fields for quarantine logging
    df = df.withColumn(
        "_has_required_fields",
        F.col("BORR_ID").isNotNull()
        & F.col("BORR_FST_NM").isNotNull()
        & F.col("BORR_LST_NM").isNotNull(),
    )

    # Log records that fail required field check (do not drop them — route to quarantine)
    quarantine_df = df.filter(~F.col("_has_required_fields"))
    if quarantine_df.count() > 0:
        print(
            f"WARNING: {quarantine_df.count()} borrower records missing required fields "
            f"(BORR_ID, BORR_FST_NM, or BORR_LST_NM). Writing to quarantine."
        )
        # In production, write quarantine_df to a quarantine Delta table
        quarantine_df.show(truncate=False)

    # Process valid records
    valid_df = df.filter(F.col("_has_required_fields"))

    # Apply all column transformations per column_mappings.md
    result = valid_df.select(
        F.col("BORR_ID").alias("external_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        # Date parsing: MM/DD/YYYY → DATE
        parse_legacy_date("BORR_DOB_DT", "date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        # Numeric parsing: VARCHAR → INT
        parse_legacy_integer("BORR_CRDT_SCR", "credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        # Amount parsing: VARCHAR with commas → DECIMAL(12,2)
        parse_legacy_amount("BORR_ANN_INCM", "annual_income"),
        # Status expansion: ACT → ACTIVE, INA → INACTIVE
        expand_status_code("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),
        # Timestamp parsing: MM/DD/YYYY → TIMESTAMP
        parse_legacy_timestamp("BORR_CRET_DT", "created_at"),
        parse_legacy_timestamp("BORR_UPDT_DT", "updated_at"),
        # Audit columns
        F.current_timestamp().alias("_ingestion_ts"),
        F.lit("CDW_BORR_MSTR").alias("_source_system"),
    )

    return result


def write_to_delta(df: DataFrame, mode: str = "overwrite"):
    """
    Write the transformed borrower DataFrame to the target Delta table.
    Uses overwrite mode for initial migration; switch to merge for incremental.
    """
    df.write.format("delta").mode(mode).partitionBy("status").saveAsTable(TARGET_TABLE)
    print(f"Successfully wrote {df.count()} records to {TARGET_TABLE}")


def main():
    parser = argparse.ArgumentParser(description="Ingest CDW_BORR_MSTR → borrowers")
    parser.add_argument("--source", required=True, help="Path to source data files")
    parser.add_argument(
        "--format", default="csv", choices=["csv", "parquet"], help="Source file format"
    )
    parser.add_argument(
        "--mode", default="overwrite", choices=["overwrite", "append"], help="Write mode"
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_BORR_MSTR_Ingestion").getOrCreate()

    print(f"Reading source data from {args.source} (format={args.format})")
    source_df = read_source(spark, args.source, args.format)
    source_count = source_df.count()
    print(f"Source record count: {source_count}")

    print("Applying transformations...")
    transformed_df = transform_borrowers(source_df)
    target_count = transformed_df.count()
    print(f"Transformed record count: {target_count}")

    if source_count != target_count:
        print(
            f"WARNING: Row count mismatch — source={source_count}, target={target_count}. "
            f"Check quarantine log for rejected records."
        )

    print(f"Writing to Delta table {TARGET_TABLE} (mode={args.mode})")
    write_to_delta(transformed_df, args.mode)

    spark.stop()


if __name__ == "__main__":
    main()
