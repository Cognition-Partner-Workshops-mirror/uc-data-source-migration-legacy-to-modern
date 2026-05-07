"""
Full migration pipeline orchestrator.

Runs all ingestion scripts in the correct dependency order:
  1. borrowers (no dependencies)
  2. loan_products (no dependencies)
  3. loan_accounts (depends on borrowers, loan_products)
  4. payments (depends on loan_accounts)

Usage (Databricks notebook):
    %run ./run_full_pipeline
"""

import time
from pyspark.sql import SparkSession

from ingest_borrowers import run as run_borrowers
from ingest_loan_products import run as run_loan_products
from ingest_loan_accounts import run as run_loan_accounts
from ingest_payments import run as run_payments


def run_full_pipeline():
    spark = SparkSession.builder.appName("LegacyCDW_FullMigration").getOrCreate()

    start = time.time()
    print("=" * 70)
    print("LEGACY CDW → DELTA LAKE MIGRATION PIPELINE")
    print("=" * 70)

    # Phase 1: Dimension tables (no FK dependencies)
    print("\n--- Phase 1: Dimension Tables ---")
    print("[1/4] Ingesting borrowers...")
    run_borrowers(spark)

    print("[2/4] Ingesting loan products...")
    run_loan_products(spark)

    # Phase 2: Fact tables (depend on dimension tables)
    print("\n--- Phase 2: Fact Tables ---")
    print("[3/4] Ingesting loan accounts...")
    run_loan_accounts(spark)

    print("[4/4] Ingesting payments...")
    run_payments(spark)

    elapsed = time.time() - start
    print("\n" + "=" * 70)
    print(f"PIPELINE COMPLETE — {elapsed:.1f}s elapsed")
    print("=" * 70)

    # Summary counts
    for table in [
        "loan_warehouse.borrowers",
        "loan_warehouse.loan_products",
        "loan_warehouse.loan_accounts",
        "loan_warehouse.payments",
    ]:
        count = spark.table(table).count()
        print(f"  {table}: {count} rows")


if __name__ == "__main__":
    run_full_pipeline()
