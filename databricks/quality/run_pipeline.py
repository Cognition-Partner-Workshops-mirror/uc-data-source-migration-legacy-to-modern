"""
Migration Pipeline Orchestrator.

Runs the full ingestion pipeline in the correct order, then executes
data quality checks and generates the report.

Usage in Databricks:
    %run ./run_pipeline
"""

from pyspark.sql import SparkSession

# Import ingestion modules
import sys
sys.path.insert(0, "../ingestion")

from ingest_borrowers import run as ingest_borrowers
from ingest_loan_products import run as ingest_loan_products
from ingest_loan_accounts import run as ingest_loan_accounts
from ingest_payments import run as ingest_payments
from data_quality_checks import run_all_checks


def run_pipeline(spark: SparkSession) -> None:
    """Execute the complete migration pipeline."""
    print("=" * 60)
    print("LEGACY CDW → DELTA LAKE MIGRATION PIPELINE")
    print("=" * 60)

    # Phase 1: Create database
    spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")

    # Phase 2: Ingestion (order matters — dimension tables before fact tables)
    print("\n--- Phase 2: Ingestion ---\n")

    summaries = {}

    # Step 1: Borrowers (dimension)
    result = ingest_borrowers(spark)
    summaries[result["table"]] = result["source_count"]

    # Step 2: Loan Products (dimension)
    result = ingest_loan_products(spark)
    summaries[result["table"]] = result["source_count"]

    # Step 3: Loan Accounts (fact — depends on borrowers + loan_products)
    result = ingest_loan_accounts(spark)
    summaries[result["table"]] = result["source_count"]

    # Step 4: Payments (fact — depends on loan_accounts)
    result = ingest_payments(spark)
    summaries[result["table"]] = result["source_count"]

    # Phase 3: Data Quality Checks
    print("\n--- Phase 3: Data Quality Checks ---\n")
    report = run_all_checks(spark, summaries)

    # Phase 4: Summary
    print("\n--- Pipeline Complete ---\n")
    if report.failed_checks > 0:
        print(f"WARNING: {report.failed_checks} quality checks failed. Review the report.")
    else:
        print("All quality checks passed.")

    return report


if __name__ == "__main__":
    spark = SparkSession.builder.appName("MigrationPipeline").getOrCreate()
    run_pipeline(spark)
