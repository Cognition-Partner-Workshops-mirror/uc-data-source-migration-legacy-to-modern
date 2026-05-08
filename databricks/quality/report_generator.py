"""
Data Quality Report Generator
===============================
Takes the QualityReport produced by data_quality_checks.py and renders it
as a Markdown file (DATA_QUALITY_REPORT.md) suitable for review by data
stewards and migration leads.

Usage (Databricks notebook):
    from databricks.quality.data_quality_checks import run as run_checks
    from databricks.quality.report_generator import generate_report
    report = run_checks(spark)
    generate_report(report, output_path="/dbfs/reports/DATA_QUALITY_REPORT.md")
"""

try:
    # Databricks notebook environment
    from databricks.quality.models import QualityReport, CheckResult
except ImportError:
    # Standalone execution (e.g., local testing or CI)
    from models import QualityReport, CheckResult
from typing import List
import logging

logger = logging.getLogger("report_generator")
logging.basicConfig(level=logging.INFO)

# Output path for the generated report (can be overridden)
DEFAULT_OUTPUT_PATH = "databricks/quality/DATA_QUALITY_REPORT.md"


def _severity_badge(severity: str) -> str:
    """Return a Markdown-formatted severity indicator."""
    badges = {
        "CRITICAL": "**CRITICAL**",
        "HIGH": "**HIGH**",
        "MEDIUM": "MEDIUM",
        "LOW": "LOW",
    }
    return badges.get(severity, severity)


def _status_icon(status: str) -> str:
    """Return a pass/fail indicator for the report."""
    return "PASS" if status == "PASS" else "FAIL"


def _group_by_category(results: List[CheckResult]) -> dict:
    """Group check results by category for organized report sections."""
    groups = {}
    for r in results:
        groups.setdefault(r.category, []).append(r)
    return groups


def render_markdown(report: QualityReport) -> str:
    """Render the full quality report as a Markdown string."""
    lines = []

    # Header
    lines.append("# Data Quality Report")
    lines.append("")
    lines.append(f"**Run timestamp:** {report.run_timestamp}")
    lines.append("")

    # Executive summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total checks | {report.total_count} |")
    lines.append(f"| Passed | {report.pass_count} |")
    lines.append(f"| Failed | {report.fail_count} |")
    lines.append(f"| Pass rate | {report.pass_count / report.total_count * 100:.1f}% |" if report.total_count > 0 else "| Pass rate | N/A |")
    lines.append("")

    # Overall status
    if report.fail_count == 0:
        lines.append("> **Status: ALL CHECKS PASSED** — The migrated data meets all quality criteria.")
    else:
        lines.append(f"> **Status: {report.fail_count} CHECK(S) FAILED** — Review the failures below before promoting data to production.")
    lines.append("")

    # Category display names
    category_names = {
        "ROW_COUNT": "1. Row Count Reconciliation",
        "NULL_CHECK": "2. Null Checks on Required Fields",
        "REFERENTIAL_INTEGRITY": "3. Referential Integrity",
        "BUSINESS_RULE": "4. Business Rule Validation",
    }

    # Category descriptions
    category_desc = {
        "ROW_COUNT": "Verifies that the number of records in each target Delta table matches the source count (allowing for quarantined records).",
        "NULL_CHECK": "Ensures that columns marked as NOT NULL in the modern schema contain no null values.",
        "REFERENTIAL_INTEGRITY": "Validates that all foreign key references resolve to existing parent records.",
        "BUSINESS_RULE": "Checks domain-specific invariants that must hold for the data to be business-correct.",
    }

    grouped = _group_by_category(report.results)

    # Ordered sections
    for category_key in ["ROW_COUNT", "NULL_CHECK", "REFERENTIAL_INTEGRITY", "BUSINESS_RULE"]:
        results = grouped.get(category_key, [])
        section_name = category_names.get(category_key, category_key)
        section_desc = category_desc.get(category_key, "")

        lines.append(f"## {section_name}")
        lines.append("")
        lines.append(section_desc)
        lines.append("")

        if not results:
            lines.append("*No checks in this category.*")
            lines.append("")
            continue

        # Results table
        lines.append("| Status | Table | Check | Severity | Detail |")
        lines.append("|--------|-------|-------|----------|--------|")
        for r in results:
            lines.append(
                f"| {_status_icon(r.status)} | {r.table} | {r.check_name} "
                f"| {_severity_badge(r.severity)} | {r.detail} |"
            )
        lines.append("")

    # Failed checks detail section (only if there are failures)
    failed = [r for r in report.results if r.status == "FAIL"]
    if failed:
        lines.append("## Failed Check Details")
        lines.append("")
        lines.append("The following checks require attention before the migration can be promoted to production:")
        lines.append("")
        for i, r in enumerate(failed, 1):
            lines.append(f"### Failure {i}: {r.check_name}")
            lines.append("")
            lines.append(f"- **Category:** {r.category}")
            lines.append(f"- **Table:** {r.table}")
            lines.append(f"- **Severity:** {_severity_badge(r.severity)}")
            lines.append(f"- **Detail:** {r.detail}")
            lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("*Report generated by the Legacy CDW Migration Data Quality Framework.*")
    lines.append("*See `databricks/quality/data_quality_checks.py` for check implementations.*")
    lines.append("")

    return "\n".join(lines)


