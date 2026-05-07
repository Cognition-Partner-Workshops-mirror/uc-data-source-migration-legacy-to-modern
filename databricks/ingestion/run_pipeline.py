"""
Master pipeline orchestrator for the CDW legacy-to-modern migration.

Runs all ingestion scripts in dependency order:
  1. borrowers       (no dependencies)
  2. loan_products   (no dependencies)
  3. loan_accounts   (depends on borrowers and loan_products for FK resolution)
  4. payments        (depends on loan_accounts for FK resolution)

Usage (Databricks notebook):
    %run ./run_pipeline

Usage (spark-submit):
    spark-submit run_pipeline.py
"""

import json
import sys
from datetime import datetime

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments


def run_pipeline() -> list[dict]:
    """Execute the full ingestion pipeline in order."""
    spark = SparkSession.builder.appName("CDW_Migration_Pipeline").getOrCreate()

    # Ensure target database exists
    spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")

    pipeline_start = datetime.now()
    all_stats = []
    errors = []

    steps = [
        ("1/4 Borrowers", ingest_borrowers),
        ("2/4 Loan Products", ingest_loan_products),
        ("3/4 Loan Accounts", ingest_loan_accounts),
        ("4/4 Payments", ingest_payments),
    ]

    for label, module in steps:
        print(f"\n{'='*60}")
        print(f"  Step {label}")
        print(f"{'='*60}")
        try:
            stats = module.run(spark)
            stats["status"] = "SUCCESS"
            all_stats.append(stats)
        except Exception as e:
            error_info = {
                "table": label,
                "status": "FAILED",
                "error": str(e),
            }
            all_stats.append(error_info)
            errors.append(error_info)
            print(f"ERROR in {label}: {e}")
            # Continue with next step; don't fail the entire pipeline

    pipeline_end = datetime.now()
    duration = (pipeline_end - pipeline_start).total_seconds()

    # Print summary
    print(f"\n{'='*60}")
    print(f"  PIPELINE SUMMARY")
    print(f"{'='*60}")
    print(f"Duration:  {duration:.1f}s")
    print(f"Steps:     {len(steps)}")
    print(f"Succeeded: {len(steps) - len(errors)}")
    print(f"Failed:    {len(errors)}")
    print()

    for s in all_stats:
        status_icon = "OK" if s["status"] == "SUCCESS" else "FAIL"
        table = s.get("table", "unknown")
        src = s.get("source_count", "?")
        tgt = s.get("target_count", "?")
        q = s.get("quarantine_count", "?")
        print(f"  [{status_icon}] {table:20s}  src={src}  tgt={tgt}  quarantine={q}")

    if errors:
        print(f"\nWARNING: {len(errors)} step(s) failed. Review errors above.")
        sys.exit(1)

    print("\nAll steps completed successfully.")
    return all_stats


if __name__ == "__main__":
    run_pipeline()
