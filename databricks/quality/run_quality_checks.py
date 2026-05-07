"""
Databricks notebook / job entry point for running data quality checks.

Reads source counts from a configuration or computes them from legacy
extracts, executes all quality checks, and writes the report to DBFS.

Usage (Databricks notebook):
    dbutils.widgets.text("report_path",
        "dbfs:/mnt/reports/DATA_QUALITY_REPORT.md")
    %run ./run_quality_checks
"""

from pyspark.sql import SparkSession

from data_quality_checks import generate_report, run_all_checks

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# These counts should match the legacy source extracts.
# Update them before each run, or compute dynamically from source files.
SOURCE_COUNTS = {
    "CDW_BORR_MSTR": 5,
    "CDW_LN_PROD": 5,
    "CDW_LN_ACCT": 5,
    "CDW_PMT_HIST": 10,
}

REPORT_OUTPUT_PATH = "/dbfs/mnt/reports/DATA_QUALITY_REPORT.md"


def main() -> None:
    spark = SparkSession.builder.getOrCreate()

    print("=" * 72)
    print("DATA QUALITY VALIDATION")
    print("=" * 72)

    report = run_all_checks(spark, source_counts=SOURCE_COUNTS)
    md = generate_report(report, output_path=REPORT_OUTPUT_PATH)

    print("\n" + md)

    if report.failed > 0:
        print(f"\nWARNING: {report.failed} quality check(s) failed!")
    else:
        print("\nAll quality checks passed.")


if __name__ == "__main__":
    main()
