"""
Orchestrator: Runs the full CDW legacy-to-modern migration pipeline in order.

Execution order:
1. Borrowers (dimension table, no dependencies)
2. Loan Products (dimension table, no dependencies)
3. Loan Accounts (depends on borrowers + loan_products for FK resolution)
4. Payments (depends on loan_accounts for FK resolution)

Usage:
    spark-submit run_pipeline.py <base_source_path>

    The base_source_path should contain:
      - CDW_BORR_MSTR.csv (or .parquet)
      - CDW_LN_PROD.csv (or .parquet)
      - CDW_LN_ACCT.csv (or .parquet)
      - CDW_PMT_HIST.csv (or .parquet)
"""

import sys
import os
import time

from common import get_spark, logger

import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments


def detect_source_file(base_path: str, table_name: str) -> str:
    """Detect whether source is CSV or Parquet."""
    for ext in [".parquet", ".csv"]:
        path = os.path.join(base_path, f"{table_name}{ext}")
        if os.path.exists(path):
            return path
    # Default to CSV
    return os.path.join(base_path, f"{table_name}.csv")


def run_full_pipeline(base_source_path: str):
    """Execute the full migration pipeline."""
    start_time = time.time()
    logger.info("=" * 70)
    logger.info("CDW LEGACY TO MODERN DELTA LAKE MIGRATION PIPELINE")
    logger.info("=" * 70)

    # Step 1: Borrowers
    logger.info("-" * 70)
    logger.info("STEP 1/4: Ingesting Borrowers")
    logger.info("-" * 70)
    borrower_path = detect_source_file(base_source_path, "CDW_BORR_MSTR")
    ingest_borrowers.run(borrower_path)

    # Step 2: Loan Products
    logger.info("-" * 70)
    logger.info("STEP 2/4: Ingesting Loan Products")
    logger.info("-" * 70)
    products_path = detect_source_file(base_source_path, "CDW_LN_PROD")
    ingest_loan_products.run(products_path)

    # Step 3: Loan Accounts
    logger.info("-" * 70)
    logger.info("STEP 3/4: Ingesting Loan Accounts")
    logger.info("-" * 70)
    accounts_path = detect_source_file(base_source_path, "CDW_LN_ACCT")
    ingest_loan_accounts.run(accounts_path)

    # Step 4: Payments
    logger.info("-" * 70)
    logger.info("STEP 4/4: Ingesting Payments")
    logger.info("-" * 70)
    payments_path = detect_source_file(base_source_path, "CDW_PMT_HIST")
    ingest_payments.run(payments_path)

    elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info(f"PIPELINE COMPLETE in {elapsed:.2f} seconds")
    logger.info("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: spark-submit run_pipeline.py <base_source_path>")
        print("")
        print("Expected source files in base_source_path:")
        print("  CDW_BORR_MSTR.csv or CDW_BORR_MSTR.parquet")
        print("  CDW_LN_PROD.csv or CDW_LN_PROD.parquet")
        print("  CDW_LN_ACCT.csv or CDW_LN_ACCT.parquet")
        print("  CDW_PMT_HIST.csv or CDW_PMT_HIST.parquet")
        sys.exit(1)

    run_full_pipeline(sys.argv[1])
