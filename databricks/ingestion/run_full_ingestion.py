"""
Orchestrator script: runs the full CDW legacy-to-modern ingestion pipeline.

Executes ingestion in the correct dependency order:
  1. borrowers     (no FK dependencies)
  2. loan_products (no FK dependencies)
  3. loan_accounts (depends on borrowers + loan_products for FK resolution)
  4. payments      (depends on loan_accounts for FK resolution)

Usage (Databricks notebook cell):
    %run ./run_full_ingestion

Or as a standalone script:
    spark-submit --master local[*] run_full_ingestion.py \
        --base-path /mnt/landing/cdw/ \
        --source-format csv
"""

import argparse
import logging
import time

from pyspark.sql import SparkSession

from ingest_borrowers import read_legacy_borrowers, transform_borrowers, write_borrowers
from ingest_loan_products import (
    read_legacy_loan_products, transform_loan_products, write_loan_products,
)
from ingest_loan_accounts import (
    read_legacy_loan_accounts, transform_loan_accounts, write_loan_accounts,
)
from ingest_payments import read_legacy_payments, transform_payments, write_payments

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("cdw_migration.orchestrator")


def run_pipeline(spark: SparkSession, base_path: str, source_format: str = "csv") -> dict:
    """
    Execute the full ingestion pipeline in dependency order.
    Returns a summary dict with row counts and elapsed times per table.
    """
    summary = {}

    # -----------------------------------------------------------------------
    # Step 1: Borrowers (no FK dependencies)
    # -----------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 1/4: Ingesting borrowers (CDW_BORR_MSTR)")
    logger.info("=" * 60)
    t0 = time.time()
    borr_df = read_legacy_borrowers(spark, f"{base_path}/cdw_borr_mstr", source_format)
    borr_transformed = transform_borrowers(borr_df)
    write_borrowers(borr_transformed)
    summary["borrowers"] = {"rows": borr_transformed.count(), "elapsed_sec": round(time.time() - t0, 2)}

    # -----------------------------------------------------------------------
    # Step 2: Loan Products (no FK dependencies)
    # -----------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 2/4: Ingesting loan products (CDW_LN_PROD)")
    logger.info("=" * 60)
    t0 = time.time()
    prod_df = read_legacy_loan_products(spark, f"{base_path}/cdw_ln_prod", source_format)
    prod_transformed = transform_loan_products(prod_df)
    write_loan_products(prod_transformed)
    summary["loan_products"] = {"rows": prod_transformed.count(), "elapsed_sec": round(time.time() - t0, 2)}

    # -----------------------------------------------------------------------
    # Step 3: Loan Accounts (depends on borrowers + loan_products)
    # -----------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 3/4: Ingesting loan accounts (CDW_LN_ACCT)")
    logger.info("=" * 60)
    t0 = time.time()
    acct_df = read_legacy_loan_accounts(spark, f"{base_path}/cdw_ln_acct", source_format)
    acct_transformed = transform_loan_accounts(acct_df, spark)
    write_loan_accounts(acct_transformed)
    summary["loan_accounts"] = {"rows": acct_transformed.count(), "elapsed_sec": round(time.time() - t0, 2)}

    # -----------------------------------------------------------------------
    # Step 4: Payments (depends on loan_accounts)
    # -----------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STEP 4/4: Ingesting payments (CDW_PMT_HIST)")
    logger.info("=" * 60)
    t0 = time.time()
    pmt_df = read_legacy_payments(spark, f"{base_path}/cdw_pmt_hist", source_format)
    pmt_transformed = transform_payments(pmt_df, spark)
    write_payments(pmt_transformed)
    summary["payments"] = {"rows": pmt_transformed.count(), "elapsed_sec": round(time.time() - t0, 2)}

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("INGESTION PIPELINE COMPLETE")
    for table, stats in summary.items():
        logger.info("  %-20s %5d rows  (%0.1fs)", table, stats["rows"], stats["elapsed_sec"])
    logger.info("=" * 60)

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full CDW ingestion pipeline")
    parser.add_argument(
        "--base-path", required=True,
        help="Base path containing sub-directories for each legacy table extract "
             "(cdw_borr_mstr/, cdw_ln_prod/, cdw_ln_acct/, cdw_pmt_hist/)",
    )
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    args = parser.parse_args()

    spark = (
        SparkSession.builder
        .appName("CDW_Full_Ingestion_Pipeline")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )

    run_pipeline(spark, args.base_path, args.source_format)
    spark.stop()
