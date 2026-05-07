"""
Orchestrator: runs the full legacy-to-modern ingestion pipeline in order.

Execution order (respects FK dependencies):
  1. borrowers      (no dependencies)
  2. loan_products  (no dependencies)
  3. loan_accounts  (depends on borrowers + loan_products)
  4. payments       (depends on loan_accounts)

Usage:
    spark-submit --master local[*] run_pipeline.py \
        --source-dir /mnt/legacy \
        --source-format csv \
        --target-db loan_warehouse \
        --error-dir /mnt/migration/errors
"""

import argparse
import logging
import sys

from ingest_borrowers import main as ingest_borrowers
from ingest_loan_products import main as ingest_loan_products
from ingest_loan_accounts import main as ingest_loan_accounts
from ingest_payments import main as ingest_payments

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_pipeline")

STEPS = [
    ("borrowers", "cdw_borr_mstr", ingest_borrowers),
    ("loan_products", "cdw_ln_prod", ingest_loan_products),
    ("loan_accounts", "cdw_ln_acct", ingest_loan_accounts),
    ("payments", "cdw_pmt_hist", ingest_payments),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full legacy migration pipeline")
    parser.add_argument("--source-dir", required=True, help="Base directory with legacy source files")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--target-db", default="loan_warehouse")
    parser.add_argument("--error-dir", default="/mnt/migration/errors")
    opts = parser.parse_args()

    logger.info("=" * 70)
    logger.info("STARTING FULL MIGRATION PIPELINE")
    logger.info("  Source dir:    %s", opts.source_dir)
    logger.info("  Source format: %s", opts.source_format)
    logger.info("  Target DB:     %s", opts.target_db)
    logger.info("  Error dir:     %s", opts.error_dir)
    logger.info("=" * 70)

    for step_name, source_subdir, step_fn in STEPS:
        logger.info("-" * 50)
        logger.info("STEP: %s", step_name)
        logger.info("-" * 50)

        step_args = [
            "--source-path", f"{opts.source_dir}/{source_subdir}",
            "--source-format", opts.source_format,
            "--target-table", f"{opts.target_db}.{step_name}",
            "--error-path", f"{opts.error_dir}/{step_name}",
        ]

        # Add FK table args for steps that need them
        if step_name == "loan_accounts":
            step_args += [
                "--borrower-table", f"{opts.target_db}.borrowers",
                "--product-table", f"{opts.target_db}.loan_products",
            ]
        elif step_name == "payments":
            step_args += [
                "--loan-table", f"{opts.target_db}.loan_accounts",
            ]

        try:
            step_fn(step_args)
            logger.info("STEP %s: SUCCESS", step_name)
        except SystemExit as e:
            if e.code != 0:
                logger.error("STEP %s: FAILED (exit code %s)", step_name, e.code)
                sys.exit(1)
        except Exception:
            logger.exception("STEP %s: FAILED with exception", step_name)
            sys.exit(1)

    logger.info("=" * 70)
    logger.info("MIGRATION PIPELINE COMPLETE")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
