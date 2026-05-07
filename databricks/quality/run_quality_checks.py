"""
Data Quality Check Runner and Report Generator.

Executes all quality checks and generates a DATA_QUALITY_REPORT.md summarizing
pass/fail results for the CDW legacy-to-modern migration.

Usage (Databricks notebook or job):
    from databricks.quality.run_quality_checks import run_all_checks
    run_all_checks(spark, config)
"""

import logging
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession

from .checks import (
    CheckResult,
    CheckStatus,
    check_active_loan_positive_balance,
    check_borrower_required_fields,
    check_borrower_row_count,
    check_closed_loan_has_closed_date,
    check_credit_score_range,
    check_loan_account_required_fields,
    check_loan_accounts_row_count,
    check_loan_borrower_integrity,
    check_loan_product_integrity,
    check_loan_products_row_count,
    check_loan_status_values,
    check_payment_amount_components,
    check_payment_loan_integrity,
    check_payment_required_fields,
    check_payments_row_count,
)

logger = logging.getLogger(__name__)


def run_all_checks(
    spark: SparkSession,
    config: dict = None,
    report_path: str = None,
) -> list[CheckResult]:
    """
    Execute all data quality checks and generate a report.

    Args:
        spark: Active SparkSession
        config: Configuration dict with source paths and table names
        report_path: Path to write the DATA_QUALITY_REPORT.md

    Returns:
        List of CheckResult objects
    """
    if config is None:
        config = {}

    base_source = config.get("base_source_path", "/mnt/legacy")
    if report_path is None:
        report_path = config.get("report_path", "/mnt/migration/DATA_QUALITY_REPORT.md")

    results: list[CheckResult] = []

    logger.info("=" * 60)
    logger.info("STARTING DATA QUALITY CHECKS")
    logger.info("=" * 60)

    # -------------------------------------------------------------------------
    # Row Count Reconciliation
    # -------------------------------------------------------------------------
    logger.info("--- Row Count Reconciliation ---")
    results.append(
        check_borrower_row_count(spark, f"{base_source}/cdw_borr_mstr/")
    )
    results.append(
        check_loan_products_row_count(spark, f"{base_source}/cdw_ln_prod/")
    )
    results.append(
        check_loan_accounts_row_count(spark, f"{base_source}/cdw_ln_acct/")
    )
    results.append(
        check_payments_row_count(spark, f"{base_source}/cdw_pmt_hist/")
    )

    # -------------------------------------------------------------------------
    # Null Checks on Required Fields
    # -------------------------------------------------------------------------
    logger.info("--- Null Checks on Required Fields ---")
    results.append(check_borrower_required_fields(spark))
    results.append(check_loan_account_required_fields(spark))
    results.append(check_payment_required_fields(spark))

    # -------------------------------------------------------------------------
    # Referential Integrity
    # -------------------------------------------------------------------------
    logger.info("--- Referential Integrity Checks ---")
    results.append(check_loan_borrower_integrity(spark))
    results.append(check_loan_product_integrity(spark))
    results.append(check_payment_loan_integrity(spark))

    # -------------------------------------------------------------------------
    # Business Rule Validation
    # -------------------------------------------------------------------------
    logger.info("--- Business Rule Validation ---")
    results.append(check_active_loan_positive_balance(spark))
    results.append(check_closed_loan_has_closed_date(spark))
    results.append(check_payment_amount_components(spark))
    results.append(check_credit_score_range(spark))
    results.append(check_loan_status_values(spark))

    # -------------------------------------------------------------------------
    # Generate Report
    # -------------------------------------------------------------------------
    report_content = generate_report(results)

    # Write report to DBFS or local path
    try:
        dbutils = None
        try:
            # Attempt to use dbutils if running in Databricks
            from pyspark.dbutils import DBUtils
            dbutils = DBUtils(spark)
            dbutils.fs.put(report_path, report_content, overwrite=True)
            logger.info(f"Report written to: {report_path}")
        except (ImportError, Exception):
            # Fallback: write as a Spark text file
            spark.sparkContext.parallelize([report_content]).coalesce(1).saveAsTextFile(
                report_path + "_tmp"
            )
            logger.info(f"Report written to: {report_path}_tmp")
    except Exception as e:
        logger.warning(f"Could not write report to {report_path}: {e}")
        logger.info("Report content:\n" + report_content)

    # Summary log
    passed = sum(1 for r in results if r.status == CheckStatus.PASSED)
    failed = sum(1 for r in results if r.status == CheckStatus.FAILED)
    warnings = sum(1 for r in results if r.status == CheckStatus.WARNING)
    skipped = sum(1 for r in results if r.status == CheckStatus.SKIPPED)

    logger.info("=" * 60)
    logger.info(f"DATA QUALITY SUMMARY: {passed} passed, {failed} failed, "
                f"{warnings} warnings, {skipped} skipped")
    logger.info("=" * 60)

    return results


