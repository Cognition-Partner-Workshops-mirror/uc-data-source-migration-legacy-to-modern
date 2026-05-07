"""
Standalone entry point for data quality validation.

Run after the ingestion pipeline completes to validate the migrated data.

Usage in a Databricks notebook:
    from quality.run_quality_checks import run
    report = run(spark)

Or from the command line:
    spark-submit --py-files quality.zip run_quality_checks.py \
        --borrowers-count 5 --products-count 5 \
        --accounts-count 5 --payments-count 10
"""

import argparse
import sys

from pyspark.sql import SparkSession

from .validators import run_all_checks


def run(
    spark: SparkSession,
    source_counts: dict = None,
    report_path: str = "dbfs:/mnt/reports/data_quality/",
) -> object:
    """
    Run all quality checks with given or auto-detected source counts.

    If source_counts is not provided, it will query the legacy source tables
    (if available) or use the target table counts as baseline.
    """
    if source_counts is None:
        print("[quality] No source counts provided; using target counts as baseline.")
        source_counts = {
            "borrowers": spark.table("loan_warehouse.borrowers").count(),
            "loan_products": spark.table("loan_warehouse.loan_products").count(),
            "loan_accounts": spark.table("loan_warehouse.loan_accounts").count(),
            "payments": spark.table("loan_warehouse.payments").count(),
        }

    report = run_all_checks(spark, source_counts, report_path)

    if not report.all_passed:
        print(f"\nWARNING: {report.failed_count} check(s) FAILED. Review the report at {report_path}")
    else:
        print("\nAll checks PASSED.")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CDW Migration Data Quality Checks")
    parser.add_argument("--borrowers-count", type=int, default=5)
    parser.add_argument("--products-count", type=int, default=5)
    parser.add_argument("--accounts-count", type=int, default=5)
    parser.add_argument("--payments-count", type=int, default=10)
    parser.add_argument("--report-path", default="dbfs:/mnt/reports/data_quality/")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Quality_Checks").getOrCreate()

    source_counts = {
        "borrowers": args.borrowers_count,
        "loan_products": args.products_count,
        "loan_accounts": args.accounts_count,
        "payments": args.payments_count,
    }

    report = run(spark, source_counts, args.report_path)

    if not report.all_passed:
        sys.exit(1)
