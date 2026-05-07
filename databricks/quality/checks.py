"""
Data Quality Framework for CDW-to-Modern migration.

Runs post-ingestion validation checks against the modern Delta Lake tables
and produces a structured report. Each check returns a CheckResult with
pass/fail status, counts, and detail messages.

Usage (Databricks notebook):
    %run ./checks
    results = run_all_checks(spark)
    generate_report(results, "/dbfs/reports/DATA_QUALITY_REPORT.md")
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    category: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    passed: bool
    message: str
    source_count: Optional[int] = None
    target_count: Optional[int] = None
    failing_records: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. Row count reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession,
                     source_table: str, source_count: int,
                     target_table: str) -> CheckResult:
    """Verify that source and target row counts match."""
    target_count = spark.table(target_table).count()
    passed = source_count == target_count
    msg = (
        f"{source_table} -> {target_table}: "
        f"source={source_count}, target={target_count}"
    )
    if not passed:
        delta = source_count - target_count
        msg += f" (MISSING {delta} rows)" if delta > 0 else f" (EXTRA {abs(delta)} rows)"
    return CheckResult(
        name=f"Row count: {source_table} -> {target_table}",
        category="Reconciliation",
        severity="CRITICAL",
        passed=passed,
        message=msg,
        source_count=source_count,
        target_count=target_count,
    )


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------

def check_required_not_null(spark: SparkSession, table: str,
                            columns: list[str]) -> list[CheckResult]:
    """Check that required columns have no null values."""
    df = spark.table(table)
    results = []
    for col_name in columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        total = df.count()
        passed = null_count == 0
        failing = []
        if not passed:
            sample = (
                df.filter(F.col(col_name).isNull())
                .limit(5)
                .collect()
            )
            failing = [str(row.asDict()) for row in sample]
        results.append(CheckResult(
            name=f"NOT NULL: {table}.{col_name}",
            category="Null Check",
            severity="HIGH",
            passed=passed,
            message=f"{null_count}/{total} rows have null {col_name}",
            failing_records=failing,
        ))
    return results


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession,
                                child_table: str, child_fk: str,
                                parent_table: str, parent_pk: str) -> CheckResult:
    """Verify all FK values in child table exist in parent table."""
    child = spark.table(child_table).select(F.col(child_fk).alias("_fk")).distinct()
    parent = spark.table(parent_table).select(F.col(parent_pk).alias("_pk")).distinct()
    orphans = child.join(parent, child["_fk"] == parent["_pk"], "left_anti")
    orphan_count = orphans.count()
    passed = orphan_count == 0
    failing = []
    if not passed:
        sample = orphans.limit(10).collect()
        failing = [str(row["_fk"]) for row in sample]
    return CheckResult(
        name=f"FK integrity: {child_table}.{child_fk} -> {parent_table}.{parent_pk}",
        category="Referential Integrity",
        severity="HIGH",
        passed=passed,
        message=f"{orphan_count} orphaned records found",
        failing_records=failing,
    )


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------

def check_active_loan_balance_positive(spark: SparkSession) -> CheckResult:
    """Active loans must have current_balance > 0."""
    loans = spark.table("loan_warehouse.loan_accounts")
    active = loans.filter(F.col("status") == "ACTIVE")
    bad = active.filter(
        F.col("current_balance").isNull() | (F.col("current_balance") <= 0)
    )
    bad_count = bad.count()
    failing = []
    if bad_count > 0:
        sample = bad.select("account_number", "current_balance", "status").limit(5).collect()
        failing = [str(row.asDict()) for row in sample]
    return CheckResult(
        name="Business rule: active loan balance > 0",
        category="Business Rule",
        severity="MEDIUM",
        passed=bad_count == 0,
        message=f"{bad_count} active loans with balance <= 0",
        failing_records=failing,
    )


def check_closed_loan_has_closed_date(spark: SparkSession) -> CheckResult:
    """Closed/defaulted loans should have an updated_at timestamp."""
    loans = spark.table("loan_warehouse.loan_accounts")
    closed = loans.filter(F.col("status").isin("CLOSED", "DEFAULT"))
    bad = closed.filter(F.col("updated_at").isNull())
    bad_count = bad.count()
    failing = []
    if bad_count > 0:
        sample = bad.select("account_number", "status", "updated_at").limit(5).collect()
        failing = [str(row.asDict()) for row in sample]
    return CheckResult(
        name="Business rule: closed/default loans have updated_at",
        category="Business Rule",
        severity="MEDIUM",
        passed=bad_count == 0,
        message=f"{bad_count} closed/default loans missing updated_at",
        failing_records=failing,
    )


def check_credit_score_range(spark: SparkSession) -> CheckResult:
    """Credit scores should be between 300 and 850 (FICO range)."""
    borrowers = spark.table("loan_warehouse.borrowers")
    has_score = borrowers.filter(F.col("credit_score").isNotNull())
    bad = has_score.filter(
        (F.col("credit_score") < 300) | (F.col("credit_score") > 850)
    )
    bad_count = bad.count()
    failing = []
    if bad_count > 0:
        sample = bad.select("external_id", "credit_score").limit(5).collect()
        failing = [str(row.asDict()) for row in sample]
    return CheckResult(
        name="Business rule: credit score 300-850",
        category="Business Rule",
        severity="MEDIUM",
        passed=bad_count == 0,
        message=f"{bad_count} borrowers with credit score outside 300-850",
        failing_records=failing,
    )


def check_payment_component_integrity(spark: SparkSession) -> CheckResult:
    """Payment components (principal + interest + escrow + late_fee) should sum to total."""
    payments = spark.table("loan_warehouse.payments")
    component_sum = (
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0))
    )
    bad = payments.filter(
        F.col("total_amount").isNotNull()
        & (F.abs(component_sum - F.col("total_amount")) > 0.01)
    )
    bad_count = bad.count()
    failing = []
    if bad_count > 0:
        sample = (
            bad.withColumn("_sum", component_sum)
            .select("_legacy_pmt_seq", "total_amount", "_sum")
            .limit(5).collect()
        )
        failing = [str(row.asDict()) for row in sample]
    return CheckResult(
        name="Business rule: payment components sum to total",
        category="Business Rule",
        severity="HIGH",
        passed=bad_count == 0,
        message=f"{bad_count} payments where components != total",
        failing_records=failing,
    )


def check_delinquency_status_consistency(spark: SparkSession) -> CheckResult:
    """Active loans with >0 delinquency_days are inconsistent."""
    loans = spark.table("loan_warehouse.loan_accounts")
    bad = loans.filter(
        (F.col("status") == "ACTIVE")
        & F.col("delinquency_days").isNotNull()
        & (F.col("delinquency_days") > 0)
    )
    bad_count = bad.count()
    failing = []
    if bad_count > 0:
        sample = bad.select("account_number", "status", "delinquency_days").limit(5).collect()
        failing = [str(row.asDict()) for row in sample]
    return CheckResult(
        name="Business rule: delinquency days consistent with status",
        category="Business Rule",
        severity="MEDIUM",
        passed=bad_count == 0,
        message=f"{bad_count} active loans with delinquency_days > 0",
        failing_records=failing,
    )


def check_ltv_reasonable_range(spark: SparkSession) -> CheckResult:
    """LTV percent should be between 0 and 200."""
    loans = spark.table("loan_warehouse.loan_accounts")
    has_ltv = loans.filter(F.col("ltv_percent").isNotNull())
    bad = has_ltv.filter(
        (F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200)
    )
    bad_count = bad.count()
    failing = []
    if bad_count > 0:
        sample = bad.select("account_number", "ltv_percent").limit(5).collect()
        failing = [str(row.asDict()) for row in sample]
    return CheckResult(
        name="Business rule: LTV percent 0-200%",
        category="Business Rule",
        severity="LOW",
        passed=bad_count == 0,
        message=f"{bad_count} loans with LTV outside 0-200%",
        failing_records=failing,
    )


# ---------------------------------------------------------------------------
# 5. Type/parse validation
# ---------------------------------------------------------------------------

def check_dates_not_null_after_parse(spark: SparkSession, table: str,
                                      date_columns: list[str]) -> list[CheckResult]:
    """Verify that date columns were successfully parsed (no nulls from parse failures)."""
    df = spark.table(table)
    results = []
    for col_name in date_columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        total = df.count()
        results.append(CheckResult(
            name=f"Date parse: {table}.{col_name}",
            category="Type Validation",
            severity="MEDIUM",
            passed=null_count == 0,
            message=f"{null_count}/{total} null after date parse",
        ))
    return results


# ---------------------------------------------------------------------------
# Master runner
# ---------------------------------------------------------------------------

def run_all_checks(spark: SparkSession,
                   source_counts: dict = None) -> list[CheckResult]:
    """
    Run all data quality checks and return results.

    Args:
        spark: SparkSession
        source_counts: dict mapping source table name to row count
                       (e.g., {"CDW_BORR_MSTR": 5, "CDW_LN_PROD": 5, ...})
                       If None, reconciliation checks are skipped.
    """
    results = []

    # 1. Row count reconciliation
    if source_counts:
        table_pairs = [
            ("CDW_BORR_MSTR", "loan_warehouse.borrowers"),
            ("CDW_LN_PROD", "loan_warehouse.loan_products"),
            ("CDW_LN_ACCT", "loan_warehouse.loan_accounts"),
            ("CDW_PMT_HIST", "loan_warehouse.payments"),
        ]
        for src, tgt in table_pairs:
            if src in source_counts:
                results.append(check_row_counts(spark, src, source_counts[src], tgt))

    # 2. Null checks on required fields
    results.extend(check_required_not_null(spark, "loan_warehouse.borrowers",
                                            ["external_id", "first_name", "last_name", "status"]))
    results.extend(check_required_not_null(spark, "loan_warehouse.loan_products",
                                            ["code", "name"]))
    results.extend(check_required_not_null(spark, "loan_warehouse.loan_accounts",
                                            ["account_number", "borrower_id", "product_id",
                                             "original_amount", "current_balance", "status"]))
    results.extend(check_required_not_null(spark, "loan_warehouse.payments",
                                            ["loan_account_id", "payment_date",
                                             "total_amount", "type", "status"]))

    # 3. Referential integrity
    results.append(check_referential_integrity(
        spark, "loan_warehouse.loan_accounts", "borrower_id",
        "loan_warehouse.borrowers", "borrower_id"))
    results.append(check_referential_integrity(
        spark, "loan_warehouse.loan_accounts", "product_id",
        "loan_warehouse.loan_products", "product_id"))
    results.append(check_referential_integrity(
        spark, "loan_warehouse.payments", "loan_account_id",
        "loan_warehouse.loan_accounts", "loan_id"))

    # 4. Business rules
    results.append(check_active_loan_balance_positive(spark))
    results.append(check_closed_loan_has_closed_date(spark))
    results.append(check_credit_score_range(spark))
    results.append(check_payment_component_integrity(spark))
    results.append(check_delinquency_status_consistency(spark))
    results.append(check_ltv_reasonable_range(spark))

    # 5. Date parse validation
    results.extend(check_dates_not_null_after_parse(
        spark, "loan_warehouse.borrowers", ["date_of_birth"]))
    results.extend(check_dates_not_null_after_parse(
        spark, "loan_warehouse.loan_accounts",
        ["origination_date", "maturity_date"]))
    results.extend(check_dates_not_null_after_parse(
        spark, "loan_warehouse.payments", ["payment_date"]))

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results: list[CheckResult],
                    output_path: str = None) -> str:
    """
    Generate a markdown DATA_QUALITY_REPORT from check results.
    Returns the report as a string. If output_path is given, also writes to file.
    """
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {now}",
        f"**Total checks:** {total} | **Passed:** {passed} | **Failed:** {failed}",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| # | Check | Category | Severity | Result | Details |",
        "|---|-------|----------|----------|--------|---------|",
    ]

    for i, r in enumerate(results, 1):
        status = "PASS" if r.passed else "**FAIL**"
        lines.append(
            f"| {i} | {r.name} | {r.category} | {r.severity} | {status} | {r.message} |"
        )

    # Detailed failures section
    failures = [r for r in results if not r.passed]
    if failures:
        lines.extend([
            "",
            "---",
            "",
            "## Failed Check Details",
            "",
        ])
        for r in failures:
            lines.append(f"### {r.name}")
            lines.append("")
            lines.append(f"- **Category:** {r.category}")
            lines.append(f"- **Severity:** {r.severity}")
            lines.append(f"- **Message:** {r.message}")
            if r.source_count is not None:
                lines.append(f"- **Source count:** {r.source_count}")
            if r.target_count is not None:
                lines.append(f"- **Target count:** {r.target_count}")
            if r.failing_records:
                lines.append("- **Sample failing records:**")
                for rec in r.failing_records[:5]:
                    lines.append(f"  - `{rec}`")
            lines.append("")

    # All-pass section
    passes = [r for r in results if r.passed]
    if passes:
        lines.extend([
            "---",
            "",
            "## Passed Checks",
            "",
        ])
        for r in passes:
            lines.append(f"- {r.name}: {r.message}")

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w") as f:
            f.write(report)
        print(f"Report written to {output_path}")

    return report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession = None,
        source_counts: dict = None,
        output_path: str = "/dbfs/reports/DATA_QUALITY_REPORT.md") -> list[CheckResult]:
    """Run all checks, generate report, return results."""
    if spark is None:
        spark = SparkSession.builder.getOrCreate()

    print("=" * 70)
    print("DATA QUALITY FRAMEWORK: Running post-ingestion checks")
    print("=" * 70)

    results = run_all_checks(spark, source_counts)
    generate_report(results, output_path)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    print(f"\nResults: {passed} passed, {failed} failed out of {len(results)} checks")

    if failed > 0:
        print("\nFAILED CHECKS:")
        for r in results:
            if not r.passed:
                print(f"  [{r.severity}] {r.name}: {r.message}")

    return results


if __name__ == "__main__":
    run()
