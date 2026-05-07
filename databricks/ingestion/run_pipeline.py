"""
Orchestrator script that runs the full CDW-to-Delta migration pipeline
in the correct dependency order.

Usage (Databricks notebook or spark-submit):
    spark-submit run_pipeline.py \
        --landing-root /mnt/landing \
        --quarantine-root /mnt/quarantine \
        --format csv

Expected landing directory structure:
    /mnt/landing/
        cdw_borr_mstr/      (CSV or Parquet files)
        cdw_ln_prod/
        cdw_ln_acct/
        cdw_pmt_hist/
"""

import logging
import sys
import time
from argparse import ArgumentParser

from ingest_borrowers import main as ingest_borrowers
from ingest_loan_products import main as ingest_loan_products
from ingest_loan_accounts import main as ingest_loan_accounts
from ingest_payments import main as ingest_payments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_pipeline")

STEPS = [
    ("1/4 - Borrowers (CDW_BORR_MSTR)", "cdw_borr_mstr", ingest_borrowers),
    ("2/4 - Loan Products (CDW_LN_PROD)", "cdw_ln_prod", ingest_loan_products),
    ("3/4 - Loan Accounts (CDW_LN_ACCT)", "cdw_ln_acct", ingest_loan_accounts),
    ("4/4 - Payments (CDW_PMT_HIST)", "cdw_pmt_hist", ingest_payments),
]


def main() -> None:
    parser = ArgumentParser(description="Run full CDW migration pipeline")
    parser.add_argument(
        "--landing-root",
        required=True,
        help="Root path containing source table subdirectories",
    )
    parser.add_argument(
        "--quarantine-root",
        default="/mnt/quarantine",
        help="Root path for quarantined records",
    )
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    args = parser.parse_args()

    overall_start = time.time()
    failed_steps = []

    for label, subdir, fn in STEPS:
        source_path = f"{args.landing_root}/{subdir}"
        quarantine_path = f"{args.quarantine_root}/{subdir}"

        logger.info("=" * 70)
        logger.info("STEP %s", label)
        logger.info("  Source:     %s", source_path)
        logger.info("  Quarantine: %s", quarantine_path)
        logger.info("=" * 70)

        step_start = time.time()
        try:
            fn(source_path, args.format, quarantine_path)
            elapsed = time.time() - step_start
            logger.info("STEP %s completed in %.1f seconds.", label, elapsed)
        except Exception:
            elapsed = time.time() - step_start
            logger.exception(
                "STEP %s FAILED after %.1f seconds.", label, elapsed
            )
            failed_steps.append(label)

    overall_elapsed = time.time() - overall_start
    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETE in %.1f seconds.", overall_elapsed)

    if failed_steps:
        logger.error("The following steps failed: %s", ", ".join(failed_steps))
        sys.exit(1)
    else:
        logger.info("All steps succeeded.")


if __name__ == "__main__":
    main()
