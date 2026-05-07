"""
Orchestrator: runs all data quality checks and generates DATA_QUALITY_REPORT.md.

Usage (Databricks notebook):
    %run ./run_quality_checks

Usage (command line):
    spark-submit --py-files databricks.zip databricks/quality/run_quality_checks.py \
        --source-dir /mnt/legacy --format csv --output-path /dbfs/reports/DATA_QUALITY_REPORT.md
"""

import argparse
import logging
import sys
from datetime import datetime

from pyspark.sql import SparkSession

from databricks.quality.validators import (
    QualityReport,
    check_active_loan_positive_balance,
    check_closed_loan_has_closed_date,
    check_interest_rate_range,
    check_origination_before_maturity,
    check_payment_amount_positive,
    check_payment_components_sum,
    check_referential_integrity,
    check_required_not_null,
    check_row_counts,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("loan_migration.quality")

# Table paths
BORROWERS_PATH = "/mnt/delta/loan_warehouse/borrowers"
LOAN_PRODUCTS_PATH = "/mnt/delta/loan_warehouse/loan_products"
LOAN_ACCOUNTS_PATH = "/mnt/delta/loan_warehouse/loan_accounts"
PAYMENTS_PATH = "/mnt/delta/loan_warehouse/payments"

# Required columns per table
BORROWERS_REQUIRED = ["external_id", "first_name", "last_name", "status"]
LOAN_PRODUCTS_REQUIRED = ["code", "name", "type", "term_months", "rate_type"]
LOAN_ACCOUNTS_REQUIRED = [
    "account_number", "borrower_id", "product_id",
    "original_amount", "current_balance", "interest_rate",
    "term_months", "monthly_payment", "origination_date",
    "maturity_date", "status",
]
PAYMENTS_REQUIRED = ["loan_account_id", "payment_date", "total_amount", "type", "status"]


def run_all_checks(
    spark: SparkSession,
    source_dir: str = "/mnt/legacy",
    fmt: str = "csv",
) -> QualityReport:
    """Execute the full data quality check suite."""
    report = QualityReport()

    logger.info("=" * 60)
    logger.info("DATA QUALITY CHECKS — Row Count Reconciliation")
    logger.info("=" * 60)

    check_row_counts(report, spark, f"{source_dir}/CDW_BORR_MSTR", BORROWERS_PATH, "borrowers", fmt)
    check_row_counts(report, spark, f"{source_dir}/CDW_LN_PROD", LOAN_PRODUCTS_PATH, "loan_products", fmt)
    check_row_counts(report, spark, f"{source_dir}/CDW_LN_ACCT", LOAN_ACCOUNTS_PATH, "loan_accounts", fmt)
    check_row_counts(report, spark, f"{source_dir}/CDW_PMT_HIST", PAYMENTS_PATH, "payments", fmt)

    logger.info("=" * 60)
    logger.info("DATA QUALITY CHECKS — Null Checks on Required Fields")
    logger.info("=" * 60)

    check_required_not_null(report, spark, BORROWERS_PATH, "borrowers", BORROWERS_REQUIRED)
    check_required_not_null(report, spark, LOAN_PRODUCTS_PATH, "loan_products", LOAN_PRODUCTS_REQUIRED)
    check_required_not_null(report, spark, LOAN_ACCOUNTS_PATH, "loan_accounts", LOAN_ACCOUNTS_REQUIRED)
    check_required_not_null(report, spark, PAYMENTS_PATH, "payments", PAYMENTS_REQUIRED)

    logger.info("=" * 60)
    logger.info("DATA QUALITY CHECKS — Referential Integrity")
    logger.info("=" * 60)

    check_referential_integrity(
        report, spark,
        child_path=LOAN_ACCOUNTS_PATH, child_table="loan_accounts",
        child_fk_col="borrower_id",
        parent_path=BORROWERS_PATH, parent_table="borrowers",
        parent_pk_col="id",
    )
    check_referential_integrity(
        report, spark,
        child_path=LOAN_ACCOUNTS_PATH, child_table="loan_accounts",
        child_fk_col="product_id",
        parent_path=LOAN_PRODUCTS_PATH, parent_table="loan_products",
        parent_pk_col="id",
    )
    check_referential_integrity(
        report, spark,
        child_path=PAYMENTS_PATH, child_table="payments",
        child_fk_col="loan_account_id",
        parent_path=LOAN_ACCOUNTS_PATH, parent_table="loan_accounts",
        parent_pk_col="id",
    )

    logger.info("=" * 60)
    logger.info("DATA QUALITY CHECKS — Business Rules")
    logger.info("=" * 60)

    check_active_loan_positive_balance(report, spark, LOAN_ACCOUNTS_PATH)
    check_closed_loan_has_closed_date(report, spark, LOAN_ACCOUNTS_PATH)
    check_payment_amount_positive(report, spark, PAYMENTS_PATH)
    check_payment_components_sum(report, spark, PAYMENTS_PATH)
    check_origination_before_maturity(report, spark, LOAN_ACCOUNTS_PATH)
    check_interest_rate_range(report, spark, LOAN_ACCOUNTS_PATH)

    return report


def generate_report_markdown(report: QualityReport) -> str:
    """Generate a markdown-formatted quality report."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Checks | {report.total_checks} |",
        f"| Passed | {report.passed_checks} |",
        f"| Failed | {report.failed_checks} |",
        f"| Pass Rate | {report.passed_checks / max(report.total_checks, 1) * 100:.1f}% |",
        "",
    ]

    # Group results by category
    categories = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for category, checks in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Status | Check | Table | Details | Expected | Actual |")
        lines.append("|--------|-------|-------|---------|----------|--------|")
        for r in checks:
            status = "PASS" if r.passed else "**FAIL**"
            lines.append(
                f"| {status} | {r.check_name} | {r.table} | {r.details} | {r.expected} | {r.actual} |"
            )
        lines.append("")

    # Failed checks summary
    failed = [r for r in report.results if not r.passed]
    if failed:
        lines.append("## Failed Checks Detail")
        lines.append("")
        for r in failed:
            lines.append(f"### {r.check_name}")
            lines.append(f"- **Category:** {r.category}")
            lines.append(f"- **Table:** {r.table}")
            lines.append(f"- **Expected:** {r.expected}")
            lines.append(f"- **Actual:** {r.actual}")
            lines.append(f"- **Details:** {r.details}")
            lines.append("")
    else:
        lines.append("## All Checks Passed")
        lines.append("")
        lines.append("No data quality issues detected.")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run loan data quality checks")
    parser.add_argument("--source-dir", default="/mnt/legacy", help="Path to legacy source files")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument(
        "--output-path", default="/dbfs/reports/DATA_QUALITY_REPORT.md",
        help="Path to write the quality report",
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName("LoanMigration_QualityChecks").getOrCreate()

    report = run_all_checks(spark, source_dir=args.source_dir, fmt=args.format)
    markdown = generate_report_markdown(report)

    with open(args.output_path, "w") as f:
        f.write(markdown)

    print(markdown)
    logger.info("Report written to %s", args.output_path)

    if report.failed_checks > 0:
        logger.warning("%d quality checks FAILED", report.failed_checks)
        sys.exit(1)

    spark.stop()


if __name__ == "__main__":
    main()
