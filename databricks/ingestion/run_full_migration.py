"""
Orchestrator: Full Legacy-to-Modern Migration Pipeline

Runs all ingestion scripts in dependency order:
  1. borrowers       (no dependencies)
  2. loan_products   (no dependencies)
  3. loan_accounts   (depends on borrowers, loan_products)
  4. payments        (depends on loan_accounts)

Usage:
  spark-submit --py-files utils.py run_full_migration.py

Or run as a Databricks notebook cell by importing and calling main().
"""

import sys
import time
from datetime import datetime

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_accounts
import ingest_loan_products
import ingest_payments


def main():
    spark = SparkSession.builder.appName("LoanMigration_FullPipeline").getOrCreate()

    migration_start = datetime.now()
    print("=" * 70)
    print(f"[MIGRATION] Full pipeline started at {migration_start.isoformat()}")
    print("=" * 70)

    all_stats = []
    steps = [
        ("1/4 — Borrowers", ingest_borrowers.run),
        ("2/4 — Loan Products", ingest_loan_products.run),
        ("3/4 — Loan Accounts", ingest_loan_accounts.run),
        ("4/4 — Payments", ingest_payments.run),
    ]

    for step_label, run_fn in steps:
        print(f"\n{'='*70}")
        print(f"[MIGRATION] Step {step_label}")
        print(f"{'='*70}")
        step_start = time.time()
        try:
            stats = run_fn(spark)
            all_stats.append(stats)
            elapsed = time.time() - step_start
            print(f"[MIGRATION] Step {step_label} completed in {elapsed:.1f}s")
        except Exception as e:
            print(f"[MIGRATION] FATAL: Step {step_label} failed: {e}")
            print(f"[MIGRATION] Pipeline halted. Fix the issue and re-run from this step.")
            raise

    migration_end = datetime.now()
    elapsed_total = (migration_end - migration_start).total_seconds()

    print(f"\n{'='*70}")
    print(f"[MIGRATION] Full pipeline completed at {migration_end.isoformat()}")
    print(f"[MIGRATION] Total elapsed: {elapsed_total:.1f}s")
    print(f"{'='*70}")

    # Summary
    print("\n[MIGRATION] ===== RECONCILIATION SUMMARY =====")
    all_reconciled = True
    for stat in all_stats:
        status_icon = "OK" if stat["is_reconciled"] else "MISMATCH"
        print(f"  [{status_icon}] {stat['table']}: "
              f"source={stat['source_rows']}, target={stat['target_rows']}, "
              f"quarantined={stat['quarantined_rows']}")
        if not stat["is_reconciled"]:
            all_reconciled = False

    if all_reconciled:
        print("\n[MIGRATION] All tables reconciled successfully.")
    else:
        print("\n[MIGRATION] WARNING: Some tables have row count mismatches. "
              "Review quarantine tables and logs.")

    spark.stop()
    return all_stats


if __name__ == "__main__":
    main()
