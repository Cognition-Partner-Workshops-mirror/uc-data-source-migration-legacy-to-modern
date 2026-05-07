"""
Report generator for the Data Quality Validation Framework.
Produces a DATA_QUALITY_REPORT.md file summarizing all validation results.
"""

import os
from datetime import datetime

from data_quality import QualityReport


def generate_report(report: QualityReport, output_path: str = "DATA_QUALITY_REPORT.md") -> str:
    """
    Generate a Markdown report from validation results.

    Args:
        report: QualityReport with all validation results
        output_path: File path for the output report

    Returns:
        The file path of the generated report
    """
    lines = []
    lines.append("# Data Quality Validation Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("**Pipeline:** CDW Legacy to Modern Delta Lake Migration")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Checks | {report.total_checks} |")
    lines.append(f"| Passed | {report.passed_checks} |")
    lines.append(f"| Failed | {report.failed_checks} |")
    lines.append(f"| Pass Rate | {report.pass_rate:.1f}% |")

    if report.start_time and report.end_time:
        duration = (report.end_time - report.start_time).total_seconds()
        lines.append(f"| Duration | {duration:.2f}s |")
    lines.append("")

    # Overall status
    if report.failed_checks == 0:
        lines.append("> **STATUS: ALL CHECKS PASSED**")
    else:
        lines.append(f"> **STATUS: {report.failed_checks} CHECK(S) FAILED - REVIEW REQUIRED**")
    lines.append("")

    # Group results by category
    categories = {}
    for result in report.results:
        if result.category not in categories:
            categories[result.category] = []
        categories[result.category].append(result)

    # Detailed results by category
    lines.append("## Detailed Results")
    lines.append("")

    for category, results in categories.items():
        lines.append(f"### {category}")
        lines.append("")
        lines.append("| Status | Table | Check | Details |")
        lines.append("|--------|-------|-------|---------|")

        for r in results:
            status_icon = "PASS" if r.passed else "**FAIL**"
            details = r.details
            if r.expected and r.actual and not r.passed:
                details += (
                    f" (expected: {r.expected}, actual: {r.actual})"
                )
            lines.append(
                f"| {status_icon} | {r.table} | {r.check_name} "
                f"| {details} |"
            )

        lines.append("")

    # Failed checks summary (if any)
    failed = [r for r in report.results if not r.passed]
    if failed:
        lines.append("## Failed Checks - Action Required")
        lines.append("")
        for i, r in enumerate(failed, 1):
            lines.append(f"{i}. **[{r.category}]** `{r.table}`: {r.check_name}")
            lines.append(f"   - {r.details}")
            if r.expected and r.actual:
                lines.append(f"   - Expected: `{r.expected}` | Actual: `{r.actual}`")
            lines.append("")

    # Recommendations
    lines.append("## Recommendations")
    lines.append("")
    if report.failed_checks == 0:
        lines.append("- All validations passed. Data is ready for downstream consumption.")
        lines.append("- Consider scheduling periodic re-validation as new data is ingested.")
    else:
        lines.append("- Review failed checks above and investigate root causes.")
        lines.append("- Check the `_migration_errors` table for rejected source records.")
        lines.append("- Re-run ingestion after fixing source data issues.")
        lines.append("- Do NOT promote data to production until all checks pass.")
    lines.append("")

    content = "\n".join(lines)

    # Write report
    output_dir = os.path.dirname(output_path) if os.path.dirname(output_path) else "."
    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(content)

    return output_path
