"""
Master orchestration script for the full CDW -> Delta Lake migration.

Runs each ingestion step in dependency order and collects all bad-value
reports into a single union DataFrame for quality analysis.

Usage (Databricks notebook):
    # Set widgets or parameters
    dbutils.widgets.text("source_base_path", "dbfs:/mnt/legacy_export")
    dbutils.widgets.dropdown("source_format", "csv", ["csv", "parquet"])

    %run ./run_pipeline

Usage (Databricks job):
    from ingestion.run_pipeline import run_full_pipeline
    run_full_pipeline(spark, base_path="...", fmt="csv")
"""

from functools import reduce

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from ingest_borrowers import run as ingest_borrowers
from ingest_loan_accounts import run as ingest_loan_accounts
from ingest_loan_products import run as ingest_loan_products
from ingest_payments import run as ingest_payments


def run_full_pipeline(
    spark: SparkSession,
    base_path: str,
    fmt: str = "csv",
    write_mode: str = "overwrite",
) -> DataFrame:
    """Execute the complete migration pipeline in dependency order.

    Order:
        1. borrowers       (no dependencies)
        2. loan_products   (no dependencies)
        3. loan_accounts   (depends on borrowers, loan_products for FK)
        4. payments        (depends on loan_accounts for FK)

    Args:
        spark: Active SparkSession.
        base_path: Root path containing per-table subdirectories
                   (CDW_BORR_MSTR/, CDW_LN_PROD/, CDW_LN_ACCT/, CDW_PMT_HIST/).
        fmt: Source file format ("csv" or "parquet").
        write_mode: Delta write mode ("overwrite" or "append").

    Returns:
        Unified bad-value report DataFrame across all tables.
    """
    print("=" * 72)
    print("CDW LEGACY -> DELTA LAKE MIGRATION PIPELINE")
    print("=" * 72)

    reports = []

    # --- Step 1: Borrowers (dimension, no FK deps) ---
    print("\n--- Step 1/4: Ingesting CDW_BORR_MSTR -> borrowers ---")
    reports.append(
        ingest_borrowers(
            spark,
            source_path=f"{base_path}/CDW_BORR_MSTR",
            source_format=fmt,
            write_mode=write_mode,
        )
    )

    # --- Step 2: Loan Products (dimension, no FK deps) ---
    print("\n--- Step 2/4: Ingesting CDW_LN_PROD -> loan_products ---")
    reports.append(
        ingest_loan_products(
            spark,
            source_path=f"{base_path}/CDW_LN_PROD",
            source_format=fmt,
            write_mode=write_mode,
        )
    )

    # --- Step 3: Loan Accounts (fact, depends on borrowers + products) ---
    print("\n--- Step 3/4: Ingesting CDW_LN_ACCT -> loan_accounts ---")
    reports.append(
        ingest_loan_accounts(
            spark,
            source_path=f"{base_path}/CDW_LN_ACCT",
            source_format=fmt,
            write_mode=write_mode,
        )
    )

    # --- Step 4: Payments (fact, depends on loan_accounts) ---
    print("\n--- Step 4/4: Ingesting CDW_PMT_HIST -> payments ---")
    reports.append(
        ingest_payments(
            spark,
            source_path=f"{base_path}/CDW_PMT_HIST",
            source_format=fmt,
            write_mode=write_mode,
        )
    )

    # --- Consolidate bad-value reports ---
    all_bad = reduce(DataFrame.unionByName, reports)
    total_bad = all_bad.count()

    print("\n" + "=" * 72)
    print(f"PIPELINE COMPLETE  |  Total parse issues: {total_bad}")
    print("=" * 72)

    if total_bad > 0:
        print("\nConsolidated bad-value report:")
        all_bad.show(100, truncate=False)

    return all_bad
