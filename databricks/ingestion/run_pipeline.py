"""
Orchestrator: Run the full CDW -> Delta Lake migration pipeline.

Executes ingestion in dependency order:
    1. Borrowers (no dependencies)
    2. Loan Products (no dependencies)
    3. Loan Accounts (references borrowers, loan_products)
    4. Payments (references loan_accounts)

Usage (Databricks notebook or CLI):
    %run ./run_pipeline

    Or from a Databricks job:
        spark-submit --py-files databricks/ingestion/*.py databricks/ingestion/run_pipeline.py \
            --source-dir /mnt/landing/cdw_export/ \
            --source-format csv
"""

import argparse
import sys
import time
from pyspark.sql import SparkSession
from databricks.ingestion import (
    ingest_borrowers,
    ingest_loan_products,
    ingest_loan_accounts,
    ingest_payments,
)
from databricks.ingestion.transforms import logger


def get_spark() -> SparkSession:
    """Get or create a SparkSession configured for Delta Lake."""
    return (
        SparkSession.builder
        .appName("CDW_to_DeltaLake_Migration")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.databricks.delta.optimizeWrite.enabled", "true")
        .config("spark.databricks.delta.autoCompact.enabled", "true")
        .getOrCreate()
    )


def run_pipeline(source_dir: str, source_format: str = "csv",
                 write_mode: str = "overwrite"):
    """Run the full migration pipeline in dependency order.

    Args:
        source_dir: Base directory containing legacy table exports.
                    Expected subdirectories: CDW_BORR_MSTR/, CDW_LN_PROD/,
                    CDW_LN_ACCT/, CDW_PMT_HIST/
        source_format: 'csv' or 'parquet'.
        write_mode: 'overwrite' for initial load, 'append' for incremental.
    """
    spark = get_spark()
    start_time = time.time()

    results = {}

    # Step 1: Borrowers (no dependencies)
    logger.info("=" * 70)
    logger.info("STEP 1/4: Ingesting borrowers")
    logger.info("=" * 70)
    results["borrowers"] = ingest_borrowers.run(
        spark,
        source_path=f"{source_dir}/CDW_BORR_MSTR/",
        source_format=source_format,
        write_mode=write_mode,
    )

    # Step 2: Loan Products (no dependencies)
    logger.info("=" * 70)
    logger.info("STEP 2/4: Ingesting loan products")
    logger.info("=" * 70)
    results["loan_products"] = ingest_loan_products.run(
        spark,
        source_path=f"{source_dir}/CDW_LN_PROD/",
        source_format=source_format,
        write_mode=write_mode,
    )

    # Step 3: Loan Accounts (depends on borrowers, loan_products)
    logger.info("=" * 70)
    logger.info("STEP 3/4: Ingesting loan accounts")
    logger.info("=" * 70)
    results["loan_accounts"] = ingest_loan_accounts.run(
        spark,
        source_path=f"{source_dir}/CDW_LN_ACCT/",
        source_format=source_format,
        write_mode=write_mode,
    )

    # Step 4: Payments (depends on loan_accounts)
    logger.info("=" * 70)
    logger.info("STEP 4/4: Ingesting payments")
    logger.info("=" * 70)
    results["payments"] = ingest_payments.run(
        spark,
        source_path=f"{source_dir}/CDW_PMT_HIST/",
        source_format=source_format,
        write_mode=write_mode,
    )

    elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETE in %.1f seconds", elapsed)
    logger.info("=" * 70)

    # Summary
    total_quarantined = 0
    for table_name, (valid_df, quarantine_df) in results.items():
        q_count = quarantine_df.count()
        total_quarantined += q_count
        logger.info("  %s: %d loaded, %d quarantined", table_name, valid_df.count(), q_count)

    if total_quarantined > 0:
        logger.warning("TOTAL QUARANTINED ROWS: %d — review quarantine logs", total_quarantined)
    else:
        logger.info("No rows quarantined. All records migrated successfully.")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CDW to Delta Lake migration pipeline")
    parser.add_argument("--source-dir", required=True,
                        help="Base directory containing legacy table exports")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"],
                        help="Source file format (default: csv)")
    parser.add_argument("--write-mode", default="overwrite", choices=["overwrite", "append"],
                        help="Write mode (default: overwrite)")
    args = parser.parse_args()

    run_pipeline(args.source_dir, args.source_format, args.write_mode)
