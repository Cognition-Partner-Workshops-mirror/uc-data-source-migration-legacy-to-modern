"""
Migration Pipeline Orchestrator

Runs the full legacy CDW to Delta Lake migration in the correct order:
1. Borrowers (dimension table, no dependencies)
2. Loan Products (dimension table, no dependencies)
3. Loan Accounts (depends on borrowers + products for FK resolution)
4. Payments (depends on loan_accounts for FK resolution)

Usage:
    Configure source paths and run in a Databricks notebook or as a job:

    from run_pipeline import run_full_migration
    run_full_migration(spark, config)
"""

import json
import time
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_accounts
import ingest_loan_products
import ingest_payments


DEFAULT_CONFIG = {
    "source_base_path": "/mnt/legacy-data/cdw",
    "target_schema": "loan_warehouse",
    "rejection_path": "/mnt/data/rejections",
    "mode": "overwrite",
    "sources": {
        "borrowers": "/mnt/legacy-data/cdw/CDW_BORR_MSTR",
        "loan_products": "/mnt/legacy-data/cdw/CDW_LN_PROD",
        "loan_accounts": "/mnt/legacy-data/cdw/CDW_LN_ACCT",
        "payments": "/mnt/legacy-data/cdw/CDW_PMT_HIST",
    },
}


def run_full_migration(
    spark: SparkSession,
    config: Optional[dict] = None,
) -> dict:
    """
    Execute the full migration pipeline in dependency order.

    Args:
        spark: Active SparkSession
        config: Configuration dictionary (uses DEFAULT_CONFIG if not provided)

    Returns:
        Dictionary with overall migration statistics and timing
    """
    if config is None:
        config = DEFAULT_CONFIG

    schema = config.get("target_schema", "loan_warehouse")
    rejection_path = config.get("rejection_path", "/mnt/data/rejections")
    mode = config.get("mode", "overwrite")
    sources = config.get("sources", DEFAULT_CONFIG["sources"])

    results = {}
    start_time = time.time()
    pipeline_start = datetime.now().isoformat()

    print("=" * 70)
    print(f"MIGRATION PIPELINE START: {pipeline_start}")
    print("=" * 70)

    # Step 1: Borrowers (no dependencies)
    print("\n[STEP 1/4] Ingesting borrowers...")
    step_start = time.time()
    try:
        results["borrowers"] = ingest_borrowers.run(spark, {
            "source_path": sources["borrowers"],
            "target_table": f"{schema}.borrowers",
            "rejection_path": rejection_path,
            "mode": mode,
        })
        results["borrowers"]["duration_seconds"] = round(time.time() - step_start, 2)
        results["borrowers"]["status"] = "SUCCESS"
    except Exception as e:
        results["borrowers"] = {"status": "FAILED", "error": str(e)}
        print(f"[ERROR] Borrower ingestion failed: {e}")
        raise

    # Step 2: Loan Products (no dependencies)
    print("\n[STEP 2/4] Ingesting loan products...")
    step_start = time.time()
    try:
        results["loan_products"] = ingest_loan_products.run(spark, {
            "source_path": sources["loan_products"],
            "target_table": f"{schema}.loan_products",
            "rejection_path": rejection_path,
            "mode": mode,
        })
        results["loan_products"]["duration_seconds"] = round(time.time() - step_start, 2)
        results["loan_products"]["status"] = "SUCCESS"
    except Exception as e:
        results["loan_products"] = {"status": "FAILED", "error": str(e)}
        print(f"[ERROR] Loan products ingestion failed: {e}")
        raise

    # Step 3: Loan Accounts (depends on borrowers + products)
    print("\n[STEP 3/4] Ingesting loan accounts...")
    step_start = time.time()
    try:
        results["loan_accounts"] = ingest_loan_accounts.run(spark, {
            "source_path": sources["loan_accounts"],
            "target_table": f"{schema}.loan_accounts",
            "rejection_path": rejection_path,
            "mode": mode,
            "borrower_table": f"{schema}.borrowers",
            "product_table": f"{schema}.loan_products",
        })
        results["loan_accounts"]["duration_seconds"] = round(time.time() - step_start, 2)
        results["loan_accounts"]["status"] = "SUCCESS"
    except Exception as e:
        results["loan_accounts"] = {"status": "FAILED", "error": str(e)}
        print(f"[ERROR] Loan accounts ingestion failed: {e}")
        raise

    # Step 4: Payments (depends on loan_accounts)
    print("\n[STEP 4/4] Ingesting payments...")
    step_start = time.time()
    try:
        results["payments"] = ingest_payments.run(spark, {
            "source_path": sources["payments"],
            "target_table": f"{schema}.payments",
            "rejection_path": rejection_path,
            "mode": mode,
            "loan_accounts_table": f"{schema}.loan_accounts",
        })
        results["payments"]["duration_seconds"] = round(time.time() - step_start, 2)
        results["payments"]["status"] = "SUCCESS"
    except Exception as e:
        results["payments"] = {"status": "FAILED", "error": str(e)}
        print(f"[ERROR] Payments ingestion failed: {e}")
        raise

    # Summary
    total_duration = round(time.time() - start_time, 2)
    results["_pipeline_summary"] = {
        "start_time": pipeline_start,
        "end_time": datetime.now().isoformat(),
        "total_duration_seconds": total_duration,
        "tables_loaded": sum(
            1 for v in results.values()
            if isinstance(v, dict) and v.get("status") == "SUCCESS"
        ),
        "total_source_records": sum(
            v.get("source_count", 0) for v in results.values()
            if isinstance(v, dict) and "source_count" in v
        ),
        "total_rejected_records": sum(
            v.get("rejected_count", 0) for v in results.values()
            if isinstance(v, dict) and "rejected_count" in v
        ),
    }

    print("\n" + "=" * 70)
    print("MIGRATION PIPELINE COMPLETE")
    print(f"Duration: {total_duration}s")
    print(f"Tables loaded: {results['_pipeline_summary']['tables_loaded']}/4")
    print(f"Total records: {results['_pipeline_summary']['total_source_records']}")
    print(f"Total rejections: {results['_pipeline_summary']['total_rejected_records']}")
    print("=" * 70)

    return results


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.getOrCreate()
    migration_results = run_full_migration(spark)
    print("\nDetailed results:")
    print(json.dumps(migration_results, indent=2, default=str))
