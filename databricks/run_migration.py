"""
Migration Pipeline Orchestrator
=================================
Coordinates the execution of all ingestion scripts in the correct order
and runs data quality checks upon completion.

Execution Order (dependency-driven):
  1. Borrowers (no dependencies)
  2. Loan Products (no dependencies)
  3. Loan Accounts (depends on borrowers + loan_products for FK resolution)
  4. Payments (depends on loan_accounts for FK resolution)
  5. Data Quality Checks (depends on all tables being populated)

Usage:
  spark-submit run_migration.py
  -- or run as a Databricks notebook --
"""

from pyspark.sql import SparkSession
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_migration")


def create_spark_session():
    """Initialize SparkSession with Delta Lake support."""
    return (
        SparkSession.builder
        .appName("LoanMigration_FullPipeline")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )


def create_database(spark):
    """Create the target database if it does not exist."""
    logger.info("Creating target database: loan_warehouse")
    spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")
    spark.sql("USE loan_warehouse")


def run_step(step_name, module_func):
    """Run a pipeline step with error handling and logging."""
    logger.info(f"{'=' * 60}")
    logger.info(f"STEP: {step_name}")
    logger.info(f"{'=' * 60}")
    try:
        module_func()
        logger.info(f"STEP COMPLETED: {step_name}")
        return True
    except Exception as e:
        logger.error(f"STEP FAILED: {step_name} - {str(e)}")
        raise


def main():
    """
    Main orchestrator: runs all pipeline stages in dependency order.
    Stops on first failure to prevent cascading errors.
    """
    logger.info("=" * 70)
    logger.info("  LEGACY CDW → DELTA LAKE MIGRATION PIPELINE")
    logger.info("=" * 70)

    spark = create_spark_session()
    create_database(spark)
    spark.stop()

    # Import and run each ingestion step in order
    # Step 1: Ingest Borrowers (no dependencies)
    from ingestion.ingest_borrowers import main as ingest_borrowers
    run_step("Ingest Borrowers (CDW_BORR_MSTR → borrowers)", ingest_borrowers)

    # Step 2: Ingest Loan Products (no dependencies)
    from ingestion.ingest_loan_products import main as ingest_loan_products
    run_step("Ingest Loan Products (CDW_LN_PROD → loan_products)", ingest_loan_products)

    # Step 3: Ingest Loan Accounts (depends on borrowers + loan_products)
    from ingestion.ingest_loan_accounts import main as ingest_loan_accounts
    run_step("Ingest Loan Accounts (CDW_LN_ACCT → loan_accounts)", ingest_loan_accounts)

    # Step 4: Ingest Payments (depends on loan_accounts)
    from ingestion.ingest_payments import main as ingest_payments
    run_step("Ingest Payments (CDW_PMT_HIST → payments)", ingest_payments)

    # Step 5: Run Data Quality Checks
    from quality.data_quality_checks import main as run_quality_checks
    run_step("Data Quality Validation", run_quality_checks)

    logger.info("=" * 70)
    logger.info("  MIGRATION PIPELINE COMPLETED SUCCESSFULLY")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