def generate_report(results: list[CheckResult]) -> str:
    """Generate a markdown DATA_QUALITY_REPORT from check results."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    passed = sum(1 for r in results if r.status == CheckStatus.PASSED)
    failed = sum(1 for r in results if r.status == CheckStatus.FAILED)
    warnings = sum(1 for r in results if r.status == CheckStatus.WARNING)
    skipped = sum(1 for r in results if r.status == CheckStatus.SKIPPED)
    total = len(results)

    overall = "PASS" if failed == 0 else "FAIL"

    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {now}",
        f"**Overall Status:** {'PASS' if failed == 0 else 'FAIL'}",
        f"**Pipeline:** CDW Legacy-to-Modern Migration",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total Checks | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Warnings | {warnings} |",
        f"| Skipped | {skipped} |",
        "",
        "---",
        "",
    ]

    # Group results by category
    categories = {}
    for r in results:
        if r.category not in categories:
            categories[r.category] = []
        categories[r.category].append(r)

    for category, checks in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Check | Status | Message |")
        lines.append("|-------|--------|---------|")

        for check in checks:
            status_icon = {
                CheckStatus.PASSED: "PASS",
                CheckStatus.FAILED: "FAIL",
                CheckStatus.WARNING: "WARN",
                CheckStatus.SKIPPED: "SKIP",
            }[check.status]

            # Escape pipe characters in message
            msg = check.message.replace("|", "\\|")
            lines.append(f"| {check.name} | {status_icon} | {msg} |")

        lines.append("")

    # Detailed failures section
    failures = [r for r in results if r.status in (CheckStatus.FAILED, CheckStatus.WARNING)]
    if failures:
        lines.append("---")
        lines.append("")
        lines.append("## Detailed Findings")
        lines.append("")

        for r in failures:
            lines.append(f"### {r.name}")
            lines.append("")
            lines.append(f"- **Status:** {r.status.value}")
            lines.append(f"- **Message:** {r.message}")
            if r.expected:
                lines.append(f"- **Expected:** {r.expected}")
            if r.actual:
                lines.append(f"- **Actual:** {r.actual}")
            if r.details:
                lines.append(f"- **Details:**")
                for key, value in r.details.items():
                    lines.append(f"  - {key}: {value}")
            lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("*Report generated by CDW Migration Data Quality Framework*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("CDW_DataQuality_Checks").getOrCreate()

    config = {
        "base_source_path": spark.conf.get("migration.base_source_path", "/mnt/legacy"),
        "report_path": spark.conf.get(
            "migration.quality_report_path", "/mnt/migration/DATA_QUALITY_REPORT.md"
        ),
    }

    results = run_all_checks(spark, config)

    # Exit with non-zero if any checks failed
    failed_count = sum(1 for r in results if r.status == CheckStatus.FAILED)
    if failed_count > 0:
        logger.error(f"{failed_count} quality checks FAILED!")
        raise SystemExit(1)

    print("All data quality checks passed!")
