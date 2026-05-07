"""
Orchestrator: run the full legacy CDW → Delta Lake migration pipeline.

Executes ingestion in dependency order:
  1. borrowers      (no FK dependencies)
  2. loan_products  (no FK dependencies)
  3. loan_accounts  (depends on borrowers, loan_products)
  4. payments       (depends on loan_accounts)

Each step logs row counts and the orchestrator collects a summary dict
suitable for the data-quality reconciliation step.

Usage (Databricks notebook):
    from databricks.ingestion.run_pipeline import run_migration
    results = run_migration(spark, base_path="/mnt/landing/cdw/")
"""

import logging
import time

from pyspark.sql import SparkSession

from databricks.ingestion.ingest_borrowers import ingest_borrowers
from databricks.ingestion.ingest_loan_accounts import ingest_loan_accounts
from databricks.ingestion.ingest_loan_products import ingest_loan_products
from databricks.ingestion.ingest_payments import ingest_payments

logger = logging.getLogger("migration.run_pipeline")

STEPS = [
    ("borrowers", "cdw_borr_mstr", ingest_borrowers),
    ("loan_products", "cdw_ln_prod", ingest_loan_products),
    ("loan_accounts", "cdw_ln_acct", ingest_loan_accounts),
    ("payments", "cdw_pmt_hist", ingest_payments),
]


def run_migration(
    spark: SparkSession,
    base_path: str,
    file_format: str = "csv",
    write_mode: str = "overwrite",
) -> dict:
    """Execute the full migration pipeline in dependency order.

    Args:
        spark: Active SparkSession.
        base_path: Root landing-zone path containing one sub-folder per source
                   table (e.g., ``/mnt/landing/cdw/cdw_borr_mstr/``).
        file_format: 'csv' or 'parquet'.
        write_mode: Spark write mode ('overwrite' for full reload, 'append' for incremental).

    Returns:
        Dictionary keyed by table name with source_count, target_count, and elapsed_seconds.
    """
    results = {}
    overall_start = time.time()

    for table_name, source_folder, ingest_fn in STEPS:
        source_path = f"{base_path.rstrip('/')}/{source_folder}/"
        step_start = time.time()
        logger.info("=" * 60)
        logger.info("Starting ingestion: %s from %s", table_name, source_path)

        try:
            if table_name in ("loan_accounts", "payments"):
                counts = ingest_fn(spark, source_path, file_format, write_mode)
            else:
                counts = ingest_fn(spark, source_path, file_format, write_mode)

            elapsed = round(time.time() - step_start, 2)
            results[table_name] = {**counts, "elapsed_seconds": elapsed, "status": "SUCCESS"}
            logger.info(
                "Completed %s: %d → %d rows in %.2fs",
                table_name,
                counts["source_count"],
                counts["target_count"],
                elapsed,
            )
        except Exception:
            elapsed = round(time.time() - step_start, 2)
            results[table_name] = {
                "source_count": 0,
                "target_count": 0,
                "elapsed_seconds": elapsed,
                "status": "FAILED",
            }
            logger.exception("FAILED ingestion for %s after %.2fs", table_name, elapsed)

    overall_elapsed = round(time.time() - overall_start, 2)
    logger.info("=" * 60)
    logger.info("Migration pipeline completed in %.2fs", overall_elapsed)
    for name, info in results.items():
        logger.info(
            "  %-20s  src=%d  tgt=%d  %.2fs  [%s]",
            name,
            info["source_count"],
            info["target_count"],
            info["elapsed_seconds"],
            info["status"],
        )

    return results
