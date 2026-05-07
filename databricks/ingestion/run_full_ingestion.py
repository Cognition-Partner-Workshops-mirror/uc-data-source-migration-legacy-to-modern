"""
Orchestrator script that runs the full ingestion pipeline in the correct
dependency order:

    1. borrowers       (no dependencies)
    2. loan_products   (no dependencies)
    3. loan_accounts   (depends on borrowers + loan_products for FK resolution)
    4. payments        (depends on loan_accounts for FK resolution)

Usage (Databricks notebook or spark-submit):
    spark-submit run_full_ingestion.py \
        --base-path /mnt/landing \
        --format csv
"""

import argparse
import json
import sys
from datetime import datetime

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_accounts
import ingest_loan_products
import ingest_payments

PIPELINE_STEPS = [
    {
        "name": "borrowers",
        "module": ingest_borrowers,
        "subfolder": "cdw_borr_mstr",
    },
    {
        "name": "loan_products",
        "module": ingest_loan_products,
        "subfolder": "cdw_ln_prod",
    },
    {
        "name": "loan_accounts",
        "module": ingest_loan_accounts,
        "subfolder": "cdw_ln_acct",
    },
    {
        "name": "payments",
        "module": ingest_payments,
        "subfolder": "cdw_pmt_hist",
    },
]


def run_pipeline(spark, base_path, source_format="csv", write_mode="overwrite"):
    """Execute every ingestion step in order and collect results."""

    results = {}
    overall_success = True
    start_ts = datetime.utcnow()

    print("=" * 70)
    print(f"  FULL INGESTION PIPELINE — started at {start_ts.isoformat()}")
    print(f"  Base path : {base_path}")
    print(f"  Format    : {source_format}")
    print(f"  Write mode: {write_mode}")
    print("=" * 70)

    for step in PIPELINE_STEPS:
        source_path = f"{base_path}/{step['subfolder']}"
        try:
            result = step["module"].run(
                spark,
                source_path=source_path,
                source_format=source_format,
                write_mode=write_mode,
            )
            results[step["name"]] = result
            if result["source_count"] != result["target_count"]:
                overall_success = False
        except Exception as exc:
            print(f"  ERROR [{step['name']}]: {exc}")
            results[step["name"]] = {"error": str(exc)}
            overall_success = False

    end_ts = datetime.utcnow()
    elapsed = (end_ts - start_ts).total_seconds()

    print("=" * 70)
    print("  PIPELINE SUMMARY")
    print("=" * 70)
    for name, res in results.items():
        if "error" in res:
            print(f"  {name:20s}  FAILED  — {res['error']}")
        else:
            match = "OK" if res["source_count"] == res["target_count"] else "MISMATCH"
            print(
                f"  {name:20s}  {match:8s}  "
                f"source={res['source_count']}  target={res['target_count']}"
            )
    print(f"\n  Elapsed: {elapsed:.1f}s")
    print(f"  Overall: {'SUCCESS' if overall_success else 'FAILURE'}")
    print("=" * 70)

    return results, overall_success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run full CDW migration pipeline")
    parser.add_argument(
        "--base-path",
        default="/mnt/landing",
        help="Base path containing subfolders for each legacy table export",
    )
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_FullIngestion").getOrCreate()

    results, success = run_pipeline(spark, args.base_path, args.format, args.mode)

    # Write results JSON for downstream quality checks
    with open("/tmp/ingestion_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    if not success:
        sys.exit(1)
