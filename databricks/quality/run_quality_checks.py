"""
Data-quality check runner for the legacy CDW → Delta Lake migration.

Runs all validation checks and generates a DATA_QUALITY_REPORT.md in the
repository root (or a configurable output path).

Usage (Databricks notebook):
    from databricks.quality.run_quality_checks import run_quality_checks
    run_quality_checks(spark, pipeline_results, output_path="/dbfs/reports/")
"""

import logging
from datetime import datetime, timezone

from pyspark.sql import SparkSession

from databricks.quality.validators import (
    QualityReport,
    check_business_rules,
    check_referential_integrity,
    check_required_nulls,
    check_row_counts,
)

logger = logging.getLogger("migration.quality.runner")


def generate_report_markdown(report: QualityReport) -> str:
    """Render the quality report as Markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {now}",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total checks | {report.total} |",
        f"| Passed | {report.passed} |",
        f"| Failed | {report.failed} |",
        "",
        "---",
        "",
    ]

    categories = sorted(set(r.category for r in report.results))
    for cat in categories:
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Check | Status | Detail | Expected | Actual |")
        lines.append("|-------|--------|--------|----------|--------|")

        cat_results = [r for r in report.results if r.category == cat]
        for r in cat_results:
            status = "PASS" if r.passed else "**FAIL**"
            lines.append(
                f"| {r.check_name} | {status} | {r.detail} | {r.expected} | {r.actual} |"
            )

        lines.append("")

    if report.failed > 0:
        lines.append("---")
        lines.append("")
        lines.append("## Failed Checks Summary")
        lines.append("")
        for r in report.results:
            if not r.passed:
                lines.append(f"- **[{r.category}]** {r.check_name}: {r.detail}")
        lines.append("")

    lines.append("---")
    lines.append("")
    overall = "ALL CHECKS PASSED" if report.failed == 0 else f"{report.failed} CHECK(S) FAILED"
    lines.append(f"**Overall Result: {overall}**")
    lines.append("")

    return "\n".join(lines)


def run_quality_checks(
    spark: SparkSession,
    pipeline_results: dict,
    output_path: str = ".",
) -> QualityReport:
    """Run all data-quality checks and write the report to disk.

    Args:
        spark: Active SparkSession.
        pipeline_results: Dict returned by ``run_pipeline.run_migration()``.
        output_path: Directory where DATA_QUALITY_REPORT.md will be written.
                     For Databricks, use a DBFS path (e.g. '/dbfs/reports/').

    Returns:
        The populated QualityReport object.
    """
    report = QualityReport()

    logger.info("Running row-count reconciliation checks...")
    check_row_counts(report, pipeline_results)

    logger.info("Running null checks on required fields...")
    check_required_nulls(spark, report)

    logger.info("Running referential integrity checks...")
    check_referential_integrity(spark, report)

    logger.info("Running business rule validations...")
    check_business_rules(spark, report)

    md_content = generate_report_markdown(report)
    report_file = f"{output_path.rstrip('/')}/DATA_QUALITY_REPORT.md"

    try:
        with open(report_file, "w") as f:
            f.write(md_content)
        logger.info("Data quality report written to %s", report_file)
    except OSError:
        logger.warning(
            "Could not write report to %s — writing to DBFS fallback", report_file
        )
        dbfs_path = "/dbfs/tmp/DATA_QUALITY_REPORT.md"
        with open(dbfs_path, "w") as f:
            f.write(md_content)
        logger.info("Data quality report written to %s", dbfs_path)

    logger.info(
        "Quality check complete: %d passed, %d failed out of %d total",
        report.passed,
        report.failed,
        report.total,
    )

    return report
