"""
Data Quality Runner

Orchestrates all quality checks and generates:
1. Console output with pass/fail summary
2. A DATA_QUALITY_REPORT.md file with detailed results

Usage:
    spark-submit runner.py <base_source_path> [file_format] [output_path]
"""

import sys
from datetime import datetime

from pyspark.sql import SparkSession

from .checks import (
    check_business_rules,
    check_nulls,
    check_referential_integrity,
    check_row_count,
)


def run_quality_checks(spark: SparkSession, base_source_path: str,
                       file_format: str = "csv") -> list:
    """Run all data quality checks and return results.

    Args:
        spark: Active SparkSession
        base_source_path: Base path to source files for row count comparison
        file_format: Source file format

    Returns:
        List of check result dicts
    """
    all_results = []

    print("[INFO] Running row count reconciliation checks...")
    tables_and_paths = [
        ("loan_warehouse.borrowers", f"{base_source_path}/CDW_BORR_MSTR/"),
        ("loan_warehouse.loan_products", f"{base_source_path}/CDW_LN_PROD/"),
        ("loan_warehouse.loan_accounts", f"{base_source_path}/CDW_LN_ACCT/"),
        ("loan_warehouse.payments", f"{base_source_path}/CDW_PMT_HIST/"),
    ]

    for table, path in tables_and_paths:
        try:
            result = check_row_count(spark, path, table, file_format)
            all_results.append(result)
        except Exception as e:
            all_results.append({
                "check_name": f"Row count: {table}",
                "category": "row_count",
                "passed": False,
                "details": f"Check failed with error: {e}",
                "source_value": None,
                "target_value": None,
            })

    print("[INFO] Running null checks on required fields...")
    for table in [
        "loan_warehouse.borrowers",
        "loan_warehouse.loan_products",
        "loan_warehouse.loan_accounts",
        "loan_warehouse.payments",
    ]:
        try:
            null_results = check_nulls(spark, table)
            all_results.extend(null_results)
        except Exception as e:
            all_results.append({
                "check_name": f"Null checks: {table}",
                "category": "null_check",
                "passed": False,
                "details": f"Check failed with error: {e}",
                "source_value": None,
                "target_value": None,
            })

    print("[INFO] Running referential integrity checks...")
    try:
        ri_results = check_referential_integrity(spark)
        all_results.extend(ri_results)
    except Exception as e:
        all_results.append({
            "check_name": "Referential integrity checks",
            "category": "referential_integrity",
            "passed": False,
            "details": f"Check failed with error: {e}",
            "source_value": None,
            "target_value": None,
        })

    print("[INFO] Running business rule validations...")
    try:
        br_results = check_business_rules(spark)
        all_results.extend(br_results)
    except Exception as e:
        all_results.append({
            "check_name": "Business rule checks",
            "category": "business_rule",
            "passed": False,
            "details": f"Check failed with error: {e}",
            "source_value": None,
            "target_value": None,
        })

    return all_results


def generate_report(results: list, output_path: str = None) -> str:
    """Generate a markdown quality report from check results.

    Args:
        results: List of check result dicts
        output_path: Optional file path to write the report

    Returns:
        Markdown report content as string
    """
    timestamp = datetime.now().isoformat()
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    pass_rate = (passed / total * 100) if total > 0 else 0

    # Group by category
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {timestamp}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Checks | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Pass Rate | {pass_rate:.1f}% |",
        "",
        f"**Overall Status:** {'PASS' if failed == 0 else 'FAIL'}",
        "",
    ]

    category_labels = {
        "row_count": "Row Count Reconciliation",
        "null_check": "Null Checks on Required Fields",
        "referential_integrity": "Referential Integrity",
        "business_rule": "Business Rule Validations",
    }

    for cat_key, cat_label in category_labels.items():
        cat_results = categories.get(cat_key, [])
        if not cat_results:
            continue

        cat_passed = sum(1 for r in cat_results if r["passed"])
        cat_total = len(cat_results)

        lines.append(f"## {cat_label} ({cat_passed}/{cat_total} passed)")
        lines.append("")
        lines.append("| Status | Check | Details |")
        lines.append("|--------|-------|---------|")

        for r in cat_results:
            status_icon = "PASS" if r["passed"] else "FAIL"
            lines.append(f"| {status_icon} | {r['check_name']} | {r['details']} |")

        lines.append("")

    # Quarantine summary
    lines.extend([
        "## Quarantine Summary",
        "",
        "Records that failed critical parsing are stored in quarantine tables:",
        "- `loan_warehouse._quarantine_borrowers`",
        "- `loan_warehouse._quarantine_loan_products`",
        "- `loan_warehouse._quarantine_loan_accounts`",
        "- `loan_warehouse._quarantine_payments`",
        "",
        "Review quarantined records and resolve data issues before marking "
        "migration as complete.",
        "",
        "---",
        f"*Report generated by Data Quality Framework at {timestamp}*",
    ])

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w") as f:
            f.write(report)
        print(f"[INFO] Quality report written to: {output_path}")

    return report


if __name__ == "__main__":
    spark = SparkSession.builder \
        .appName("LoanMigration_QualityChecks") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .getOrCreate()

    base_path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/legacy-export"
    file_format = sys.argv[2] if len(sys.argv) > 2 else "csv"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "/dbfs/reports/DATA_QUALITY_REPORT.md"

    results = run_quality_checks(spark, base_path, file_format)
    report = generate_report(results, output_path)

    # Print summary
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    print(f"\n{'='*70}")
    print(f"QUALITY CHECK COMPLETE: {passed} passed, {failed} failed")
    print(f"{'='*70}")

    if failed > 0:
        print("\nFailed checks:")
        for r in results:
            if not r["passed"]:
                print(f"  FAIL: {r['check_name']} - {r['details']}")
        sys.exit(1)
