"""
Execution summary report generator.
Produces a human-readable report (text + HTML) from validation test results,
with pass/fail counts, category breakdowns, and detailed failure listings.
"""

import json
import logging
import os
from collections import Counter
from datetime import datetime

from config import REPORT_OUTPUT_DIR

logger = logging.getLogger(__name__)


def _ensure_report_dir() -> str:
    """Create the report output directory if it does not exist."""
    os.makedirs(REPORT_OUTPUT_DIR, exist_ok=True)
    return REPORT_OUTPUT_DIR


def generate_text_report(results: list[dict], run_params: dict) -> str:
    """
    Generate a plain-text execution summary report.

    Args:
        results: List of test result dicts from all modules.
        run_params: Dict with run metadata (as_of_dt, timestamp, etc.).

    Returns:
        Path to the generated text report file.
    """
    report_dir = _ensure_report_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"validation_report_{timestamp}.txt"
    filepath = os.path.join(report_dir, filename)

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    # Category breakdown
    cat_counter = Counter()
    cat_pass = Counter()
    for r in results:
        cat = r.get("category", "unknown")
        cat_counter[cat] += 1
        if r.get("passed"):
            cat_pass[cat] += 1

    lines = [
        "=" * 80,
        "HIVE DATA VALIDATION — EXECUTION SUMMARY REPORT",
        "=" * 80,
        "",
        "Run Parameters:",
        f"  as_of_dt (current):  {run_params.get('as_of_dt', 'N/A')}",
        f"  as_of_dt (previous): {run_params.get('as_of_dt_previous', 'N/A')}",
        f"  Execution time:      {run_params.get('execution_time', 'N/A')}",
        f"  JDBC URL:            {run_params.get('jdbc_url', 'N/A')}",
        f"  Report generated:    {datetime.now().isoformat()}",
        "",
        "-" * 80,
        "OVERALL RESULTS",
        "-" * 80,
        f"  Total tests:   {total}",
        f"  Passed:        {passed}",
        f"  Failed:        {failed}",
        f"  Pass rate:     {(passed / total * 100):.1f}%" if total > 0 else "  Pass rate:     N/A",
        "",
        "-" * 80,
        "RESULTS BY CATEGORY",
        "-" * 80,
    ]

    for cat in sorted(cat_counter.keys()):
        cat_total = cat_counter[cat]
        cat_passed = cat_pass[cat]
        cat_failed = cat_total - cat_passed
        # Status indicator for the category
        status = "PASS" if cat_failed == 0 else "FAIL"
        lines.append(
            f"  [{status}] {cat:<20s}  "
            f"{cat_passed}/{cat_total} passed  "
            f"({cat_failed} failed)"
        )

    # Detailed failures
    failures = [r for r in results if not r.get("passed")]
    if failures:
        lines.extend([
            "",
            "-" * 80,
            "FAILED TEST DETAILS",
            "-" * 80,
        ])
        for i, f in enumerate(failures, 1):
            lines.extend([
                f"  [{i}] {f.get('test_id', '?')} — {f.get('test_name', '?')}",
                f"      Category:  {f.get('category', '?')}",
                f"      Expected:  {f.get('expected', '?')}",
                f"      Actual:    {f.get('actual', '?')}",
                f"      Message:   {f.get('message', '')}",
                f"      SQL:       {str(f.get('sql', ''))[:200]}",
                "",
            ])
    else:
        lines.extend([
            "",
            "-" * 80,
            "ALL TESTS PASSED",
            "-" * 80,
        ])

    lines.extend([
        "",
        "=" * 80,
        "END OF REPORT",
        "=" * 80,
    ])

    report_text = "\n".join(lines)
    with open(filepath, "w") as fh:
        fh.write(report_text)

    logger.info("Text report written to %s", filepath)
    return filepath


