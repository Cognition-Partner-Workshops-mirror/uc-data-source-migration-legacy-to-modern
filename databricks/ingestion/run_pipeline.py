"""
Migration Pipeline Orchestrator

Runs the full ingestion pipeline in dependency order:
  1. borrowers    (no dependencies)
  2. loan_products (no dependencies)
  3. loan_accounts (depends on borrowers + loan_products for RI checks)
  4. payments      (depends on loan_accounts for RI checks)

Usage (Databricks notebook):
    %run ./run_pipeline
"""

import sys
import traceback
from datetime import datetime

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments


def run_full_pipeline(spark: SparkSession):
    """Execute all ingestion steps in order, collecting results."""
    results = {}
    steps = [
        ("borrowers", ingest_borrowers),
        ("loan_products", ingest_loan_products),
        ("loan_accounts", ingest_loan_accounts),
        ("payments", ingest_payments),
    ]

    start_time = datetime.now()
    print("#" * 70)
    print(f"# MIGRATION PIPELINE STARTED AT {start_time.isoformat()}")
    print("#" * 70)

    failed_steps = []

    for step_name, module in steps:
        step_start = datetime.now()
        print(f"\n>>> Step: {step_name} (started {step_start.isoformat()})")
        try:
            result = module.run(spark)
            results[step_name] = {"status": "SUCCESS", "metrics": result}
            elapsed = (datetime.now() - step_start).total_seconds()
            print(f">>> Step: {step_name} completed in {elapsed:.1f}s")
        except Exception as e:
            elapsed = (datetime.now() - step_start).total_seconds()
            error_msg = traceback.format_exc()
            results[step_name] = {"status": "FAILED", "error": str(e)}
            failed_steps.append(step_name)
            print(f"[ERROR] Step {step_name} FAILED after {elapsed:.1f}s: {e}")
            print(error_msg)
            # Continue with remaining steps if possible
            if step_name in ("borrowers", "loan_products"):
                print(
                    f"[WARN] Continuing pipeline despite {step_name} failure. "
                    "Downstream RI checks may report orphaned references."
                )
            else:
                print(f"[WARN] Continuing pipeline despite {step_name} failure.")

    end_time = datetime.now()
    total_elapsed = (end_time - start_time).total_seconds()

    print("\n" + "#" * 70)
    print(f"# MIGRATION PIPELINE COMPLETED AT {end_time.isoformat()}")
    print(f"# Total elapsed: {total_elapsed:.1f}s")
    print("#" * 70)

    print("\n--- PIPELINE SUMMARY ---")
    for step_name, result in results.items():
        status = result["status"]
        if status == "SUCCESS":
            m = result["metrics"]
            print(
                f"  {step_name}: {status} "
                f"(source={m['source_count']}, clean={m['clean_count']}, target={m['target_count']})"
            )
        else:
            print(f"  {step_name}: {status} ({result['error']})")

    if failed_steps:
        print(f"\n[ERROR] {len(failed_steps)} step(s) failed: {', '.join(failed_steps)}")
        sys.exit(1)
    else:
        print("\n[INFO] All steps completed successfully.")

    return results


# Entry point
# spark = SparkSession.builder.getOrCreate()
# run_full_pipeline(spark)
