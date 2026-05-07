"""
Orchestrator script: runs the full CDW -> Delta Lake ingestion pipeline in order.

Execution order matters because of FK resolution dependencies:
1. borrowers       (no dependencies)
2. loan_products   (no dependencies)
3. loan_accounts   (depends on borrowers + loan_products for FK resolution)
4. payments        (depends on loan_accounts for FK resolution)

Usage:
    In a Databricks notebook or as a standalone PySpark job:
        %run ./run_pipeline

    Or from CLI:
        spark-submit run_pipeline.py
"""

from pyspark.sql import SparkSession
import logging
import sys

# Configure logging for the migration pipeline
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("cdw_migration")


def create_database(spark: SparkSession):
    """Create the target database/schema if it doesn't exist."""
    spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")
    logger.info("Database loan_warehouse ensured")


def run_ddl(spark: SparkSession, ddl_path: str):
    """
    Execute Delta Lake DDL scripts to create target tables.

    Reads each .sql file and executes it against the Spark session.
    Tables use IF NOT EXISTS so this is safe to re-run.
    """
    import os
    ddl_files = sorted([f for f in os.listdir(ddl_path) if f.endswith(".sql")])
    for ddl_file in ddl_files:
        filepath = os.path.join(ddl_path, ddl_file)
        with open(filepath, "r") as f:
            sql = f.read()
        # Skip comment-only lines and execute the CREATE TABLE statement
        spark.sql(sql)
        logger.info(f"Executed DDL: {ddl_file}")


def run_full_pipeline(spark: SparkSession):
    """
    Run the complete ingestion pipeline in dependency order.

    Each step is logged with timing information. If any step fails,
    the error is logged and the pipeline halts (fail-fast) so that
    downstream tables don't ingest stale or incomplete data.
    """
    from datetime import datetime

    # Import ingestion modules (order matters for FK resolution)
    import ingest_borrowers
    import ingest_loan_products
    import ingest_loan_accounts
    import ingest_payments

    pipeline_steps = [
        ("1/4 - Borrowers", ingest_borrowers.run),
        ("2/4 - Loan Products", ingest_loan_products.run),
        ("3/4 - Loan Accounts", ingest_loan_accounts.run),
        ("4/4 - Payments", ingest_payments.run),
    ]

    pipeline_start = datetime.now()
    logger.info("=" * 60)
    logger.info("CDW -> Delta Lake Migration Pipeline STARTING")
    logger.info("=" * 60)

    for step_name, step_fn in pipeline_steps:
        step_start = datetime.now()
        logger.info(f"[{step_name}] Starting...")
        try:
            step_fn(spark)
            elapsed = (datetime.now() - step_start).total_seconds()
            logger.info(f"[{step_name}] Completed in {elapsed:.1f}s")
        except Exception as e:
            elapsed = (datetime.now() - step_start).total_seconds()
            logger.error(f"[{step_name}] FAILED after {elapsed:.1f}s: {e}")
            raise  # Fail-fast: don't proceed to dependent steps

    total_elapsed = (datetime.now() - pipeline_start).total_seconds()
    logger.info("=" * 60)
    logger.info(f"CDW -> Delta Lake Migration Pipeline COMPLETE in {total_elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Full_Migration").getOrCreate()

    # Create target database
    create_database(spark)

    # Run the full ingestion pipeline
    run_full_pipeline(spark)

    spark.stop()
