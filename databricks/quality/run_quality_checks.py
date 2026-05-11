"""
Standalone script to run all data quality checks after ingestion.

Can be executed as a Databricks notebook or Python script.
Reads the already-loaded Delta tables and produces DATA_QUALITY_REPORT.md.

Usage:
  1. Run after the ingestion pipeline (run_ingestion.py) has completed.
  2. Optionally pass ingestion results for row count reconciliation.
  3. Report is written to the specified output path or DBFS default.

Example Databricks notebook usage:
  %run ./validation
  report = run_all_checks(spark, source_counts=ingestion_results)
"""

import logging
import sys

from pyspark.sql import SparkSession

# Add parent directory to path so we can import from ingestion/
sys.path.insert(0, "../ingestion")

from validation import run_all_checks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("cdw_migration.quality_runner")


def main():
    """Run quality checks as standalone script."""
    spark = SparkSession.builder.appName(
        "CDW_Migration_QualityChecks"
    ).enableHiveSupport().getOrCreate()

    try:
        # Run without source counts (row count reconciliation will be skipped
        # unless ingestion results are passed in). In a production Databricks
        # workflow, the orchestrator would pass the ingestion results dict.
        report = run_all_checks(
            spark,
            source_counts=None,
            output_path="/dbfs/tmp/DATA_QUALITY_REPORT.md",
        )

        logger.info(f"Overall: {report.passed} passed, {report.failed} failed")

        if report.failed > 0:
            logger.error("Quality checks have failures — review DATA_QUALITY_REPORT.md")
            sys.exit(1)
        else:
            logger.info("All quality checks passed")

    finally:
        spark.stop()


if __name__ == "__main__":
    main()
