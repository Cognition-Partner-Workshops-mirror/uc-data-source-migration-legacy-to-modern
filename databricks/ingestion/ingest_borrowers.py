"""
Ingest borrowers from legacy CDW_BORR_MSTR into Delta Lake ``loan_warehouse.borrowers``.

Transformations applied:
  - BORR_DOB_DT  (MM/DD/YYYY string)  -> date_of_birth  (DateType)
  - BORR_ANN_INCM (comma string)      -> annual_income   (Decimal)
  - BORR_CRDT_SCR (string)            -> credit_score    (IntegerType)
  - BORR_STAT_CD  (ACT/INA)           -> status          (expanded)
  - BORR_CRET_DT / BORR_UPDT_DT      -> created_at / updated_at (Timestamp)
  - BORR_REC_TYP                      -> dropped (not needed)

Usage (Databricks notebook):
    %run ./common_utils
    %run ./ingest_borrowers

Or as a standalone script:
    spark-submit ingest_borrowers.py --source /mnt/landing/cdw_borr_mstr --format csv
"""

import argparse
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from common_utils import (
    BORROWER_STATUS_MAP,
    collect_parse_errors,
    drop_audit_columns,
    expand_status_col,
    log_error_summary,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
    read_legacy_source,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TARGET_TABLE = "loan_warehouse.borrowers"
SOURCE_SYSTEM = "CDW_BORR_MSTR"
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_borr_mstr"


def transform_borrowers(raw_df):
    """Apply all column-level transformations to a raw CDW_BORR_MSTR DataFrame."""

    df = raw_df

    # --- Date / Timestamp conversions ---
    df = parse_date_col(df, "BORR_DOB_DT", "date_of_birth")
    df = parse_timestamp_col(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "BORR_UPDT_DT", "updated_at")

    # --- Numeric conversions ---
    df = parse_int_col(df, "BORR_CRDT_SCR", "credit_score")
    df = parse_amount_col(df, "BORR_ANN_INCM", "annual_income", precision=12, scale=2)

    # --- Status expansion ---
    df = expand_status_col(df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)

    # --- Direct-copy renames ---
    df = (
        df.withColumn("external_id", F.col("BORR_ID"))
          .withColumn("first_name", F.col("BORR_FST_NM"))
          .withColumn("last_name", F.col("BORR_LST_NM"))
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

    # --- Metadata columns ---
    df = (
        df.withColumn("_migration_ts", F.current_timestamp())
          .withColumn("_source_system", F.lit(SOURCE_SYSTEM))
    )

    return df


def run(spark, source_path, source_format="csv", write_mode="overwrite"):
    """End-to-end ingestion pipeline for borrowers."""

    print(f"=== Ingesting {SOURCE_SYSTEM} -> {TARGET_TABLE} ===")
    print(f"  Source: {source_path} ({source_format})")

    # 1. Read raw legacy data
    raw_df = read_legacy_source(spark, source_path, fmt=source_format)
    source_count = raw_df.count()
    print(f"  Source row count: {source_count}")

    if source_count == 0:
        print("  WARNING: Source is empty. Skipping ingestion.")
        return {"source_count": 0, "target_count": 0, "errors": {}}

    # 2. Transform
    transformed_df = transform_borrowers(raw_df)

    # 3. Log parse errors (do NOT drop — log them)
    error_summary = log_error_summary(transformed_df, SOURCE_SYSTEM)
    error_rows = collect_parse_errors(transformed_df)
    error_count = error_rows.count()
    if error_count > 0:
        print(f"  WARNING: {error_count} row(s) had parse issues — writing anyway.")
        error_rows.write.mode("overwrite").parquet(
            f"/mnt/migration_errors/{SOURCE_SYSTEM}_errors"
        )

    # 4. Select final columns and drop audit flags
    final_df = drop_audit_columns(transformed_df).select(
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
        "_migration_ts",
        "_source_system",
    )

    # 5. Write to Delta
    (
        final_df.write
        .format("delta")
        .mode(write_mode)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    target_count = spark.table(TARGET_TABLE).count()
    print(f"  Target row count: {target_count}")
    print(f"  Reconciliation: source={source_count}, target={target_count}, "
          f"match={source_count == target_count}")
    print(f"=== {SOURCE_SYSTEM} ingestion complete ===\n")

    return {
        "source_count": source_count,
        "target_count": target_count,
        "errors": error_summary,
    }


# ---------------------------------------------------------------------------
# CLI entry point (for spark-submit)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_BORR_MSTR into Delta Lake")
    parser.add_argument("--source", default=DEFAULT_SOURCE_PATH, help="Source file path")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    spark = SparkSession.builder.appName("IngestBorrowers").getOrCreate()
    result = run(spark, args.source, args.format, args.mode)
    if result["source_count"] != result["target_count"]:
        print("ERROR: Row count mismatch!")
        sys.exit(1)
