"""
Standalone runner for data quality checks.

Reads ingestion results from the pipeline summary (or uses defaults
matching the legacy seed data) and runs the full quality suite.
Writes DATA_QUALITY_REPORT.md to the configured output path.
"""

import logging
import sys

from pyspark.sql import SparkSession

from data_quality_checks import run_all_checks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("run_quality_checks")


def main():
    spark = SparkSession.builder.appName("Data_Quality_Runner").getOrCreate()

    # Default source counts matching the legacy seed data
    source_counts = {
        "borrowers": 5,
        "loan_products": 5,
        "loan_accounts": 5,
        "payments": 10,
    }

    logger.info("Running data quality checks with source counts: %s", source_counts)

    report = run_all_checks(
        spark=spark,
        source_counts=source_counts,
        output_path="dbfs:/mnt/reports/DATA_QUALITY_REPORT.md",
    )

    logger.info("Quality report: %d passed, %d failed out of %d total checks",
                report.passed_checks, report.failed_checks, report.total_checks)

    if not report.all_passed:
        logger.error("Data quality checks FAILED — review the report.")
        sys.exit(1)
    else:
        logger.info("All data quality checks PASSED.")


if __name__ == "__main__":
    main()
