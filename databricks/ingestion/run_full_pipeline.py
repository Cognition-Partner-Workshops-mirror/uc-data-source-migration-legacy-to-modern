"""
Master orchestration script for the full legacy-to-modern migration pipeline.

Execution order:
  1. borrowers       (no dependencies)
  2. loan_products   (no dependencies)
  3. loan_accounts   (depends on borrowers + loan_products for FK resolution)
  4. payments        (depends on loan_accounts for FK resolution)

Usage:
    spark-submit run_full_pipeline.py
    or run as a Databricks notebook cell: %run ./run_full_pipeline
"""

import sys
import time
from datetime import datetime

from pyspark.sql import SparkSession

from ingest_borrowers import run_borrower_ingestion
from ingest_loan_products import run_product_ingestion
from ingest_loan_accounts import run_account_ingestion
from ingest_payments import run_payment_ingestion


def run_full_pipeline(spark: SparkSession) -> dict:
    """Run the complete migration pipeline in dependency order."""
    pipeline_start = time.time()
    all_stats = {}

    print("=" * 70)
    print(f"FULL MIGRATION PIPELINE — Started at {datetime.utcnow().isoformat()}")
    print("=" * 70)

    # Step 1: Borrowers (no FK dependencies)
    print("\n>>> Step 1/4: Borrowers")
    try:
        all_stats["borrowers"] = run_borrower_ingestion(spark)
    except Exception as e:
        print(f"FATAL: Borrower ingestion failed: {e}")
        all_stats["borrowers"] = {"error": str(e)}
        print("Cannot proceed — loan_accounts depends on borrowers.")
        _print_summary(all_stats, pipeline_start)
        sys.exit(1)

    # Step 2: Loan Products (no FK dependencies)
    print("\n>>> Step 2/4: Loan Products")
    try:
        all_stats["loan_products"] = run_product_ingestion(spark)
    except Exception as e:
        print(f"FATAL: Loan product ingestion failed: {e}")
        all_stats["loan_products"] = {"error": str(e)}
        print("Cannot proceed — loan_accounts depends on loan_products.")
        _print_summary(all_stats, pipeline_start)
        sys.exit(1)

    # Step 3: Loan Accounts (depends on borrowers + loan_products)
    print("\n>>> Step 3/4: Loan Accounts")
    try:
        all_stats["loan_accounts"] = run_account_ingestion(spark)
    except Exception as e:
        print(f"FATAL: Loan account ingestion failed: {e}")
        all_stats["loan_accounts"] = {"error": str(e)}
        print("Cannot proceed — payments depends on loan_accounts.")
        _print_summary(all_stats, pipeline_start)
        sys.exit(1)

    # Step 4: Payments (depends on loan_accounts)
    print("\n>>> Step 4/4: Payments")
    try:
        all_stats["payments"] = run_payment_ingestion(spark)
    except Exception as e:
        print(f"ERROR: Payment ingestion failed: {e}")
        all_stats["payments"] = {"error": str(e)}

    _print_summary(all_stats, pipeline_start)
    return all_stats


def _print_summary(stats: dict, start_time: float) -> None:
    """Print a summary of the full pipeline run."""
    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print("MIGRATION PIPELINE SUMMARY")
    print("=" * 70)
    for table, table_stats in stats.items():
        if "error" in table_stats:
            print(f"  {table:20s}  FAILED — {table_stats['error']}")
        else:
            src = table_stats.get("source_count", "?")
            tgt = table_stats.get("target_count", "?")
            qua = table_stats.get("quarantined_count", 0)
            match = "OK" if src == tgt + qua else "MISMATCH"
            print(
                f"  {table:20s}  source={src}  target={tgt}  "
                f"quarantined={qua}  [{match}]"
            )
    print(f"\nTotal elapsed time: {elapsed:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_FullPipeline").getOrCreate()
    run_full_pipeline(spark)
