"""
Migration Pipeline Orchestrator

Runs the full ingestion pipeline in the correct dependency order:
1. borrowers (no dependencies)
2. loan_products (no dependencies)
3. loan_accounts (depends on borrowers + loan_products for FK resolution)
4. payments (depends on loan_accounts for FK resolution)

Usage:
    spark-submit run_pipeline.py <base_source_path> [file_format]

Example:
    spark-submit run_pipeline.py /mnt/legacy-export/ csv
    spark-submit run_pipeline.py dbfs:/FileStore/legacy/ parquet
"""

import json
import sys
from datetime import datetime

from pyspark.sql import SparkSession

from .ingest_borrowers import ingest_borrowers
from .ingest_loan_accounts import ingest_loan_accounts
from .ingest_loan_products import ingest_loan_products
from .ingest_payments import ingest_payments


def run_full_pipeline(spark: SparkSession, base_path: str,
                      file_format: str = "csv") -> dict:
    """Execute the full migration pipeline in dependency order.

    Args:
        spark: Active SparkSession
        base_path: Base path containing subdirectories for each source table
        file_format: Source format ('csv' or 'parquet')

    Returns:
        dict with overall results and per-table metrics
    """
    start_time = datetime.now()
    results = []
    errors = []

    # Create target database if not exists
    spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")

    print("=" * 70)
    print(f"MIGRATION PIPELINE STARTED: {start_time.isoformat()}")
    print(f"Source base path: {base_path}")
    print(f"File format: {file_format}")
    print("=" * 70)

    # Step 1: Borrowers (independent)
    print("\n[STEP 1/4] Ingesting borrowers...")
    try:
        r = ingest_borrowers(spark, f"{base_path}/CDW_BORR_MSTR/", file_format)
        results.append(r)
    except Exception as e:
        errors.append({"table": "borrowers", "error": str(e)})
        print(f"[ERROR] Borrower ingestion failed: {e}")

    # Step 2: Loan Products (independent)
    print("\n[STEP 2/4] Ingesting loan products...")
    try:
        r = ingest_loan_products(spark, f"{base_path}/CDW_LN_PROD/", file_format)
        results.append(r)
    except Exception as e:
        errors.append({"table": "loan_products", "error": str(e)})
        print(f"[ERROR] Loan product ingestion failed: {e}")

    # Step 3: Loan Accounts (depends on borrowers + loan_products)
    print("\n[STEP 3/4] Ingesting loan accounts...")
    try:
        r = ingest_loan_accounts(spark, f"{base_path}/CDW_LN_ACCT/", file_format)
        results.append(r)
    except Exception as e:
        errors.append({"table": "loan_accounts", "error": str(e)})
        print(f"[ERROR] Loan account ingestion failed: {e}")

    # Step 4: Payments (depends on loan_accounts)
    print("\n[STEP 4/4] Ingesting payments...")
    try:
        r = ingest_payments(spark, f"{base_path}/CDW_PMT_HIST/", file_format)
        results.append(r)
    except Exception as e:
        errors.append({"table": "payments", "error": str(e)})
        print(f"[ERROR] Payment ingestion failed: {e}")

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Summary
    total_source = sum(r["source_count"] for r in results)
    total_target = sum(r["target_count"] for r in results)
    total_quarantined = sum(r["quarantined_count"] for r in results)

    summary = {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_seconds": duration,
        "tables_processed": len(results),
        "tables_failed": len(errors),
        "total_source_records": total_source,
        "total_target_records": total_target,
        "total_quarantined_records": total_quarantined,
        "table_results": results,
        "errors": errors,
    }

    print("\n" + "=" * 70)
    print("MIGRATION PIPELINE COMPLETE")
    print(f"Duration: {duration:.1f}s")
    print(f"Tables processed: {len(results)}/{len(results) + len(errors)}")
    print(f"Total records: {total_source} source -> {total_target} target "
          f"({total_quarantined} quarantined)")
    if errors:
        print(f"ERRORS: {len(errors)} table(s) failed")
        for err in errors:
            print(f"  - {err['table']}: {err['error']}")
    print("=" * 70)

    return summary


if __name__ == "__main__":
    spark = SparkSession.builder \
        .appName("LoanMigration_FullPipeline") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .getOrCreate()

    base_path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/legacy-export"
    file_format = sys.argv[2] if len(sys.argv) > 2 else "csv"

    summary = run_full_pipeline(spark, base_path, file_format)
    print(f"\n[PIPELINE SUMMARY JSON]\n{json.dumps(summary, indent=2)}")
