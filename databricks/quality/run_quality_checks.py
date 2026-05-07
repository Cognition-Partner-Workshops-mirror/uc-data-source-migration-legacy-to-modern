"""
Data Quality Check Runner

Executes all validation checks and generates a consolidated report.
Designed to run after the ingestion pipeline completes.

Usage:
    from run_quality_checks import run_all_checks
    report = run_all_checks(spark, config)
"""

from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession

from validators import (
    ValidationResult,
    check_active_loan_positive_balance,
    check_closed_loan_has_closed_date,
    check_credit_score_range,
    check_loan_term_valid,
    check_payment_amounts_consistent,
    check_referential_integrity,
    check_required_not_null,
    check_row_count_reconciliation,
)


DEFAULT_CONFIG = {
    "schema": "loan_warehouse",
    "source_base_path": "/mnt/legacy-data/cdw",
    "sources": {
        "borrowers": "/mnt/legacy-data/cdw/CDW_BORR_MSTR",
        "loan_products": "/mnt/legacy-data/cdw/CDW_LN_PROD",
        "loan_accounts": "/mnt/legacy-data/cdw/CDW_LN_ACCT",
        "payments": "/mnt/legacy-data/cdw/CDW_PMT_HIST",
    },
    "source_format": "csv",
    "report_output_path": "/mnt/data/quality_reports",
}

# Required (NOT NULL) columns per table
REQUIRED_COLUMNS = {
    "borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_products": ["code", "name", "is_active"],
    "loan_accounts": ["account_number", "borrower_id", "product_id", "status"],
    "payments": ["loan_account_id", "payment_date", "status"],
}


def run_all_checks(
    spark: SparkSession,
    config: Optional[dict] = None,
) -> list:
    """
    Execute all data quality checks and return results.

    Checks performed:
    1. Row count reconciliation for each table
    2. Required field null checks
    3. Referential integrity (loan_accounts -> borrowers, payments -> loan_accounts)
    4. Business rule validations

    Returns:
        List of ValidationResult objects
    """
    if config is None:
        config = DEFAULT_CONFIG

    schema = config.get("schema", "loan_warehouse")
    sources = config.get("sources", DEFAULT_CONFIG["sources"])
    source_format = config.get("source_format", "csv")

    all_results = []

    print("=" * 70)
    print(f"DATA QUALITY CHECKS START: {datetime.now().isoformat()}")
    print("=" * 70)

    # 1. Row Count Reconciliation
    print("\n[CATEGORY] Row Count Reconciliation")
    print("-" * 40)
    tables = ["borrowers", "loan_products", "loan_accounts", "payments"]
    for table_name in tables:
        result = check_row_count_reconciliation(
            spark,
            source_path=sources[table_name],
            target_table=f"{schema}.{table_name}",
            source_format=source_format,
        )
        all_results.append(result)
        _print_result(result)

    # 2. Required Field Null Checks
    print("\n[CATEGORY] Required Field Null Checks")
    print("-" * 40)
    for table_name, columns in REQUIRED_COLUMNS.items():
        results = check_required_not_null(
            spark,
            table=f"{schema}.{table_name}",
            columns=columns,
        )
        all_results.extend(results)
        for r in results:
            _print_result(r)

    # 3. Referential Integrity
    print("\n[CATEGORY] Referential Integrity")
    print("-" * 40)

    # loan_accounts.borrower_id -> borrowers.id
    result = check_referential_integrity(
        spark,
        child_table=f"{schema}.loan_accounts",
        child_column="borrower_id",
        parent_table=f"{schema}.borrowers",
        parent_column="id",
    )
    all_results.append(result)
    _print_result(result)

    # loan_accounts.product_id -> loan_products.id
    result = check_referential_integrity(
        spark,
        child_table=f"{schema}.loan_accounts",
        child_column="product_id",
        parent_table=f"{schema}.loan_products",
        parent_column="id",
    )
    all_results.append(result)
    _print_result(result)

    # payments.loan_account_id -> loan_accounts.id
    result = check_referential_integrity(
        spark,
        child_table=f"{schema}.payments",
        child_column="loan_account_id",
        parent_table=f"{schema}.loan_accounts",
        parent_column="id",
    )
    all_results.append(result)
    _print_result(result)

    # 4. Business Rule Validations
    print("\n[CATEGORY] Business Rule Validations")
    print("-" * 40)

    business_checks = [
        check_active_loan_positive_balance(spark, f"{schema}.loan_accounts"),
        check_closed_loan_has_closed_date(spark, f"{schema}.loan_accounts"),
        check_payment_amounts_consistent(spark, f"{schema}.payments"),
        check_loan_term_valid(spark, f"{schema}.loan_accounts"),
        check_credit_score_range(spark, f"{schema}.borrowers"),
    ]
    for result in business_checks:
        all_results.append(result)
        _print_result(result)

    # Summary
    _print_summary(all_results)

    return all_results


