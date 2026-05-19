"""
Full ingestion orchestrator: runs all four ingestion scripts in dependency order.

Execution order (respects FK dependencies):
  1. borrowers       — no dependencies (dimension table)
  2. loan_products   — no dependencies (dimension table)
  3. loan_accounts   — depends on borrowers + loan_products (FK resolution)
  4. payments        — depends on loan_accounts (FK resolution)

This script is designed to be run as a Databricks notebook or via spark-submit.
It coordinates the individual ingestion modules and provides a single entry point
for the complete migration pipeline.

Usage:
    spark-submit run_full_ingestion.py \\
        --borrowers-source /mnt/landing/cdw_borr_mstr.csv \\
        --products-source /mnt/landing/cdw_ln_prod.csv \\
        --accounts-source /mnt/landing/cdw_ln_acct.csv \\
        --payments-source /mnt/landing/cdw_pmt_hist.csv
"""

import argparse
import logging
import sys
import time

from pyspark.sql import SparkSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("run_full_ingestion")

# Default source paths (override via CLI arguments)
DEFAULT_PATHS = {
    "borrowers": "/mnt/landing/cdw_borr_mstr",
    "products": "/mnt/landing/cdw_ln_prod",
    "accounts": "/mnt/landing/cdw_ln_acct",
    "payments": "/mnt/landing/cdw_pmt_hist",
}


def create_spark_session() -> SparkSession:
    """Create a shared SparkSession for all ingestion steps."""
    return (
        SparkSession.builder
        .appName("LoanMigration_FullIngestion")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .getOrCreate()
    )


def run_step(step_name: str, step_fn, *args, **kwargs):
    """
    Execute a single ingestion step with timing and error handling.

    Logs the start, duration, and outcome of each step. On failure, logs the
    error and re-raises to halt the pipeline (downstream steps depend on
    upstream tables being populated).

    Args:
        step_name: Human-readable name for logging.
        step_fn: Callable to execute.
        *args, **kwargs: Passed through to step_fn.
    """
    logger.info(f"{'=' * 60}")
    logger.info(f"STEP: {step_name}")
    logger.info(f"{'=' * 60}")

    start_time = time.time()
    try:
        step_fn(*args, **kwargs)
        elapsed = time.time() - start_time
        logger.info(f"STEP '{step_name}' completed in {elapsed:.1f}s")
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"STEP '{step_name}' FAILED after {elapsed:.1f}s: {str(e)}",
            exc_info=True,
        )
        raise


def ingest_borrowers(spark: SparkSession, source_path: str, file_format: str):
    """Run borrower ingestion using the shared SparkSession."""
    from ingest_borrowers import read_source, transform_borrowers, write_to_delta
    source_df = read_source(spark, source_path, file_format)
    transformed_df = transform_borrowers(source_df)
    write_to_delta(transformed_df, "loan_management.borrowers")


def ingest_loan_products(spark: SparkSession, source_path: str, file_format: str):
    """Run loan product ingestion using the shared SparkSession."""
    from ingest_loan_products import read_source, transform_loan_products, write_to_delta
    source_df = read_source(spark, source_path, file_format)
    transformed_df = transform_loan_products(source_df)
    write_to_delta(transformed_df, "loan_management.loan_products")


def ingest_loan_accounts(spark: SparkSession, source_path: str, file_format: str):
    """Run loan account ingestion using the shared SparkSession."""
    from ingest_loan_accounts import read_source, transform_loan_accounts, write_to_delta
    source_df = read_source(spark, source_path, file_format)
    transformed_df = transform_loan_accounts(spark, source_df)
    write_to_delta(transformed_df, "loan_management.loan_accounts")


def ingest_payments(spark: SparkSession, source_path: str, file_format: str):
    """Run payment ingestion using the shared SparkSession."""
    from ingest_payments import read_source, transform_payments, write_to_delta
    source_df = read_source(spark, source_path, file_format)
    transformed_df = transform_payments(spark, source_df)
    write_to_delta(transformed_df, "loan_management.payments")


def main():
    """Main entry point for the full ingestion pipeline."""
    parser = argparse.ArgumentParser(
        description="Run complete CDW-to-Delta-Lake migration pipeline"
    )
    parser.add_argument(
        "--borrowers-source", default=DEFAULT_PATHS["borrowers"],
        help="Path to CDW_BORR_MSTR source file",
    )
    parser.add_argument(
        "--products-source", default=DEFAULT_PATHS["products"],
        help="Path to CDW_LN_PROD source file",
    )
    parser.add_argument(
        "--accounts-source", default=DEFAULT_PATHS["accounts"],
        help="Path to CDW_LN_ACCT source file",
    )
    parser.add_argument(
        "--payments-source", default=DEFAULT_PATHS["payments"],
        help="Path to CDW_PMT_HIST source file",
    )
    parser.add_argument(
        "--format", default="csv", choices=["csv", "parquet"],
        help="Source file format for all tables (default: csv)",
    )
    args = parser.parse_args()

    logger.info("#" * 60)
    logger.info("STARTING FULL CDW-TO-DELTA-LAKE MIGRATION")
    logger.info("#" * 60)

    overall_start = time.time()
    spark = create_spark_session()

    try:
        # Create schema first (idempotent)
        spark.sql("CREATE SCHEMA IF NOT EXISTS loan_management")

        # Step 1 & 2: Dimension tables (no FK dependencies, could run in parallel)
        run_step(
            "Ingest Borrowers (CDW_BORR_MSTR -> borrowers)",
            ingest_borrowers, spark, args.borrowers_source, args.format,
        )
        run_step(
            "Ingest Loan Products (CDW_LN_PROD -> loan_products)",
            ingest_loan_products, spark, args.products_source, args.format,
        )

        # Step 3: Fact table with FK to borrowers + loan_products
        run_step(
            "Ingest Loan Accounts (CDW_LN_ACCT -> loan_accounts)",
            ingest_loan_accounts, spark, args.accounts_source, args.format,
        )

        # Step 4: Fact table with FK to loan_accounts
        run_step(
            "Ingest Payments (CDW_PMT_HIST -> payments)",
            ingest_payments, spark, args.payments_source, args.format,
        )

        overall_elapsed = time.time() - overall_start
        logger.info("#" * 60)
        logger.info(f"FULL MIGRATION COMPLETED in {overall_elapsed:.1f}s")
        logger.info("#" * 60)

    except Exception as e:
        overall_elapsed = time.time() - overall_start
        logger.error(
            f"FULL MIGRATION FAILED after {overall_elapsed:.1f}s: {str(e)}",
            exc_info=True,
        )
        sys.exit(1)

    finally:
        spark.stop()


if __name__ == "__main__":
    main()
