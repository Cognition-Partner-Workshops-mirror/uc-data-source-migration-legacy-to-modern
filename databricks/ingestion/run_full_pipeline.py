"""
Orchestrator: Run the full legacy-to-modern ingestion pipeline.

Executes each table ingestion in dependency order:
  1. borrowers      (no dependencies)
  2. loan_products  (no dependencies)
  3. loan_accounts  (depends on borrowers, loan_products)
  4. payments       (depends on loan_accounts)

Usage:
    spark-submit run_full_pipeline.py \
        --borrowers  /mnt/landing/cdw_borr_mstr/ \
        --products   /mnt/landing/cdw_ln_prod/ \
        --accounts   /mnt/landing/cdw_ln_acct/ \
        --payments   /mnt/landing/cdw_pmt_hist/
"""

import argparse
import logging
import sys
import time

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_full_pipeline")


def run_step(name: str, func, *args) -> None:
    """Run a pipeline step with timing and error handling."""
    logger.info("=" * 60)
    logger.info("STARTING: %s", name)
    logger.info("=" * 60)
    start = time.time()
    try:
        func(*args)
        elapsed = time.time() - start
        logger.info("COMPLETED: %s (%.1fs)", name, elapsed)
    except Exception:
        elapsed = time.time() - start
        logger.exception("FAILED: %s (%.1fs)", name, elapsed)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full CDW migration pipeline")
    parser.add_argument("--borrowers", required=True, help="Path to CDW_BORR_MSTR source")
    parser.add_argument("--products", required=True, help="Path to CDW_LN_PROD source")
    parser.add_argument("--accounts", required=True, help="Path to CDW_LN_ACCT source")
    parser.add_argument("--payments", required=True, help="Path to CDW_PMT_HIST source")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Full_Migration_Pipeline").getOrCreate()

    pipeline_start = time.time()
    logger.info("Starting full CDW-to-Delta-Lake migration pipeline")

    try:
        # Phase 1: Independent dimension tables (can run in parallel on Databricks)
        run_step(
            "Ingest Borrowers (CDW_BORR_MSTR → borrowers)",
            lambda: (
                ingest_borrowers.write_target(
                    ingest_borrowers.transform(
                        ingest_borrowers.read_source(spark, args.borrowers)
                    )
                )
            ),
        )

        run_step(
            "Ingest Loan Products (CDW_LN_PROD → loan_products)",
            lambda: (
                ingest_loan_products.write_target(
                    ingest_loan_products.transform(
                        ingest_loan_products.read_source(spark, args.products)
                    )
                )
            ),
        )

        # Phase 2: Fact tables with FK dependencies
        run_step(
            "Ingest Loan Accounts (CDW_LN_ACCT → loan_accounts)",
            lambda: (
                ingest_loan_accounts.write_target(
                    ingest_loan_accounts.transform(
                        spark,
                        ingest_loan_accounts.read_source(spark, args.accounts),
                    )
                )
            ),
        )

        run_step(
            "Ingest Payments (CDW_PMT_HIST → payments)",
            lambda: (
                ingest_payments.write_target(
                    ingest_payments.transform(
                        spark,
                        ingest_payments.read_source(spark, args.payments),
                    )
                )
            ),
        )

        elapsed = time.time() - pipeline_start
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETED SUCCESSFULLY (%.1fs total)", elapsed)
        logger.info("=" * 60)

    except Exception:
        elapsed = time.time() - pipeline_start
        logger.exception("PIPELINE FAILED after %.1fs", elapsed)
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
