"""
Orchestrator: runs the full legacy → modern ingestion pipeline in dependency order.

Execution order:
  1. borrowers    (no dependencies)
  2. loan_products (no dependencies)
  3. loan_accounts (depends on borrowers + loan_products for FK resolution)
  4. payments      (depends on loan_accounts for FK resolution)

Each step logs source/good/quarantine counts. A summary dict is returned at the end.
"""

import logging
import sys
from datetime import datetime

from pyspark.sql import SparkSession

import ingest_borrowers
import ingest_loan_products
import ingest_loan_accounts
import ingest_payments

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("run_pipeline")


def main():
    spark = SparkSession.builder.appName("Legacy_CDW_Migration_Pipeline").getOrCreate()

    start = datetime.now()
    logger.info("=" * 70)
    logger.info("STARTING LEGACY CDW → MODERN DELTA LAKE MIGRATION")
    logger.info("=" * 70)

    results = {}

    # Step 1: Borrowers (no FK dependencies)
    logger.info("-" * 50)
    logger.info("STEP 1/4: Ingesting borrowers (CDW_BORR_MSTR)")
    logger.info("-" * 50)
    results["borrowers"] = ingest_borrowers.run(spark)

    # Step 2: Loan Products (no FK dependencies)
    logger.info("-" * 50)
    logger.info("STEP 2/4: Ingesting loan products (CDW_LN_PROD)")
    logger.info("-" * 50)
    results["loan_products"] = ingest_loan_products.run(spark)

    # Step 3: Loan Accounts (depends on borrowers + loan_products)
    logger.info("-" * 50)
    logger.info("STEP 3/4: Ingesting loan accounts (CDW_LN_ACCT)")
    logger.info("-" * 50)
    results["loan_accounts"] = ingest_loan_accounts.run(spark)

    # Step 4: Payments (depends on loan_accounts)
    logger.info("-" * 50)
    logger.info("STEP 4/4: Ingesting payments (CDW_PMT_HIST)")
    logger.info("-" * 50)
    results["payments"] = ingest_payments.run(spark)

    elapsed = datetime.now() - start
    logger.info("=" * 70)
    logger.info("MIGRATION COMPLETE in %s", elapsed)
    logger.info("=" * 70)

    # Print summary
    total_source = 0
    total_good = 0
    total_quarantined = 0
    for table, counts in results.items():
        logger.info(
            "  %-20s source=%d  good=%d  quarantined=%d",
            table,
            counts["source_count"],
            counts["good"],
            counts["quarantined"],
        )
        total_source += counts["source_count"]
        total_good += counts["good"]
        total_quarantined += counts["quarantined"]

    logger.info("-" * 50)
    logger.info(
        "  %-20s source=%d  good=%d  quarantined=%d",
        "TOTAL",
        total_source,
        total_good,
        total_quarantined,
    )

    if total_quarantined > 0:
        logger.warning("There were %d quarantined records — review quarantine paths.", total_quarantined)
        sys.exit(1)

    logger.info("All records migrated successfully.")


if __name__ == "__main__":
    main()
