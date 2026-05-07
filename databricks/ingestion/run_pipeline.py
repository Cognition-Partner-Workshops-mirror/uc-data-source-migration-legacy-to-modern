"""
Main orchestration script for the legacy CDW to modern Delta Lake migration.
Executes all ingestion steps in the correct dependency order:
1. Borrowers (dimension - no dependencies)
2. Loan Products (dimension - no dependencies)
3. Loan Accounts (fact - depends on borrowers and loan_products)
4. Payments (fact - depends on loan_accounts)
"""

import sys
import time
from datetime import datetime

from common import get_spark, MigrationConfig, logger
from ingest_borrowers import run as run_borrowers
from ingest_loan_products import run as run_loan_products
from ingest_loan_accounts import run as run_loan_accounts
from ingest_payments import run as run_payments


def create_database(config: MigrationConfig):
    """Create the target database if it does not exist."""
    spark = get_spark()
    spark.sql(f"CREATE DATABASE IF NOT EXISTS {config.target_database}")
    logger.info(f"Ensured database exists: {config.target_database}")


def run_ddl_scripts(config: MigrationConfig):
    """Execute DDL scripts to create Delta Lake tables."""
    spark = get_spark()
    ddl_scripts = [
        "databricks/ddl/01_borrowers.sql",
        "databricks/ddl/02_loan_products.sql",
        "databricks/ddl/03_loan_accounts.sql",
        "databricks/ddl/04_payments.sql",
    ]
    for script_path in ddl_scripts:
        logger.info(f"Executing DDL: {script_path}")
        try:
            with open(script_path, "r") as f:
                sql_content = f.read()
            for statement in sql_content.split(";"):
                statement = statement.strip()
                if statement and not statement.startswith("--"):
                    spark.sql(statement)
            logger.info(f"DDL executed successfully: {script_path}")
        except Exception as e:
            logger.error(f"DDL execution failed for {script_path}: {e}")
            raise


def run_full_pipeline(config: MigrationConfig = None):
    """
    Execute the full migration pipeline end-to-end.

    Execution order:
    1. Create target database
    2. Run DDL scripts to create tables
    3. Ingest borrowers (dimension)
    4. Ingest loan products (dimension)
    5. Ingest loan accounts (fact, references borrowers + products)
    6. Ingest payments (fact, references loan accounts)
    """
    if config is None:
        config = MigrationConfig()

    start_time = time.time()
    logger.info("=" * 80)
    logger.info(f"MIGRATION PIPELINE STARTED AT: {datetime.now().isoformat()}")
    logger.info("=" * 80)

    steps = [
        ("Create Database", lambda: create_database(config)),
        ("Execute DDL Scripts", lambda: run_ddl_scripts(config)),
        ("Ingest Borrowers", lambda: run_borrowers(config)),
        ("Ingest Loan Products", lambda: run_loan_products(config)),
        ("Ingest Loan Accounts", lambda: run_loan_accounts(config)),
        ("Ingest Payments", lambda: run_payments(config)),
    ]

    results = []
    for step_name, step_fn in steps:
        step_start = time.time()
        logger.info(f"\n{'>' * 20} Step: {step_name} {'<' * 20}")
        try:
            step_fn()
            elapsed = time.time() - step_start
            results.append((step_name, "SUCCESS", elapsed))
            logger.info(f"Step '{step_name}' completed in {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - step_start
            results.append((step_name, "FAILED", elapsed))
            logger.error(f"Step '{step_name}' FAILED after {elapsed:.2f}s: {e}")
            logger.error("Pipeline halted due to failure.")
            sys.exit(1)

    total_time = time.time() - start_time
    logger.info("\n" + "=" * 80)
    logger.info("MIGRATION PIPELINE SUMMARY")
    logger.info("=" * 80)
    for step_name, status, elapsed in results:
        logger.info(f"  {status:8s} | {elapsed: 7.2f}s | {step_name}")
    logger.info(f"\nTotal pipeline time: {total_time:.2f}s")
    logger.info("=" * 80)


if __name__ == "__main__":
    run_full_pipeline()
