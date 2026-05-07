"""
Orchestrator: Full CDW-to-Delta-Lake ingestion pipeline.

Runs all four ingestion scripts in dependency order:
  1. borrowers     (no dependencies)
  2. loan_products (no dependencies)
  3. loan_accounts (depends on borrowers and loan_products for FK references)
  4. payments      (depends on loan_accounts for FK references)

Usage:
    spark-submit run_full_ingestion.py \
        --borrowers   /mnt/legacy/CDW_BORR_MSTR.csv \
        --products    /mnt/legacy/CDW_LN_PROD.csv \
        --accounts    /mnt/legacy/CDW_LN_ACCT.csv \
        --payments    /mnt/legacy/CDW_PMT_HIST.csv \
        --format      csv
"""

import argparse
import sys
import time

from pyspark.sql import SparkSession

from common import logger
from ingest_borrowers import run as run_borrowers
from ingest_loan_products import run as run_loan_products
from ingest_loan_accounts import run as run_loan_accounts
from ingest_payments import run as run_payments


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full CDW-to-Delta-Lake migration pipeline")
    parser.add_argument("--borrowers", required=True, help="Path to CDW_BORR_MSTR source file")
    parser.add_argument("--products", required=True, help="Path to CDW_LN_PROD source file")
    parser.add_argument("--accounts", required=True, help="Path to CDW_LN_ACCT source file")
    parser.add_argument("--payments", required=True, help="Path to CDW_PMT_HIST source file")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_Full").getOrCreate()

    pipeline_start = time.time()
    steps = [
        ("borrowers", run_borrowers, args.borrowers),
        ("loan_products", run_loan_products, args.products),
        ("loan_accounts", run_loan_accounts, args.accounts),
        ("payments", run_payments, args.payments),
    ]

    results = {}
    for step_name, step_fn, source_path in steps:
        logger.info("=" * 60)
        logger.info("STARTING STEP: %s", step_name)
        logger.info("=" * 60)
        step_start = time.time()
        try:
            step_fn(spark, source_path, args.format)
            elapsed = time.time() - step_start
            results[step_name] = {"status": "SUCCESS", "elapsed_s": round(elapsed, 2)}
            logger.info("COMPLETED STEP: %s in %.2fs", step_name, elapsed)
        except Exception as exc:
            elapsed = time.time() - step_start
            results[step_name] = {"status": "FAILED", "elapsed_s": round(elapsed, 2), "error": str(exc)}
            logger.exception("FAILED STEP: %s after %.2fs", step_name, elapsed)

    total_elapsed = time.time() - pipeline_start

    # Print summary
    logger.info("=" * 60)
    logger.info("PIPELINE SUMMARY (total: %.2fs)", total_elapsed)
    logger.info("=" * 60)
    all_passed = True
    for step_name, result in results.items():
        logger.info("  %-20s %s (%.2fs)", step_name, result["status"], result["elapsed_s"])
        if result["status"] != "SUCCESS":
            all_passed = False

    spark.stop()

    if not all_passed:
        logger.error("Pipeline completed with failures. Review logs above.")
        sys.exit(1)
    else:
        logger.info("Pipeline completed successfully.")


if __name__ == "__main__":
    main()
