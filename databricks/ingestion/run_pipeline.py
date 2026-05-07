"""
Orchestrator: run the full legacy → modern ingestion pipeline in the correct
dependency order.

Execution order (respects FK dependencies):
  1. borrowers       (no dependencies)
  2. loan_products   (no dependencies)
  3. loan_accounts   (depends on borrowers + loan_products)
  4. payments        (depends on loan_accounts)

Usage (Databricks notebook or spark-submit):
    %run ./run_pipeline          # Databricks notebook magic
    spark-submit run_pipeline.py # Cluster mode
"""

import json
import sys
from datetime import datetime

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments


def run_full_pipeline(spark: SparkSession) -> list[dict]:
    """Execute all four ingestion jobs in order. Returns per-table stats."""
    results = []
    pipeline_start = datetime.utcnow()

    print("=" * 72)
    print("LEGACY CDW → MODERN DELTA LAKE MIGRATION PIPELINE")
    print(f"Started at: {pipeline_start.isoformat()}Z")
    print("=" * 72)

    # Step 1 — Borrowers (dimension, no FK deps)
    print("\n>>> Step 1/4: Ingesting CDW_BORR_MSTR → borrowers")
    results.append(ingest_borrowers.run(spark))

    # Step 2 — Loan Products (dimension, no FK deps)
    print("\n>>> Step 2/4: Ingesting CDW_LN_PROD → loan_products")
    results.append(ingest_loan_products.run(spark))

    # Step 3 — Loan Accounts (depends on borrowers + loan_products)
    print("\n>>> Step 3/4: Ingesting CDW_LN_ACCT → loan_accounts")
    results.append(ingest_loan_accounts.run(spark))

    # Step 4 — Payments (depends on loan_accounts)
    print("\n>>> Step 4/4: Ingesting CDW_PMT_HIST → payments")
    results.append(ingest_payments.run(spark))

    pipeline_end = datetime.utcnow()
    elapsed = (pipeline_end - pipeline_start).total_seconds()

    print("\n" + "=" * 72)
    print("PIPELINE SUMMARY")
    print("=" * 72)
    total_source = sum(r["source_count"] for r in results)
    total_target = sum(r["target_count"] for r in results)
    total_quarantine = sum(r["quarantine_count"] for r in results)

    for r in results:
        status = "OK" if r["quarantine_count"] == 0 else "WARN"
        print(f"  [{status}] {r['table']}: "
              f"{r['source_count']} source → "
              f"{r['target_count']} target, "
              f"{r['quarantine_count']} quarantined")

    print(f"\n  Totals: {total_source} source → {total_target} target, "
          f"{total_quarantine} quarantined")
    print(f"  Elapsed: {elapsed:.1f}s")
    print("=" * 72)

    return results


if __name__ == "__main__":
    spark = (
        SparkSession.builder
        .appName("CDW Legacy → Modern Delta Lake Migration Pipeline")
        .getOrCreate()
    )

    results = run_full_pipeline(spark)

    # Non-zero exit if any rows were quarantined (useful for CI/alerting)
    total_quarantine = sum(r["quarantine_count"] for r in results)
    if total_quarantine > 0:
        print(f"\nWARNING: {total_quarantine} total record(s) quarantined. "
              "Review _quarantine_* tables before promoting to production.")
        sys.exit(1)
