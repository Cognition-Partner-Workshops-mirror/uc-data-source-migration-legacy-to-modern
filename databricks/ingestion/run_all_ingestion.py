"""
run_all_ingestion.py — Master orchestrator for the full CDW → Delta migration.

Executes the ingestion scripts in dependency order:
  1. borrowers     (no dependencies — dimension table)
  2. loan_products (no dependencies — dimension table)
  3. loan_accounts (depends on borrowers + loan_products for FK resolution)
  4. payments      (depends on loan_accounts for FK resolution)

Each step logs its progress and row counts. If any step fails, the error is
logged and execution halts — partial migrations are not promoted to avoid
inconsistent state in the target warehouse.
"""

import logging
import sys

# --- Configure root logger for the migration pipeline ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cdw_migration.orchestrator")


def run_step(step_name: str, module_main):
    """Execute a single ingestion step with error handling."""
    logger.info("=" * 60)
    logger.info("STARTING STEP: %s", step_name)
    logger.info("=" * 60)
    try:
        module_main()
        logger.info("COMPLETED STEP: %s", step_name)
    except Exception as e:
        logger.error("FAILED STEP: %s — %s", step_name, str(e), exc_info=True)
        raise


def main():
    """Execute all ingestion steps in dependency order."""
    logger.info("CDW → Delta Lake Migration Pipeline — Starting")

    # Step 1: Borrowers (dimension — no dependencies)
    from ingest_borrowers import main as ingest_borrowers_main
    run_step("1/4 — Borrowers (CDW_BORR_MSTR → borrowers)", ingest_borrowers_main)

    # Step 2: Loan Products (dimension — no dependencies)
    from ingest_loan_products import main as ingest_loan_products_main
    run_step("2/4 — Loan Products (CDW_LN_PROD → loan_products)", ingest_loan_products_main)

    # Step 3: Loan Accounts (fact — depends on borrowers + loan_products)
    from ingest_loan_accounts import main as ingest_loan_accounts_main
    run_step("3/4 — Loan Accounts (CDW_LN_ACCT → loan_accounts)", ingest_loan_accounts_main)

    # Step 4: Payments (fact — depends on loan_accounts)
    from ingest_payments import main as ingest_payments_main
    run_step("4/4 — Payments (CDW_PMT_HIST → payments)", ingest_payments_main)

    logger.info("=" * 60)
    logger.info("CDW → Delta Lake Migration Pipeline — ALL STEPS COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
