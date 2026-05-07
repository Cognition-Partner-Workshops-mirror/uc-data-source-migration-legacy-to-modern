"""
Orchestrator: runs the complete CDW legacy-to-modern ingestion pipeline.

Execution order (respects FK dependencies):
  1. borrowers      (no dependencies)
  2. loan_products  (no dependencies)
  3. loan_accounts  (depends on borrowers + loan_products)
  4. payments       (depends on loan_accounts)

Usage:
    spark-submit run_full_pipeline.py \
        --base-path dbfs:/mnt/legacy \
        --format csv

Or run as a Databricks notebook cell:
    %run ./run_full_pipeline
"""

import argparse
import logging
import sys
import time

from pyspark.sql import SparkSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("cdw_migration.pipeline")


def run_pipeline(spark: SparkSession, base_path: str, source_format: str = "csv"):
    """
    Execute the full migration pipeline in dependency order.

    Parameters
    ----------
    spark : SparkSession
    base_path : str
        Base directory containing legacy export files.
        Expected files:
          {base_path}/CDW_BORR_MSTR.{csv|parquet}
          {base_path}/CDW_LN_PROD.{csv|parquet}
          {base_path}/CDW_LN_ACCT.{csv|parquet}
          {base_path}/CDW_PMT_HIST.{csv|parquet}
    source_format : str
        'csv' or 'parquet'.
    """
    ext = source_format
    results = {}
    pipeline_start = time.time()

    # ------------------------------------------------------------------
    # Step 1: Borrowers (independent)
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 1/4: Ingesting borrowers")
    logger.info("=" * 60)
    from ingest_borrowers import ingest_borrowers
    results["borrowers"] = ingest_borrowers(
        spark, f"{base_path}/CDW_BORR_MSTR.{ext}", source_format
    )

    # ------------------------------------------------------------------
    # Step 2: Loan Products (independent)
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 2/4: Ingesting loan products")
    logger.info("=" * 60)
    from ingest_loan_products import ingest_loan_products
    results["loan_products"] = ingest_loan_products(
        spark, f"{base_path}/CDW_LN_PROD.{ext}", source_format
    )

    # ------------------------------------------------------------------
    # Step 3: Loan Accounts (depends on borrowers + products)
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 3/4: Ingesting loan accounts")
    logger.info("=" * 60)
    from ingest_loan_accounts import ingest_loan_accounts
    results["loan_accounts"] = ingest_loan_accounts(
        spark, f"{base_path}/CDW_LN_ACCT.{ext}", source_format
    )

    # ------------------------------------------------------------------
    # Step 4: Payments (depends on loan accounts)
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 4/4: Ingesting payments")
    logger.info("=" * 60)
    from ingest_payments import ingest_payments
    results["payments"] = ingest_payments(
        spark, f"{base_path}/CDW_PMT_HIST.{ext}", source_format
    )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed = time.time() - pipeline_start
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE in %.1f seconds", elapsed)
    logger.info("=" * 60)

    all_reconciled = True
    for table_name, result in results.items():
        status = "PASS" if result["reconciled"] else "FAIL"
        all_reconciled = all_reconciled and result["reconciled"]
        logger.info(
            "  %-20s src=%d  tgt=%d  quarantine=%d  [%s]",
            table_name,
            result["source_count"],
            result["target_count"],
            result["quarantine_count"],
            status,
        )

    logger.info("Overall reconciliation: %s", "PASS" if all_reconciled else "FAIL")
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CDW Legacy-to-Modern Migration Pipeline")
    parser.add_argument("--base-path", default="dbfs:/mnt/legacy",
                        help="Base path to legacy export files")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"],
                        help="Source file format")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Full_Migration_Pipeline").getOrCreate()

    results = run_pipeline(spark, args.base_path, args.format)

    # Exit with error code if any table failed reconciliation
    if not all(r["reconciled"] for r in results.values()):
        sys.exit(1)
