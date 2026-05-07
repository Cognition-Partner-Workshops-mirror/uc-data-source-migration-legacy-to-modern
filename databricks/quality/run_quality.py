"""
Standalone entry-point for the data quality checks.

Usage (Databricks notebook):
    # Set widgets / parameters
    dbutils.widgets.text("source_base_path", "dbfs:/mnt/legacy/")
    dbutils.widgets.text("source_format", "csv")
    dbutils.widgets.text("report_path", "dbfs:/mnt/reports/DATA_QUALITY_REPORT.md")

    from quality.run_quality import main
    main(spark)

Or run directly:
    %run ./run_quality
"""

import logging
import sys

from pyspark.sql import SparkSession

# Import the main quality orchestrator that runs all 4 categories of checks
from .data_quality import run_quality_checks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("quality.runner")


def main(
    spark: SparkSession,
    source_base_path: str = "dbfs:/mnt/legacy/",
    source_format: str = "csv",
    report_path: str = "dbfs:/mnt/reports/DATA_QUALITY_REPORT.md",
) -> None:
    """Run all quality checks and write the markdown report; exits with code 1 on failures."""
    # Execute all 4 check categories: row counts, nulls, referential integrity, business rules
    report = run_quality_checks(
        spark=spark,
        source_base_path=source_base_path,
        source_format=source_format,
        report_output_path=report_path,
    )

    print(report.to_markdown())

    if not report.overall_passed:
        logger.error(
            "DATA QUALITY FAILURES DETECTED: %d of %d checks failed",
            report.fail_count,
            len(report.checks),
        )
        sys.exit(1)
    else:
        logger.info("All %d quality checks passed.", len(report.checks))
