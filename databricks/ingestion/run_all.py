"""
Master orchestrator: runs all ingestion scripts in dependency order.

Execution order (respects FK dependencies):
  1. borrowers      (no dependencies)
  2. loan_products  (no dependencies)
  3. loan_accounts  (depends on borrowers, loan_products)
  4. payments       (depends on loan_accounts)

Logs a summary audit record to loan_warehouse.migration_audit_log after each step.
"""

import time
import uuid
from datetime import datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

try:
    import ingest_borrowers
    import ingest_loan_products
    import ingest_loan_accounts
    import ingest_payments
except ImportError:
    pass


def create_schema(spark: SparkSession) -> None:
    """Create the target catalog/schema if it doesn't exist."""
    spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")


def log_audit(spark: SparkSession, run_id: str, source: str, target: str,
              source_count: int, target_count: int, status: str,
              error_msg: str, duration: float) -> None:
    """Append an audit record to the migration audit log."""
    audit_df = spark.createDataFrame(
        [(run_id, datetime.utcnow(), source, target,
          source_count, target_count, 0, 0,
          status, error_msg, duration)],
        schema=[
            "run_id", "run_timestamp", "source_table", "target_table",
            "source_row_count", "target_row_count",
            "rejected_row_count", "warnings_count",
            "status", "error_message", "duration_seconds",
        ],
    )
    (
        audit_df.write
        .format("delta")
        .mode("append")
        .saveAsTable("loan_warehouse.migration_audit_log")
    )


def run_step(spark: SparkSession, run_id: str, name: str, source: str,
             target: str, func) -> bool:
    """Execute one ingestion step with timing and error handling."""
    print(f"\n{'='*70}")
    print(f"STEP: {name}")
    print(f"{'='*70}")

    start = time.time()
    try:
        count = func(spark)
        duration = time.time() - start
        log_audit(spark, run_id, source, target, count, count, "SUCCESS", None, duration)
        print(f"COMPLETED {name} in {duration:.1f}s ({count} rows)")
        return True
    except Exception as e:
        duration = time.time() - start
        error_msg = str(e)[:500]
        log_audit(spark, run_id, source, target, 0, 0, "FAILED", error_msg, duration)
        print(f"FAILED {name} after {duration:.1f}s: {error_msg}")
        return False


def main():
    spark = SparkSession.builder.appName("CDW_Migration_Pipeline").getOrCreate()
    run_id = str(uuid.uuid4())

    print(f"Migration run ID: {run_id}")
    print(f"Started at: {datetime.utcnow().isoformat()}")

    create_schema(spark)

    steps = [
        ("Ingest Borrowers", "CDW_BORR_MSTR", "loan_warehouse.borrowers",
         ingest_borrowers.run),
        ("Ingest Loan Products", "CDW_LN_PROD", "loan_warehouse.loan_products",
         ingest_loan_products.run),
        ("Ingest Loan Accounts", "CDW_LN_ACCT", "loan_warehouse.loan_accounts",
         ingest_loan_accounts.run),
        ("Ingest Payments", "CDW_PMT_HIST", "loan_warehouse.payments",
         ingest_payments.run),
    ]

    results = []
    for name, source, target, func in steps:
        success = run_step(spark, run_id, name, source, target, func)
        results.append((name, success))
        if not success:
            print(f"\nABORTING: {name} failed. Downstream steps skipped.")
            break

    print(f"\n{'='*70}")
    print("MIGRATION SUMMARY")
    print(f"{'='*70}")
    for name, success in results:
        status = "OK" if success else "FAILED"
        print(f"  {status:6s}  {name}")

    all_ok = all(s for _, s in results)
    print(f"\nOverall: {'SUCCESS' if all_ok else 'FAILED'}")
    print(f"Run ID: {run_id}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    exit(main())
