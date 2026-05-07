"""
Orchestrator script — runs the full CDW-to-Delta Lake ingestion pipeline
in the correct dependency order.

Execution order:
  1. borrowers        (no dependencies)
  2. loan_products    (no dependencies)
  3. loan_accounts    (depends on borrowers for FK resolution)
  4. payments         (depends on loan_accounts for FK validation)

Usage (Databricks notebook or spark-submit):
    %run ./run_pipeline

Or:
    spark-submit --py-files transforms.py run_pipeline.py
"""

import logging
import sys
import time

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_accounts
import ingest_loan_products
import ingest_payments

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_pipeline")


def run_pipeline(spark: SparkSession) -> dict:
    """Execute the full migration pipeline and collect statistics."""
    pipeline_start = time.time()
    results = {}

    # --- Phase 1: Independent dimension tables ---
    steps = [
        ("borrowers", ingest_borrowers),
        ("loan_products", ingest_loan_products),
    ]
    for name, module in steps:
        logger.info("=" * 60)
        logger.info("PHASE 1 — Ingesting %s", name)
        logger.info("=" * 60)
        try:
            results[name] = module.run(spark)
        except Exception:
            logger.exception("FAILED: %s ingestion", name)
            results[name] = {"error": True}

    # --- Phase 2: Dependent fact tables ---
    steps = [
        ("loan_accounts", ingest_loan_accounts),
        ("payments", ingest_payments),
    ]
    for name, module in steps:
        logger.info("=" * 60)
        logger.info("PHASE 2 — Ingesting %s", name)
        logger.info("=" * 60)
        try:
            results[name] = module.run(spark)
        except Exception:
            logger.exception("FAILED: %s ingestion", name)
            results[name] = {"error": True}

    elapsed = time.time() - pipeline_start
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE in %.1f seconds", elapsed)
    logger.info("=" * 60)
    for table, stats in results.items():
        logger.info("  %s: %s", table, stats)

    failed = [t for t, s in results.items() if s.get("error")]
    if failed:
        logger.error("FAILED TABLES: %s", failed)
        sys.exit(1)

    return results


if __name__ == "__main__":
    spark = SparkSession.builder.appName("cdw_migration_pipeline").getOrCreate()
    run_pipeline(spark)
