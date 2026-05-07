"""
Orchestrator: Runs the full CDW-to-Delta-Lake ingestion pipeline in the
correct dependency order.

This script is designed to be run as a Databricks notebook or via
spark-submit. It imports and executes each ingestion module sequentially.

Usage (Databricks notebook):
    %run ./run_full_pipeline

Usage (spark-submit):
    spark-submit --master local[*] run_full_pipeline.py \
        --landing-path /mnt/landing \
        --source-format csv
"""

import argparse
import logging
import sys
import time

from pyspark.sql import SparkSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("cdw_migration.orchestrator")

# Default table names (Unity Catalog three-level namespace)
CATALOG = "loan_catalog"
SCHEMA = "loan_warehouse"

TABLE_BORROWERS = f"{CATALOG}.{SCHEMA}.borrowers"
TABLE_PRODUCTS = f"{CATALOG}.{SCHEMA}.loan_products"
TABLE_LOANS = f"{CATALOG}.{SCHEMA}.loan_accounts"
TABLE_PAYMENTS = f"{CATALOG}.{SCHEMA}.payments"


def run_step(step_name: str, func, *args, **kwargs):
    """Execute a pipeline step with timing and error handling."""
    logger.info("=" * 60)
    logger.info("STARTING STEP: %s", step_name)
    logger.info("=" * 60)
    start = time.time()
    try:
        func(*args, **kwargs)
        elapsed = time.time() - start
        logger.info("COMPLETED STEP: %s (%.1fs)", step_name, elapsed)
    except Exception:
        elapsed = time.time() - start
        logger.exception("FAILED STEP: %s after %.1fs", step_name, elapsed)
        raise


def ingest_borrowers(spark: SparkSession, landing_path: str, fmt: str):
    from ingest_borrowers import read_source, transform, write_target

    raw = read_source(spark, f"{landing_path}/cdw_borr_mstr.{fmt}", fmt)
    transformed = transform(raw)
    write_target(transformed, TABLE_BORROWERS)


def ingest_loan_products(spark: SparkSession, landing_path: str, fmt: str):
    from ingest_loan_products import read_source, transform, write_target

    raw = read_source(spark, f"{landing_path}/cdw_ln_prod.{fmt}", fmt)
    transformed = transform(raw)
    write_target(transformed, TABLE_PRODUCTS)


def ingest_loan_accounts(spark: SparkSession, landing_path: str, fmt: str):
    from ingest_loan_accounts import read_source, transform, write_target

    raw = read_source(spark, f"{landing_path}/cdw_ln_acct.{fmt}", fmt)
    transformed = transform(raw, spark, TABLE_BORROWERS, TABLE_PRODUCTS)
    write_target(transformed, TABLE_LOANS)


def ingest_payments(spark: SparkSession, landing_path: str, fmt: str):
    from ingest_payments import read_source, transform, write_target

    raw = read_source(spark, f"{landing_path}/cdw_pmt_hist.{fmt}", fmt)
    transformed = transform(raw, spark, TABLE_LOANS)
    write_target(transformed, TABLE_PAYMENTS)


def main():
    parser = argparse.ArgumentParser(description="Run full CDW migration pipeline")
    parser.add_argument("--landing-path", required=True, help="Base path to landing zone files")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"], help="Source file format")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_Full_Pipeline").getOrCreate()

    pipeline_start = time.time()
    logger.info("=" * 60)
    logger.info("CDW-TO-DELTA LAKE MIGRATION PIPELINE")
    logger.info("Landing path: %s", args.landing_path)
    logger.info("Source format: %s", args.source_format)
    logger.info("=" * 60)

    try:
        # Step 1: Dimension tables (no FK dependencies)
        run_step("1/4 - Ingest Borrowers", ingest_borrowers, spark, args.landing_path, args.source_format)
        run_step("2/4 - Ingest Loan Products", ingest_loan_products, spark, args.landing_path, args.source_format)

        # Step 2: Fact tables (depend on dimension tables)
        run_step("3/4 - Ingest Loan Accounts", ingest_loan_accounts, spark, args.landing_path, args.source_format)
        run_step("4/4 - Ingest Payments", ingest_payments, spark, args.landing_path, args.source_format)

        total_elapsed = time.time() - pipeline_start
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE in %.1fs", total_elapsed)
        logger.info("=" * 60)

    except Exception:
        total_elapsed = time.time() - pipeline_start
        logger.exception("PIPELINE FAILED after %.1fs", total_elapsed)
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