def generate_report_markdown(results: list) -> str:
    """
    Generate a DATA_QUALITY_REPORT.md from validation results.

    Returns:
        Markdown string with formatted report
    """
    now = datetime.now().isoformat()
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    warned = sum(1 for r in results if r.status == "WARN")
    total = len(results)

    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {now}",
        f"**Total Checks:** {total}",
        f"**Passed:** {passed} | **Failed:** {failed} | **Warnings:** {warned}",
        "",
        f"**Overall Status:** {'PASS' if failed == 0 else 'FAIL'}",
        "",
        "---",
        "",
        "## Summary by Category",
        "",
        "| Category | Checks | Passed | Failed | Warnings |",
        "|----------|--------|--------|--------|----------|",
    ]

    categories = {}
    for r in results:
        if r.category not in categories:
            categories[r.category] = {"total": 0, "pass": 0, "fail": 0, "warn": 0}
        categories[r.category]["total"] += 1
        if r.status == "PASS":
            categories[r.category]["pass"] += 1
        elif r.status == "FAIL":
            categories[r.category]["fail"] += 1
        else:
            categories[r.category]["warn"] += 1

    for cat, counts in categories.items():
        lines.append(
            f"| {cat} | {counts['total']} | {counts['pass']} | {counts['fail']} | {counts['warn']} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Detailed Results",
        "",
    ])

    # Group by category
    for category in categories:
        lines.append(f"### {category.replace('_', ' ').title()}")
        lines.append("")
        lines.append("| Check | Table | Status | Message |")
        lines.append("|-------|-------|--------|---------|")

        for r in results:
            if r.category == category:
                status_icon = "PASS" if r.status == "PASS" else ("FAIL" if r.status == "FAIL" else "WARN")
                lines.append(
                    f"| {r.check_name} | {r.table} | {status_icon} | {r.message} |"
                )
        lines.append("")

    # Failed checks detail
    failed_results = [r for r in results if r.status == "FAIL"]
    if failed_results:
        lines.extend([
            "---",
            "",
            "## Failed Checks — Details",
            "",
        ])
        for r in failed_results:
            lines.extend([
                f"### {r.check_name}",
                f"- **Table:** {r.table}",
                f"- **Expected:** {r.expected}",
                f"- **Actual:** {r.actual}",
                f"- **Failing Records:** {r.failing_count}",
                f"- **Total Records:** {r.total_count}",
                f"- **Message:** {r.message}",
                "",
            ])

    lines.extend([
        "---",
        "",
        "## Recommendations",
        "",
        "1. Investigate any FAIL results before promoting data to production",
        "2. Review rejection logs at `/mnt/data/rejections/` for parse error details",
        "3. WARN results indicate data anomalies that may be acceptable",
        "4. Re-run quality checks after any data corrections",
        "",
    ])

    return "\n".join(lines)


def save_report(
    results: list,
    output_path: str,
    spark: Optional[SparkSession] = None,
) -> str:
    """
    Save the quality report as both Markdown and JSON.

    Returns:
        Path to the generated markdown report
    """
    md_content = generate_report_markdown(results)
    # Write markdown report
    if spark:
        spark.sparkContext.parallelize([md_content]).coalesce(1).saveAsTextFile(
            f"{output_path}/DATA_QUALITY_REPORT_md"
        )

    # Also save as structured JSON for programmatic access
    json_results = []
    for r in results:
        json_results.append({
            "check_name": r.check_name,
            "category": r.category,
            "table": r.table,
            "status": r.status,
            "message": r.message,
            "expected": r.expected,
            "actual": r.actual,
            "failing_count": r.failing_count,
            "total_count": r.total_count,
            "timestamp": r.timestamp,
        })

    if spark:
        json_df = spark.createDataFrame(json_results)
        json_df.write.mode("overwrite").format("json").save(
            f"{output_path}/quality_results_json"
        )

    return md_content


def _print_result(result: ValidationResult) -> None:
    """Print a single result to stdout."""
    icon = "[PASS]" if result.status == "PASS" else ("[FAIL]" if result.status == "FAIL" else "[WARN]")
    print(f"  {icon} {result.check_name}: {result.message}")


def _print_summary(results: list) -> None:
    """Print summary statistics."""
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    warned = sum(1 for r in results if r.status == "WARN")

    print("\n" + "=" * 70)
    print("DATA QUALITY SUMMARY")
    print(f"  Total checks: {len(results)}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Warnings: {warned}")
    print(f"  Overall: {'PASS' if failed == 0 else 'FAIL'}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.getOrCreate()
    results = run_all_checks(spark)
    report_md = save_report(results, DEFAULT_CONFIG["report_output_path"], spark)
    print("\n\nGenerated Report:\n")
    print(report_md)