def generate_report(report: QualityReport,
                    output_path: str = DEFAULT_OUTPUT_PATH) -> str:
    """Generate DATA_QUALITY_REPORT.md from a QualityReport.

    Args:
        report: QualityReport from data_quality_checks.run()
        output_path: File path to write the Markdown report to.

    Returns:
        The rendered Markdown string.
    """
    md_content = render_markdown(report)

    with open(output_path, "w") as f:
        f.write(md_content)

    logger.info("Data quality report written to %s", output_path)
    return md_content


# ---------------------------------------------------------------------------
# Standalone usage
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Generate a sample report for documentation purposes
    sample_report = QualityReport()
    sample_report.results = [
        CheckResult("ROW_COUNT", "borrowers", "Row count reconciliation: borrowers", "PASS", "Source=5, Target=5 (exact match)", "LOW"),
        CheckResult("ROW_COUNT", "loan_products", "Row count reconciliation: loan_products", "PASS", "Source=5, Target=5 (exact match)", "LOW"),
        CheckResult("ROW_COUNT", "loan_accounts", "Row count reconciliation: loan_accounts", "PASS", "Source=5, Target=5 (exact match)", "LOW"),
        CheckResult("ROW_COUNT", "payments", "Row count reconciliation: payments", "PASS", "Source=10, Target=10 (exact match)", "LOW"),
        CheckResult("NULL_CHECK", "borrowers", "NOT NULL: borrowers.first_name", "PASS", "first_name: no nulls", "LOW"),
        CheckResult("NULL_CHECK", "borrowers", "NOT NULL: borrowers.credit_score", "PASS", "credit_score: no nulls", "LOW"),
        CheckResult("REFERENTIAL_INTEGRITY", "loan_accounts", "FK: loan_accounts.borrower_id -> borrowers.id", "PASS", "All references valid", "LOW"),
        CheckResult("REFERENTIAL_INTEGRITY", "loan_accounts", "FK: loan_accounts.product_id -> loan_products.id", "PASS", "All references valid", "LOW"),
        CheckResult("REFERENTIAL_INTEGRITY", "payments", "FK: payments.loan_account_id -> loan_accounts.id", "PASS", "All references valid", "LOW"),
        CheckResult("BUSINESS_RULE", "loan_accounts", "Active loans must have current_balance > 0", "PASS", "All active loans have positive balance", "LOW"),
        CheckResult("BUSINESS_RULE", "loan_accounts", "Active loans should not be delinquent (delinquency_days must be 0)", "FAIL", "1 active loan(s) with delinquency_days > 0", "HIGH"),
        CheckResult("BUSINESS_RULE", "borrowers", "Credit scores must be in FICO range 300-850", "PASS", "All credit scores in valid range", "LOW"),
        CheckResult("BUSINESS_RULE", "payments", "Payment component sum must match total (within $1.00 tolerance)", "FAIL", "2 payment(s) with component sum mismatch > $1.00", "HIGH"),
        CheckResult("BUSINESS_RULE", "loan_accounts", "Origination date must precede maturity date", "PASS", "All loan date ranges valid", "LOW"),
    ]
    generate_report(sample_report, DEFAULT_OUTPUT_PATH)
    print("Sample report generated at:", DEFAULT_OUTPUT_PATH)
