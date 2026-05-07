"""
Master pipeline orchestrator for the CDW -> Delta Lake migration.

Executes all ingestion jobs in dependency order:
  1. borrowers     (no dependencies)
  2. loan_products (no dependencies)
  3. loan_accounts (depends on borrowers, loan_products for FK resolution)
  4. payments      (depends on loan_accounts for FK resolution)

Usage in a Databricks notebook:
    from ingestion.run_pipeline import run_full_pipeline
    results = run_full_pipeline(spark, base_source_path="dbfs:/mnt/landing/cdw/")

Or run as a standalone script:
    spark-submit --py-files ingestion.zip run_pipeline.py \
        --source-path dbfs:/mnt/landing/cdw/ \
        --source-format csv
"""

import argparse
import json
import sys
from datetime import datetime

from pyspark.sql import SparkSession

from .ingest_borrowers import run as ingest_borrowers
from .ingest_loan_products import run as ingest_loan_products
from .ingest_loan_accounts import run as ingest_loan_accounts
from .ingest_payments import run as ingest_payments


def run_full_pipeline(
    spark: SparkSession,
    base_source_path: str,
    source_format: str = "csv",
    write_mode: str = "append",
    quarantine_base: str = "dbfs:/mnt/quarantine/",
) -> dict:
    """
    Run the complete ingestion pipeline in dependency order.

    Parameters:
        spark             : Active SparkSession
        base_source_path  : Root path containing subdirectories per legacy table
                            Expected structure:
                              {base_source_path}/cdw_borr_mstr/
                              {base_source_path}/cdw_ln_prod/
                              {base_source_path}/cdw_ln_acct/
                              {base_source_path}/cdw_pmt_hist/
        source_format     : 'csv' or 'parquet'
        write_mode        : Spark write mode ('append', 'overwrite')
        quarantine_base   : Base path for quarantined/rejected rows

    Returns:
        Dict with per-table ingestion summaries.
    """
    base = base_source_path.rstrip("/")
    qbase = quarantine_base.rstrip("/")
    pipeline_start = datetime.utcnow()
    results = {}

    print("=" * 70)
    print(f"CDW -> Delta Lake Migration Pipeline")
    print(f"Started: {pipeline_start.isoformat()}Z")
    print(f"Source:  {base}")
    print(f"Format:  {source_format}")
    print("=" * 70)

    # Step 1: Borrowers (no dependencies)
    print("\n--- Step 1/4: Ingesting borrowers ---")
    results["borrowers"] = ingest_borrowers(
        spark,
        source_path=f"{base}/cdw_borr_mstr/",
        error_path=f"{qbase}/borrowers/",
        source_format=source_format,
        write_mode=write_mode,
    )

    # Step 2: Loan Products (no dependencies)
    print("\n--- Step 2/4: Ingesting loan_products ---")
    results["loan_products"] = ingest_loan_products(
        spark,
        source_path=f"{base}/cdw_ln_prod/",
        error_path=f"{qbase}/loan_products/",
        source_format=source_format,
        write_mode=write_mode,
    )

    # Step 3: Loan Accounts (depends on borrowers + loan_products)
    print("\n--- Step 3/4: Ingesting loan_accounts ---")
    results["loan_accounts"] = ingest_loan_accounts(
        spark,
        source_path=f"{base}/cdw_ln_acct/",
        error_path=f"{qbase}/loan_accounts/",
        source_format=source_format,
        write_mode=write_mode,
    )

    # Step 4: Payments (depends on loan_accounts)
    print("\n--- Step 4/4: Ingesting payments ---")
    results["payments"] = ingest_payments(
        spark,
        source_path=f"{base}/cdw_pmt_hist/",
        error_path=f"{qbase}/payments/",
        source_format=source_format,
        write_mode=write_mode,
    )

    pipeline_end = datetime.utcnow()
    elapsed = (pipeline_end - pipeline_start).total_seconds()

    print("\n" + "=" * 70)
    print("Pipeline Summary")
    print("=" * 70)
    total_source = sum(r["source_count"] for r in results.values())
    total_valid = sum(r["valid_count"] for r in results.values())
    total_quarantined = sum(r["quarantine_count"] for r in results.values())

    for table_name, summary in results.items():
        print(
            f"  {table_name:20s} | "
            f"source={summary['source_count']:>6d} | "
            f"loaded={summary['valid_count']:>6d} | "
            f"quarantined={summary['quarantine_count']:>4d}"
        )

    print(f"\n  TOTAL               | source={total_source:>6d} | loaded={total_valid:>6d} | quarantined={total_quarantined:>4d}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print("=" * 70)

    results["_pipeline"] = {
        "started_at": pipeline_start.isoformat() + "Z",
        "finished_at": pipeline_end.isoformat() + "Z",
        "elapsed_seconds": elapsed,
        "total_source": total_source,
        "total_valid": total_valid,
        "total_quarantined": total_quarantined,
    }

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CDW to Delta Lake Migration Pipeline")
    parser.add_argument("--source-path", required=True, help="Base DBFS path to legacy CSV/Parquet extracts")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--write-mode", default="append", choices=["append", "overwrite"])
    parser.add_argument("--quarantine-path", default="dbfs:/mnt/quarantine/")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_Pipeline").getOrCreate()

    results = run_full_pipeline(
        spark,
        base_source_path=args.source_path,
        source_format=args.source_format,
        write_mode=args.write_mode,
        quarantine_base=args.quarantine_path,
    )

    print("\nFull results JSON:")
    print(json.dumps(results, indent=2, default=str))
