"""
Orchestrator script: runs the full legacy CDW → Delta Lake ingestion pipeline.

Execution order (dimension tables first, then fact tables):
  1. borrowers       (CDW_BORR_MSTR — no dependencies)
  2. loan_products   (CDW_LN_PROD — no dependencies)
  3. loan_accounts   (CDW_LN_ACCT — depends on borrowers + loan_products for FK)
  4. payments        (CDW_PMT_HIST — depends on loan_accounts for FK)

Each step logs row counts and quarantine stats. The pipeline fails fast on
unrecoverable errors but continues through data-quality issues (routing bad
records to the quarantine table).

Usage in Databricks:
  - Run this notebook/script directly, or call run_full_pipeline() from a
    Databricks Workflow / Job.
  - Adjust SOURCE_PATHS in config.py to point to your legacy export location.
"""

import logging
import sys
from datetime import datetime

from pyspark.sql import SparkSession

from ingest_borrowers import ingest_borrowers
from ingest_loan_products import ingest_loan_products
from ingest_loan_accounts import ingest_loan_accounts
from ingest_payments import ingest_payments
from config import TARGET_DATABASE

# Configure logging for the pipeline
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("cdw_migration.orchestrator")


def run_full_pipeline(spark: SparkSession, file_format: str = "csv") -> dict:
    """
    Run the complete ingestion pipeline in dependency order.

    Args:
        spark: Active SparkSession
        file_format: Source file format — "csv" or "parquet"

    Returns:
        dict with per-table reconciliation counts and overall status
    """
    pipeline_start = datetime.now()
    logger.info("=" * 70)
    logger.info("CDW → Delta Lake Migration Pipeline — Starting")
    logger.info(f"Target database: {TARGET_DATABASE}")
    logger.info(f"Source format: {file_format}")
    logger.info("=" * 70)

    # Create target database if it doesn't exist
    spark.sql(f"CREATE DATABASE IF NOT EXISTS {TARGET_DATABASE}")

    results = {}
    pipeline_status = "SUCCESS"

    # -------------------------------------------------------------------------
    # Step 1: Ingest borrowers (no dependencies)
    # -------------------------------------------------------------------------
    try:
        logger.info("-" * 50)
        logger.info("Step 1/4: Ingesting borrowers (CDW_BORR_MSTR)")
        logger.info("-" * 50)
        results["borrowers"] = ingest_borrowers(spark, file_format)
    except Exception as e:
        logger.error(f"FATAL: Borrower ingestion failed: {e}", exc_info=True)
        results["borrowers"] = {"error": str(e)}
        pipeline_status = "FAILED"
        # Fail fast — downstream tables depend on borrowers
        raise RuntimeError("Pipeline aborted: borrower ingestion failed") from e

    # -------------------------------------------------------------------------
    # Step 2: Ingest loan products (no dependencies)
    # -------------------------------------------------------------------------
    try:
        logger.info("-" * 50)
        logger.info("Step 2/4: Ingesting loan products (CDW_LN_PROD)")
        logger.info("-" * 50)
        results["loan_products"] = ingest_loan_products(spark, file_format)
    except Exception as e:
        logger.error(f"FATAL: Loan product ingestion failed: {e}", exc_info=True)
        results["loan_products"] = {"error": str(e)}
        pipeline_status = "FAILED"
        raise RuntimeError("Pipeline aborted: loan product ingestion failed") from e

    # -------------------------------------------------------------------------
    # Step 3: Ingest loan accounts (depends on borrowers + loan_products)
    # -------------------------------------------------------------------------
    try:
        logger.info("-" * 50)
        logger.info("Step 3/4: Ingesting loan accounts (CDW_LN_ACCT)")
        logger.info("-" * 50)
        results["loan_accounts"] = ingest_loan_accounts(spark, file_format)
    except Exception as e:
        logger.error(f"FATAL: Loan account ingestion failed: {e}", exc_info=True)
        results["loan_accounts"] = {"error": str(e)}
        pipeline_status = "FAILED"
        raise RuntimeError("Pipeline aborted: loan account ingestion failed") from e

    # -------------------------------------------------------------------------
    # Step 4: Ingest payments (depends on loan_accounts)
    # -------------------------------------------------------------------------
    try:
        logger.info("-" * 50)
        logger.info("Step 4/4: Ingesting payments (CDW_PMT_HIST)")
        logger.info("-" * 50)
        results["payments"] = ingest_payments(spark, file_format)
    except Exception as e:
        logger.error(f"FATAL: Payment ingestion failed: {e}", exc_info=True)
        results["payments"] = {"error": str(e)}
        pipeline_status = "FAILED"
        raise RuntimeError("Pipeline aborted: payment ingestion failed") from e

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    pipeline_end = datetime.now()
    elapsed = (pipeline_end - pipeline_start).total_seconds()

    logger.info("=" * 70)
    logger.info(f"Pipeline Status: {pipeline_status}")
    logger.info(f"Elapsed Time: {elapsed:.1f} seconds")
    logger.info("Per-table results:")
    for table, counts in results.items():
        logger.info(f"  {table}: {counts}")
    logger.info("=" * 70)

    results["_pipeline_status"] = pipeline_status
    results["_elapsed_seconds"] = elapsed
    return results


if __name__ == "__main__":
    spark = SparkSession.builder.appName(
        "CDW_Migration_Full_Pipeline"
    ).enableHiveSupport().getOrCreate()

    try:
        results = run_full_pipeline(spark)
        if results["_pipeline_status"] != "SUCCESS":
            sys.exit(1)
    finally:
        spark.stop()
