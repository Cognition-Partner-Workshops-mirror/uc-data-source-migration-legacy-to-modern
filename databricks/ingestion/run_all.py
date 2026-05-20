"""
run_all.py — Orchestrator script for the full legacy CDW → Delta Lake migration.

Executes the ingestion scripts in the correct dependency order:
  1. borrowers     (no dependencies — dimension table)
  2. loan_products (no dependencies — dimension table)
  3. loan_accounts (depends on borrowers and loan_products for FK resolution)
  4. payments      (depends on loan_accounts for FK resolution)

Each step logs row counts and parse errors. The orchestrator collects results
into a summary report for reconciliation.

Usage:
  - Databricks notebook: %run ./run_all
  - spark-submit: spark-submit run_all.py
"""

import sys
import traceback
from datetime import datetime

from pyspark.sql import SparkSession

# Import the individual ingestion modules
import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments


def run_full_migration():
    """
    Execute the full migration pipeline in dependency order.
    Returns a dict of per-table results for downstream quality checks.
    """
    spark = SparkSession.builder.appName("LoanMigrationPipeline").getOrCreate()

    start_time = datetime.now()
    results = {}
    failed_steps = []

    # Define the execution order with dependencies noted
    steps = [
        ("borrowers", ingest_borrowers, "No dependencies — base dimension table"),
        ("loan_products", ingest_loan_products, "No dependencies — reference table"),
        ("loan_accounts", ingest_loan_accounts, "Depends on borrowers, loan_products"),
        ("payments", ingest_payments, "Depends on loan_accounts"),
    ]

    print("=" * 70)
    print(f"LOAN MANAGEMENT MIGRATION PIPELINE — Started at {start_time}")
    print("=" * 70)

    for table_name, module, dependency_note in steps:
        step_start = datetime.now()
        print(f"\n{'─' * 70}")
        print(f"Step: {table_name} ({dependency_note})")
        print(f"{'─' * 70}")

        try:
            # Run the ingestion module, passing the shared SparkSession
            result = module.run(spark=spark)
            results[table_name] = result
            elapsed = (datetime.now() - step_start).total_seconds()
            print(f"Completed {table_name} in {elapsed:.1f}s — "
                  f"source={result['source_count']}, target={result['target_count']}, "
                  f"errors={result['error_count']}")

        except Exception as e:
            # Log the failure but continue with remaining steps so that
            # independent tables are still ingested
            elapsed = (datetime.now() - step_start).total_seconds()
            error_msg = f"FAILED {table_name} after {elapsed:.1f}s: {str(e)}"
            print(error_msg)
            traceback.print_exc()
            failed_steps.append(table_name)
            results[table_name] = {
                "source_count": -1,
                "target_count": -1,
                "error_count": -1,
                "failure_reason": str(e),
            }

    # Print final summary
    end_time = datetime.now()
    total_elapsed = (end_time - start_time).total_seconds()

    print(f"\n{'=' * 70}")
    print(f"MIGRATION PIPELINE SUMMARY")
    print(f"{'=' * 70}")
    print(f"Started:  {start_time}")
    print(f"Finished: {end_time}")
    print(f"Duration: {total_elapsed:.1f}s")
    print(f"{'─' * 70}")

    for table_name, result in results.items():
        status = "FAILED" if table_name in failed_steps else "OK"
        src = result.get("source_count", "N/A")
        tgt = result.get("target_count", "N/A")
        errs = result.get("error_count", "N/A")
        print(f"  {table_name:20s}  {status:8s}  source={src}  target={tgt}  errors={errs}")

    print(f"{'─' * 70}")

    if failed_steps:
        print(f"WARNING: {len(failed_steps)} step(s) failed: {', '.join(failed_steps)}")
        print("Review the error logs above and re-run failed steps after fixing.")
    else:
        print("All steps completed successfully.")

    print(f"{'=' * 70}\n")

    return results


if __name__ == "__main__":
    results = run_full_migration()

    # Exit with non-zero code if any step failed
    failed = [k for k, v in results.items() if v.get("source_count", -1) == -1]
    if failed:
        sys.exit(1)
