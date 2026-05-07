"""
Entry point for running data quality validation after ingestion.
Executes all checks and generates the DATA_QUALITY_REPORT.md.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ingestion"))

from pyspark.sql import SparkSession

from data_quality import DataQualityValidator
from report_generator import generate_report

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("run_validation")


def get_spark() -> SparkSession:
    """Get or create a SparkSession."""
    return (
        SparkSession.builder
        .appName("CDW_Migration_DataQuality")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .getOrCreate()
    )


def main():
    """Run all data quality validations and generate report."""
    spark = get_spark()

    logger.info("Initializing Data Quality Validator...")
    validator = DataQualityValidator(
        spark=spark,
        database="loan_warehouse",
        source_base_path="/mnt/legacy-cdw/exports",
        source_format="csv",
    )

    # Run all checks
    report = validator.run_all_checks()

    # Generate report
    report_path = generate_report(
        report,
        output_path="DATA_QUALITY_REPORT.md"
    )
    logger.info(f"Report generated: {report_path}")

    # Exit with non-zero code if any checks failed
    if report.failed_checks > 0:
        logger.warning(
            f"Data quality validation completed with {report.failed_checks} failures. "
            f"Review {report_path} for details."
        )
        sys.exit(1)
    else:
        logger.info("All data quality checks passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