def generate_html_report(results: list[dict], run_params: dict) -> str:
    """
    Generate an HTML execution summary report with styled tables.

    Args:
        results: List of test result dicts from all modules.
        run_params: Dict with run metadata.

    Returns:
        Path to the generated HTML report file.
    """
    report_dir = _ensure_report_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"validation_report_{timestamp}.html"
    filepath = os.path.join(report_dir, filename)

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    pass_rate = f"{(passed / total * 100):.1f}%" if total > 0 else "N/A"

    # Category breakdown
    categories = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in categories:
            categories[cat] = {"total": 0, "passed": 0, "failed": 0}
        categories[cat]["total"] += 1
        if r.get("passed"):
            categories[cat]["passed"] += 1
        else:
            categories[cat]["failed"] += 1

    # Build HTML content
    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "  <meta charset='UTF-8'>",
        "  <title>Hive Validation Report</title>",
        "  <style>",
        "    body { font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background: #f5f5f5; }",
        "    h1 { color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }",
        "    h2 { color: #555; margin-top: 30px; }",
        "    .summary-box { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }",
        "    .pass { color: #28a745; font-weight: bold; }",
        "    .fail { color: #dc3545; font-weight: bold; }",
        "    table { border-collapse: collapse; width: 100%; margin-top: 10px; background: white; }",
        "    th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; font-size: 13px; }",
        "    th { background-color: #007bff; color: white; }",
        "    tr:nth-child(even) { background-color: #f9f9f9; }",
        "    tr:hover { background-color: #e9ecef; }",
        "    .status-pass { background-color: #d4edda; }",
        "    .status-fail { background-color: #f8d7da; }",
        "    .params { font-size: 14px; color: #666; }",
        "    .sql-cell { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: monospace; font-size: 11px; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>Hive Data Validation &mdash; Execution Summary Report</h1>",
        "  <div class='summary-box'>",
        "    <div class='params'>",
        f"      <strong>as_of_dt:</strong> {run_params.get('as_of_dt', 'N/A')} &nbsp;|&nbsp;",
        f"      <strong>Previous:</strong> {run_params.get('as_of_dt_previous', 'N/A')} &nbsp;|&nbsp;",
        f"      <strong>Execution time:</strong> {run_params.get('execution_time', 'N/A')} &nbsp;|&nbsp;",
        f"      <strong>Generated:</strong> {datetime.now().isoformat()}",
        "    </div>",
        f"    <h2>Overall: <span class='{'pass' if failed == 0 else 'fail'}'>"
        f"      {passed}/{total} passed ({pass_rate})</span></h2>",
        "  </div>",
        "",
        "  <h2>Results by Category</h2>",
        "  <table>",
        "    <tr><th>Category</th><th>Total</th><th>Passed</th><th>Failed</th><th>Status</th></tr>",
    ]

    for cat in sorted(categories.keys()):
        c = categories[cat]
        status_class = "status-pass" if c["failed"] == 0 else "status-fail"
        status_text = "PASS" if c["failed"] == 0 else "FAIL"
        html_parts.append(
            f"    <tr class='{status_class}'>"
            f"<td>{cat}</td><td>{c['total']}</td><td>{c['passed']}</td>"
            f"<td>{c['failed']}</td><td><strong>{status_text}</strong></td></tr>"
        )

    html_parts.extend([
        "  </table>",
        "",
        "  <h2>All Test Results</h2>",
        "  <table>",
        "    <tr><th>ID</th><th>Test Name</th><th>Category</th>"
        "<th>Expected</th><th>Actual</th><th>Status</th><th>Message</th><th>SQL</th></tr>",
    ])

    for r in results:
        status_class = "status-pass" if r.get("passed") else "status-fail"
        status_text = "PASS" if r.get("passed") else "FAIL"
        sql_display = str(r.get("sql", ""))[:150]
        html_parts.append(
            f"    <tr class='{status_class}'>"
            f"<td>{r.get('test_id', '')}</td>"
            f"<td>{r.get('test_name', '')}</td>"
            f"<td>{r.get('category', '')}</td>"
            f"<td>{r.get('expected', '')}</td>"
            f"<td>{r.get('actual', '')}</td>"
            f"<td><strong>{status_text}</strong></td>"
            f"<td>{r.get('message', '')}</td>"
            f"<td class='sql-cell' title='{str(r.get('sql', ''))}'>{sql_display}</td>"
            f"</tr>"
        )

    html_parts.extend([
        "  </table>",
        "</body>",
        "</html>",
    ])

    html_content = "\n".join(html_parts)
    with open(filepath, "w") as fh:
        fh.write(html_content)

    logger.info("HTML report written to %s", filepath)
    return filepath


def generate_json_report(results: list[dict], run_params: dict) -> str:
    """
    Generate a machine-readable JSON report for downstream automation.

    Args:
        results: List of test result dicts.
        run_params: Dict with run metadata.

    Returns:
        Path to the generated JSON report file.
    """
    report_dir = _ensure_report_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"validation_report_{timestamp}.json"
    filepath = os.path.join(report_dir, filename)

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))

    report_data = {
        "metadata": {
            "report_type": "hive_data_validation",
            "generated_at": datetime.now().isoformat(),
            **run_params,
        },
        "summary": {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        },
        "results": results,
    }

    with open(filepath, "w") as fh:
        json.dump(report_data, fh, indent=2, default=str)

    logger.info("JSON report written to %s", filepath)
    return filepath
