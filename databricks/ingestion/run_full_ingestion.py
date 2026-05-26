"""
Full ingestion orchestrator for the legacy CDW to Delta Lake migration.

Executes all four ingestion scripts in the correct dependency order:
  1. borrowers     (no dependencies — dimension table)
  2. loan_products (no dependencies — dimension/reference table)
  3. loan_accounts (depends on borrowers + loan_products for FK resolution)
  4. payments      (depends on loan_accounts for FK resolution)

This script can be run as a Databricks notebook or submitted via spark-submit.
It provides a single entry point for the full migration pipeline with
consolidated logging and error handling.

Usage:
  # Run all four ingestion steps in sequence
  spark-submit run_full_ingestion.py

  # Or import and call from a Databricks notebook:
  # %run ./run_full_ingestion
"""

import logging
import time

# Import individual ingestion modules
import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments

# =============================================================================
# Logging setup
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("run_full_ingestion")


def run_step(step_name, step_func):
    """
    Execute a single ingestion step with timing and error handling.

    Returns (success: bool, elapsed_seconds: float).
    """
    logger.info(f"{'=' * 70}")
    logger.info(f"STEP: {step_name}")
    logger.info(f"{'=' * 70}")
    start = time.time()
    try:
        step_func()
        elapsed = time.time() - start
        logger.info(f"STEP {step_name} completed in {elapsed:.1f}s")
        return True, elapsed
    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"STEP {step_name} FAILED after {elapsed:.1f}s: {e}", exc_info=True)
        return False, elapsed


def main():
    """
    Run the full ingestion pipeline in dependency order.

    Stops on first failure to prevent FK resolution issues in downstream steps.
    """
    logger.info("=" * 70)
    logger.info("STARTING FULL INGESTION PIPELINE: Legacy CDW → Delta Lake")
    logger.info("=" * 70)

    # Define steps in execution order (order matters for FK dependencies)
    steps = [
        ("1. Borrowers (CDW_BORR_MSTR → borrowers)", ingest_borrowers.main),
        ("2. Loan Products (CDW_LN_PROD → loan_products)", ingest_loan_products.main),
        ("3. Loan Accounts (CDW_LN_ACCT → loan_accounts)", ingest_loan_accounts.main),
        ("4. Payments (CDW_PMT_HIST → payments)", ingest_payments.main),
    ]

    results = []
    total_start = time.time()

    for step_name, step_func in steps:
        success, elapsed = run_step(step_name, step_func)
        results.append((step_name, success, elapsed))

        if not success:
            # Stop pipeline on failure — downstream steps depend on upstream data
            logger.error(
                f"Pipeline halted at '{step_name}'. "
                "Downstream steps skipped to prevent FK resolution errors."
            )
            break

    # Print summary
    total_elapsed = time.time() - total_start
    logger.info("")
    logger.info("=" * 70)
    logger.info("INGESTION PIPELINE SUMMARY")
    logger.info("=" * 70)
    all_passed = True
    for step_name, success, elapsed in results:
        status = "PASS" if success else "FAIL"
        if not success:
            all_passed = False
        logger.info(f"  [{status}] {step_name} ({elapsed:.1f}s)")

    # Report steps that were skipped due to earlier failure
    completed_count = len(results)
    if completed_count < len(steps):
        for step_name, _ in steps[completed_count:]:
            logger.info(f"  [SKIP] {step_name}")
            all_passed = False

    logger.info(f"  Total elapsed: {total_elapsed:.1f}s")
    logger.info("=" * 70)

    if all_passed:
        logger.info("ALL STEPS COMPLETED SUCCESSFULLY")
    else:
        logger.error("PIPELINE COMPLETED WITH ERRORS — review logs above")
        raise RuntimeError("Ingestion pipeline failed — see logs for details")


if __name__ == "__main__":
    main()
