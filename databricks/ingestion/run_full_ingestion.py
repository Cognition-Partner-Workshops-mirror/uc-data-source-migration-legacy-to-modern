"""
Orchestrator: Run the full CDW-to-Delta-Lake ingestion pipeline.

Executes ingestion in dependency order:
  1. borrowers     (no dependencies)
  2. loan_products (no dependencies)
  3. loan_accounts (depends on borrowers, loan_products for FK validation)
  4. payments      (depends on loan_accounts for FK validation)

Usage:
    spark-submit run_full_ingestion.py \\
        --landing-dir /mnt/landing \\
        --format csv

Or run as a Databricks notebook:
    %run ./run_full_ingestion
"""

import argparse
import logging
import time

from pyspark.sql import SparkSession

from ingest_borrowers import run as run_borrowers
from ingest_loan_products import run as run_loan_products
from ingest_loan_accounts import run as run_loan_accounts
from ingest_payments import run as run_payments

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_full_ingestion")


STEPS = [
    ("borrowers", "cdw_borr_mstr", run_borrowers),
    ("loan_products", "cdw_ln_prod", run_loan_products),
    ("loan_accounts", "cdw_ln_acct", run_loan_accounts),
    ("payments", "cdw_pmt_hist", run_payments),
]


def main(landing_dir: str, source_format: str) -> None:
    spark = SparkSession.builder.appName("CDW_Full_Ingestion").getOrCreate()

    overall_start = time.time()
    results = []

    for table_name, source_name, run_fn in STEPS:
        source_path = f"{landing_dir}/{source_name}"
        logger.info("=" * 60)
        logger.info("Starting ingestion: %s from %s", table_name, source_path)
        logger.info("=" * 60)

        step_start = time.time()
        try:
            run_fn(source_path=source_path, source_format=source_format)
            elapsed = time.time() - step_start
            results.append((table_name, "SUCCESS", f"{elapsed:.1f}s"))
            logger.info("Completed %s in %.1f seconds", table_name, elapsed)
        except Exception as e:
            elapsed = time.time() - step_start
            results.append((table_name, "FAILED", str(e)))
            logger.error("FAILED %s after %.1f seconds: %s", table_name, elapsed, e)
            raise

    overall_elapsed = time.time() - overall_start
    logger.info("=" * 60)
    logger.info("FULL INGESTION COMPLETE in %.1f seconds", overall_elapsed)
    logger.info("=" * 60)

    summary_df = spark.createDataFrame(results, ["table", "status", "detail"])
    summary_df.show(truncate=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run full CDW ingestion pipeline")
    parser.add_argument(
        "--landing-dir",
        default="/mnt/landing",
        help="Base directory containing source files",
    )
    parser.add_argument(
        "--format",
        default="csv",
        choices=["csv", "parquet", "json"],
        help="Source file format",
    )
    args = parser.parse_args()
    main(landing_dir=args.landing_dir, source_format=args.format)
