"""
Orchestrator: runs all four ingestion scripts in dependency order.

Execution order (dependencies flow downward):
  1. borrowers       (no dependencies)
  2. loan_products   (no dependencies)
  3. loan_accounts   (depends on borrowers + loan_products for FK resolution)
  4. payments        (depends on loan_accounts for FK resolution)

Usage (Databricks notebook):
    %run ./run_ingestion

Usage (command line / Databricks job):
    spark-submit --py-files databricks.zip databricks/ingestion/run_ingestion.py \
        --source-dir /mnt/legacy --format csv
"""

import argparse
import json
import logging
from datetime import datetime

from pyspark.sql import SparkSession

from databricks.ingestion import (
    ingest_borrowers,
    ingest_loan_accounts,
    ingest_loan_products,
    ingest_payments,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("loan_migration.orchestrator")


def run_all(
    spark: SparkSession,
    source_dir: str = "/mnt/legacy",
    fmt: str = "csv",
) -> list[dict]:
    """
    Execute all ingestion scripts in dependency order.
    Returns a list of summary dicts from each step.
    """
    start_time = datetime.utcnow()
    results = []

    # ── Step 1 & 2: dimension tables (independent, could be parallelized) ──
    logger.info("=" * 60)
    logger.info("STEP 1/4: Ingesting borrowers")
    logger.info("=" * 60)
    results.append(ingest_borrowers.run(
        spark, source_path=f"{source_dir}/CDW_BORR_MSTR", fmt=fmt,
    ))

    logger.info("=" * 60)
    logger.info("STEP 2/4: Ingesting loan_products")
    logger.info("=" * 60)
    results.append(ingest_loan_products.run(
        spark, source_path=f"{source_dir}/CDW_LN_PROD", fmt=fmt,
    ))

    # ── Step 3: loan_accounts (needs borrowers + products for FK lookup) ──
    logger.info("=" * 60)
    logger.info("STEP 3/4: Ingesting loan_accounts")
    logger.info("=" * 60)
    results.append(ingest_loan_accounts.run(
        spark, source_path=f"{source_dir}/CDW_LN_ACCT", fmt=fmt,
    ))

    # ── Step 4: payments (needs loan_accounts for FK lookup) ──
    logger.info("=" * 60)
    logger.info("STEP 4/4: Ingesting payments")
    logger.info("=" * 60)
    results.append(ingest_payments.run(
        spark, source_path=f"{source_dir}/CDW_PMT_HIST", fmt=fmt,
    ))

    elapsed = (datetime.utcnow() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info("ALL INGESTION COMPLETE in %.1f seconds", elapsed)
    logger.info("=" * 60)
    for r in results:
        logger.info(
            "  %-20s  src=%d  tgt=%d  issues=%d",
            r["table"], r["source_count"], r["target_count"],
            r["records_with_quality_issues"],
        )

    return results


def main():
    parser = argparse.ArgumentParser(description="Run loan data migration ingestion")
    parser.add_argument("--source-dir", default="/mnt/legacy", help="Path to legacy source files")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("LoanMigration_Ingestion").getOrCreate()

    results = run_all(spark, source_dir=args.source_dir, fmt=args.format)

    print("\n" + json.dumps(results, indent=2))
    spark.stop()


if __name__ == "__main__":
    main()
