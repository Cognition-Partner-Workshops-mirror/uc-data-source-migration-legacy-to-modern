"""Orchestrator script to run the full CDW-to-Delta ingestion pipeline.

Executes each table ingestion in dependency order:
  1. borrowers      (no dependencies)
  2. loan_products  (no dependencies)
  3. loan_accounts  (depends on borrowers + loan_products for FK resolution)
  4. payments       (depends on loan_accounts for FK resolution)

Usage (Databricks notebook or job):
    from databricks.ingestion.run_all import run_pipeline
    results = run_pipeline(spark, base_source_path="/mnt/legacy-extract/")
"""

from datetime import datetime

from pyspark.sql import SparkSession

from databricks.ingestion.ingest_borrowers import run as ingest_borrowers
from databricks.ingestion.ingest_loan_accounts import run as ingest_loan_accounts
from databricks.ingestion.ingest_loan_products import run as ingest_loan_products
from databricks.ingestion.ingest_payments import run as ingest_payments


def run_pipeline(
    spark: SparkSession,
    base_source_path: str,
    file_format: str = "csv",
    quarantine_base: str | None = None,
) -> dict:
    """Run the complete ingestion pipeline in dependency order.

    Parameters
    ----------
    spark : SparkSession
        Active Spark session.
    base_source_path : str
        Root path containing source extracts. Expected sub-paths:
          {base_source_path}/cdw_borr_mstr/
          {base_source_path}/cdw_ln_prod/
          {base_source_path}/cdw_ln_acct/
          {base_source_path}/cdw_pmt_hist/
    file_format : str
        Source file format — ``csv`` or ``parquet``.
    quarantine_base : str or None
        If provided, quarantined rows are written under this path.

    Returns
    -------
    dict
        Summary of all ingestion results keyed by table name.
    """
    results = {}
    pipeline_start = datetime.utcnow()
    base = base_source_path.rstrip("/")
    qbase = quarantine_base.rstrip("/") if quarantine_base else None

    print("=" * 70)
    print("CDW-TO-DELTA LAKE MIGRATION PIPELINE")
    print(f"Started at: {pipeline_start.isoformat()}")
    print(f"Source path: {base}")
    print(f"File format: {file_format}")
    print("=" * 70)

    # Step 1: Borrowers (dimension, no FK dependencies)
    print("\n>>> STEP 1/4: Ingesting borrowers...")
    results["borrowers"] = ingest_borrowers(
        spark,
        source_path=f"{base}/cdw_borr_mstr/",
        file_format=file_format,
        quarantine_path=f"{qbase}/borrowers/" if qbase else None,
    )

    # Step 2: Loan Products (dimension, no FK dependencies)
    print("\n>>> STEP 2/4: Ingesting loan products...")
    results["loan_products"] = ingest_loan_products(
        spark,
        source_path=f"{base}/cdw_ln_prod/",
        file_format=file_format,
        quarantine_path=f"{qbase}/loan_products/" if qbase else None,
    )

    # Step 3: Loan Accounts (depends on borrowers + loan_products)
    print("\n>>> STEP 3/4: Ingesting loan accounts...")
    results["loan_accounts"] = ingest_loan_accounts(
        spark,
        source_path=f"{base}/cdw_ln_acct/",
        file_format=file_format,
        quarantine_path=f"{qbase}/loan_accounts/" if qbase else None,
    )

    # Step 4: Payments (depends on loan_accounts)
    print("\n>>> STEP 4/4: Ingesting payments...")
    results["payments"] = ingest_payments(
        spark,
        source_path=f"{base}/cdw_pmt_hist/",
        file_format=file_format,
        quarantine_path=f"{qbase}/payments/" if qbase else None,
    )

    pipeline_end = datetime.utcnow()
    elapsed = (pipeline_end - pipeline_start).total_seconds()

    print("\n" + "=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)
    total_source = 0
    total_loaded = 0
    total_quarantined = 0
    for table_name, stats in results.items():
        total_source += stats["source_count"]
        total_loaded += stats["loaded_count"]
        total_quarantined += stats["quarantined_count"]
        print(
            f"  {table_name:20s}  source={stats['source_count']:>8d}  "
            f"loaded={stats['loaded_count']:>8d}  "
            f"quarantined={stats['quarantined_count']:>5d}"
        )
    print(f"\n  {'TOTAL':20s}  source={total_source:>8d}  "
          f"loaded={total_loaded:>8d}  quarantined={total_quarantined:>5d}")
    print(f"\n  Elapsed: {elapsed:.1f}s")
    print("=" * 70)

    results["_pipeline"] = {
        "start_time": pipeline_start.isoformat(),
        "end_time": pipeline_end.isoformat(),
        "elapsed_seconds": elapsed,
        "total_source": total_source,
        "total_loaded": total_loaded,
        "total_quarantined": total_quarantined,
    }

    return results
