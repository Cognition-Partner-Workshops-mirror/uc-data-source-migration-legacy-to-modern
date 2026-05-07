"""
Full ingestion orchestrator for CDW legacy-to-Delta Lake migration.

Runs all per-table ingestion scripts in dependency order:
  1. borrowers       (dimension — no dependencies)
  2. loan_products   (reference — no dependencies)
  3. loan_accounts   (depends on borrowers, loan_products)
  4. payments        (depends on loan_accounts)

Usage:
    spark-submit run_full_ingestion.py [--base-path /mnt/landing/cdw]
                                       [--database loan_warehouse]
"""

import argparse
import sys
import time

from pyspark.sql import SparkSession

from ingest_borrowers import ingest_borrowers
from ingest_loan_accounts import ingest_loan_accounts
from ingest_loan_products import ingest_loan_products
from ingest_payments import ingest_payments

TABLES = [
    {
        "name": "borrowers",
        "source": "CDW_BORR_MSTR",
        "target": "borrowers",
        "func": ingest_borrowers,
    },
    {
        "name": "loan_products",
        "source": "CDW_LN_PROD",
        "target": "loan_products",
        "func": ingest_loan_products,
    },
    {
        "name": "loan_accounts",
        "source": "CDW_LN_ACCT",
        "target": "loan_accounts",
        "func": ingest_loan_accounts,
    },
    {
        "name": "payments",
        "source": "CDW_PMT_HIST",
        "target": "payments",
        "func": ingest_payments,
    },
]


def run_full_ingestion(base_path: str, database: str) -> None:
    """Execute all ingestion scripts in dependency order."""

    spark = SparkSession.builder.appName(
        "CDW_Migration_FullIngestion"
    ).getOrCreate()

    print("=" * 70)
    print("CDW Legacy-to-Delta Lake Full Ingestion")
    print(f"  Base path : {base_path}")
    print(f"  Database  : {database}")
    print("=" * 70)

    results = []
    overall_start = time.time()

    for table in TABLES:
        input_path = f"{base_path}/{table['source']}"
        output_table = f"{database}.{table['target']}"
        print(f"\n--- Ingesting {table['name']} ---")
        start = time.time()
        try:
            table["func"](spark, input_path, output_table)
            elapsed = time.time() - start
            results.append(
                {"table": table["name"], "status": "SUCCESS", "time": elapsed}
            )
            print(f"  Completed in {elapsed:.1f}s")
        except Exception as exc:
            elapsed = time.time() - start
            results.append(
                {"table": table["name"], "status": "FAILED", "time": elapsed}
            )
            print(f"  FAILED after {elapsed:.1f}s: {exc}")
            # Continue with remaining tables to maximize data loaded
            continue

    overall_elapsed = time.time() - overall_start

    print("\n" + "=" * 70)
    print("Ingestion Summary")
    print("=" * 70)
    for r in results:
        print(f"  {r['table']:20s} {r['status']:10s} {r['time']:.1f}s")
    print(f"\nTotal elapsed: {overall_elapsed:.1f}s")

    failed = [r for r in results if r["status"] == "FAILED"]
    if failed:
        print(f"\nWARNING: {len(failed)} table(s) failed ingestion.")
        sys.exit(1)
    else:
        print("\nAll tables ingested successfully.")

    spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run full CDW-to-Delta Lake ingestion pipeline"
    )
    parser.add_argument(
        "--base-path",
        default="/mnt/landing/cdw",
        help="Base path to landing zone CSV/Parquet files",
    )
    parser.add_argument(
        "--database",
        default="loan_warehouse",
        help="Target Databricks database name",
    )
    args = parser.parse_args()

    run_full_ingestion(args.base_path, args.database)
