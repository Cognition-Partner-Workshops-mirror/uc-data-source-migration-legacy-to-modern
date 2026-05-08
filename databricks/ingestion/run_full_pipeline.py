"""
Orchestrator: runs the full legacy → modern ingestion pipeline in dependency order.

Execution order (each step depends on the previous):
  1. borrowers     — no dependencies
  2. loan_products — no dependencies (parallel with borrowers if desired)
  3. loan_accounts — depends on borrowers + loan_products (FK resolution)
  4. payments      — depends on loan_accounts (FK resolution)

Usage:
  Databricks notebook: %run ./run_full_pipeline
  Spark-submit:        spark-submit run_full_pipeline.py
"""

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments


def main() -> None:
    spark = SparkSession.builder.appName("LegacyToModern_FullPipeline").getOrCreate()

    print("=" * 70)
    print("STEP 1/4 — Ingesting borrowers (CDW_BORR_MSTR → borrowers)")
    print("=" * 70)
    ingest_borrowers.main()

    print("=" * 70)
    print("STEP 2/4 — Ingesting loan products (CDW_LN_PROD → loan_products)")
    print("=" * 70)
    ingest_loan_products.main()

    print("=" * 70)
    print("STEP 3/4 — Ingesting loan accounts (CDW_LN_ACCT → loan_accounts)")
    print("=" * 70)
    ingest_loan_accounts.main()

    print("=" * 70)
    print("STEP 4/4 — Ingesting payments (CDW_PMT_HIST → payments)")
    print("=" * 70)
    ingest_payments.main()

    print("=" * 70)
    print("PIPELINE COMPLETE — all four tables ingested.")
    print("=" * 70)

    # Final summary
    for table in ["borrowers", "loan_products", "loan_accounts", "payments"]:
        fqn = f"loan_warehouse.{table}"
        count = spark.table(fqn).count()
        print(f"  {fqn}: {count} rows")


if __name__ == "__main__":
    main()
