"""
Master Pipeline Orchestrator: Runs the full CDW legacy-to-modern migration.

Executes all ingestion scripts in dependency order:
1. Borrowers (no dependencies)
2. Loan Products (no dependencies)
3. Loan Accounts (depends on Borrowers, Loan Products)
4. Payments (depends on Loan Accounts)

Usage (Databricks notebook or job):
    %run ./run_pipeline
    -- or --
    python -m databricks.ingestion.run_pipeline
"""

import logging
import sys
from datetime import datetime

from pyspark.sql import SparkSession

from .ingest_borrowers import ingest_borrowers
from .ingest_loan_accounts import ingest_loan_accounts
from .ingest_loan_products import ingest_loan_products
from .ingest_payments import ingest_payments

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_full_pipeline(spark: SparkSession, config: dict = None) -> dict:
    """
    Execute the complete migration pipeline in dependency order.

    Args:
        spark: Active SparkSession
        config: Optional configuration dict with source paths and target tables.
                If not provided, defaults from Spark conf or hardcoded paths are used.

    Returns:
        Dictionary with overall pipeline metrics and per-table results.
    """
    if config is None:
        config = {}

    pipeline_start = datetime.now()
    results = {}
    overall_status = "SUCCESS"

    # Default configuration
    base_source = config.get("base_source_path", "/mnt/legacy")
    base_rejected = config.get("base_rejected_path", "/mnt/migration/rejected")
    write_mode = config.get("write_mode", "overwrite")

    # -------------------------------------------------------------------------
    # Step 1: Ingest Borrowers
    # -------------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 1: Ingesting Borrowers (CDW_BORR_MSTR)")
    logger.info("=" * 60)
    try:
        results["borrowers"] = ingest_borrowers(
            spark,
            source_path=config.get("borrowers_source", f"{base_source}/cdw_borr_mstr/"),
            target_table=config.get("borrowers_target", "loan_warehouse.borrowers"),
            rejected_path=f"{base_rejected}/borrowers/",
            mode=write_mode,
        )
    except Exception as e:
        logger.error(f"FAILED: Borrower ingestion - {e}")
        results["borrowers"] = {"status": "FAILED", "error": str(e)}
        overall_status = "PARTIAL_FAILURE"

    # -------------------------------------------------------------------------
    # Step 2: Ingest Loan Products
    # -------------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 2: Ingesting Loan Products (CDW_LN_PROD)")
    logger.info("=" * 60)
    try:
        results["loan_products"] = ingest_loan_products(
            spark,
            source_path=config.get("loan_products_source", f"{base_source}/cdw_ln_prod/"),
            target_table=config.get("loan_products_target", "loan_warehouse.loan_products"),
            rejected_path=f"{base_rejected}/loan_products/",
            mode=write_mode,
        )
    except Exception as e:
        logger.error(f"FAILED: Loan products ingestion - {e}")
        results["loan_products"] = {"status": "FAILED", "error": str(e)}
        overall_status = "PARTIAL_FAILURE"

    # -------------------------------------------------------------------------
    # Step 3: Ingest Loan Accounts (depends on Borrowers + Products)
    # -------------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 3: Ingesting Loan Accounts (CDW_LN_ACCT)")
    logger.info("=" * 60)
    if results.get("borrowers", {}).get("status") == "FAILED":
        logger.warning("Skipping loan accounts: borrower ingestion failed (dependency)")
        results["loan_accounts"] = {"status": "SKIPPED", "reason": "Borrower ingestion failed"}
        overall_status = "PARTIAL_FAILURE"
    else:
        try:
            results["loan_accounts"] = ingest_loan_accounts(
                spark,
                source_path=config.get("loan_accounts_source", f"{base_source}/cdw_ln_acct/"),
                target_table=config.get("loan_accounts_target", "loan_warehouse.loan_accounts"),
                rejected_path=f"{base_rejected}/loan_accounts/",
                mode=write_mode,
            )
        except Exception as e:
            logger.error(f"FAILED: Loan accounts ingestion - {e}")
            results["loan_accounts"] = {"status": "FAILED", "error": str(e)}
            overall_status = "PARTIAL_FAILURE"

    # -------------------------------------------------------------------------
    # Step 4: Ingest Payments (depends on Loan Accounts)
    # -------------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 4: Ingesting Payments (CDW_PMT_HIST)")
    logger.info("=" * 60)
    if results.get("loan_accounts", {}).get("status") in ("FAILED", "SKIPPED"):
        logger.warning("Skipping payments: loan accounts ingestion failed/skipped (dependency)")
        results["payments"] = {"status": "SKIPPED", "reason": "Loan accounts ingestion failed/skipped"}
        overall_status = "PARTIAL_FAILURE"
    else:
        try:
            results["payments"] = ingest_payments(
                spark,
                source_path=config.get("payments_source", f"{base_source}/cdw_pmt_hist/"),
                target_table=config.get("payments_target", "loan_warehouse.payments"),
                rejected_path=f"{base_rejected}/payments/",
                mode=write_mode,
            )
        except Exception as e:
            logger.error(f"FAILED: Payments ingestion - {e}")
            results["payments"] = {"status": "FAILED", "error": str(e)}
            overall_status = "PARTIAL_FAILURE"

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    pipeline_end = datetime.now()
    duration = (pipeline_end - pipeline_start).total_seconds()

    summary = {
        "overall_status": overall_status,
        "start_time": pipeline_start.isoformat(),
        "end_time": pipeline_end.isoformat(),
        "duration_seconds": duration,
        "tables": results,
    }

    logger.info("=" * 60)
    logger.info(f"PIPELINE COMPLETE - Status: {overall_status}")
    logger.info(f"Duration: {duration:.1f}s")
    for table, metrics in results.items():
        status = metrics.get("status", "UNKNOWN")
        source_count = metrics.get("source_count", "N/A")
        valid_count = metrics.get("valid_count", "N/A")
        logger.info(f"  {table}: {status} (source={source_count}, valid={valid_count})")
    logger.info("=" * 60)

    return summary


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Full_Migration_Pipeline").getOrCreate()

    config = {
        "base_source_path": spark.conf.get("migration.base_source_path", "/mnt/legacy"),
        "base_rejected_path": spark.conf.get("migration.base_rejected_path", "/mnt/migration/rejected"),
        "write_mode": spark.conf.get("migration.write_mode", "overwrite"),
    }

    result = run_full_pipeline(spark, config)

    if result["overall_status"] != "SUCCESS":
        logger.error("Pipeline completed with failures!")
        sys.exit(1)

    print("Pipeline completed successfully!")
