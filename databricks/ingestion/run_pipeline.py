"""Master pipeline orchestrator — runs all ingestion steps in dependency order.

Execution order (respects FK dependencies):
  1. borrowers       (no dependencies)
  2. loan_products   (no dependencies)
  3. loan_accounts   (depends on borrowers, loan_products)
  4. payments        (depends on loan_accounts)

Usage (Databricks notebook or job):
    spark = SparkSession.builder.appName("LoanMigration").getOrCreate()
    exec(open("run_pipeline.py").read())
"""

import logging
import sys
from datetime import datetime

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments

logger = logging.getLogger("ingestion.pipeline")
logging.basicConfig(level=logging.INFO)


def run_all(spark: SparkSession) -> dict:
    """Run all ingestion steps and return a summary dict."""
    results = {}
    steps = [
        ("borrowers", ingest_borrowers),
        ("loan_products", ingest_loan_products),
        ("loan_accounts", ingest_loan_accounts),
        ("payments", ingest_payments),
    ]

    start = datetime.utcnow()
    for name, module in steps:
        step_start = datetime.utcnow()
        logger.info("=" * 60)
        logger.info("Starting ingestion: %s", name)
        logger.info("=" * 60)
        try:
            source_count = module.run(spark)
            target_count = spark.table(f"loan_warehouse.{name}").count()
            results[name] = {
                "status": "SUCCESS",
                "source_rows": source_count,
                "target_rows": target_count,
                "duration_sec": (datetime.utcnow() - step_start).total_seconds(),
            }
        except Exception as exc:
            logger.error("FAILED ingestion for %s: %s", name, exc, exc_info=True)
            results[name] = {
                "status": "FAILED",
                "error": str(exc),
                "duration_sec": (datetime.utcnow() - step_start).total_seconds(),
            }
            # Halt on failure — downstream tables depend on this one
            logger.error("Halting pipeline due to failure in %s", name)
            break

    total_duration = (datetime.utcnow() - start).total_seconds()
    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1f seconds", total_duration)
    for name, info in results.items():
        logger.info(
            "  %-20s  %s  (%.1fs)",
            name,
            info["status"],
            info["duration_sec"],
        )
    logger.info("=" * 60)

    return results


if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_Pipeline").getOrCreate()
    results = run_all(spark)
    failed = [n for n, r in results.items() if r["status"] == "FAILED"]
    if failed:
        logger.error("Pipeline finished with failures: %s", failed)
        sys.exit(1)
