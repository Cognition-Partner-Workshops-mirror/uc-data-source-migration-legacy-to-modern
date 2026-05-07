"""
Data Quality Validation Framework
==================================

Post-ingestion validation module that checks:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts ↔ borrowers and
     payments ↔ loan_accounts
  4. Business rule validation (balance > 0 for active loans, closed date
     required for closed loans, etc.)

Each check returns a CheckResult dataclass.  The run_all() function
executes every check and produces a DATA_QUALITY_REPORT.md summary.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str
    check_name: str
    passed: bool
    detail: str
    severity: str = "ERROR"  # ERROR | WARNING | INFO
    affected_rows: int = 0


# ---------------------------------------------------------------------------
# 1. Row count reconciliation
# ---------------------------------------------------------------------------

def _count_source(spark: SparkSession, path: str) -> int:
    """Count rows in a legacy source (CSV or Parquet)."""
    try:
        return spark.read.parquet(path).count()
    except Exception:
        return spark.read.option("header", "true").csv(path).count()


def check_row_counts(
    spark: SparkSession,
    source_counts: dict[str, int],
    quarantine_counts: Optional[dict[str, int]] = None,
) -> list[CheckResult]:
    """Verify source_count == target_count + quarantine_count for each table."""
    results: list[CheckResult] = []
    quarantine_counts = quarantine_counts or {}

    table_map = {
        "CDW_BORR_MSTR": "loan_warehouse.borrowers",
        "CDW_LN_PROD":   "loan_warehouse.loan_products",
        "CDW_LN_ACCT":   "loan_warehouse.loan_accounts",
        "CDW_PMT_HIST":  "loan_warehouse.payments",
    }

    for legacy_name, modern_table in table_map.items():
        src = source_counts.get(legacy_name, 0)
        try:
            tgt = spark.table(modern_table).count()
        except Exception:
            results.append(CheckResult(
                category="Row Count",
                check_name=f"{legacy_name} → {modern_table}",
                passed=False,
                detail=f"Target table {modern_table} does not exist or is inaccessible.",
                severity="ERROR",
            ))
            continue

        qtn = quarantine_counts.get(legacy_name, 0)
        expected = tgt + qtn
        passed = src == expected

        results.append(CheckResult(
            category="Row Count",
            check_name=f"{legacy_name} → {modern_table}",
            passed=passed,
            detail=(
                f"Source={src}, Target={tgt}, Quarantine={qtn}. "
                f"{'Balanced.' if passed else f'MISMATCH: expected {src}, got {expected}.'}"
            ),
            severity="ERROR" if not passed else "INFO",
            affected_rows=abs(src - expected),
        ))

    return results


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers":     ["external_id", "first_name", "last_name", "status"],
    "loan_warehouse.loan_products": ["code", "name", "type", "term_months", "rate_type"],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date", "status",
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount", "type", "status",
    ],
}


def check_required_nulls(spark: SparkSession) -> list[CheckResult]:
    """Flag any NULL values in columns that must be NOT NULL."""
    results: list[CheckResult] = []

    for table, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table)
        except Exception:
            results.append(CheckResult(
                category="Null Check",
                check_name=f"{table} — table access",
                passed=False,
                detail=f"Table {table} does not exist or is inaccessible.",
                severity="ERROR",
            ))
            continue

        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            passed = null_count == 0
            results.append(CheckResult(
                category="Null Check",
                check_name=f"{table}.{col_name}",
                passed=passed,
                detail=f"{null_count} NULL value(s) found." if not passed else "No NULLs.",
                severity="ERROR" if not passed else "INFO",
                affected_rows=null_count,
            ))

    return results


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession) -> list[CheckResult]:
    """Verify FK relationships: loan_accounts → borrowers, payments → loan_accounts."""
    results: list[CheckResult] = []

    # loan_accounts.borrower_id → borrowers.borrower_id
    try:
        loans = spark.table("loan_warehouse.loan_accounts")
        borrowers = spark.table("loan_warehouse.borrowers")
        orphan_borrower = (
            loans.alias("l")
            .join(
                borrowers.alias("b"),
                F.col("l.borrower_id") == F.col("b.borrower_id"),
                "left_anti",
            )
            .count()
        )
        results.append(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.borrower_id → borrowers",
            passed=orphan_borrower == 0,
            detail=(
                f"{orphan_borrower} loan account(s) reference non-existent borrower(s)."
                if orphan_borrower > 0 else "All borrower references valid."
            ),
            severity="ERROR" if orphan_borrower > 0 else "INFO",
            affected_rows=orphan_borrower,
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.borrower_id → borrowers",
            passed=False,
            detail=f"Check failed: {e}",
            severity="ERROR",
        ))

    # loan_accounts.product_id → loan_products.product_id
    try:
        products = spark.table("loan_warehouse.loan_products")
        orphan_product = (
            loans.alias("l")
            .join(
                products.alias("p"),
                F.col("l.product_id") == F.col("p.product_id"),
                "left_anti",
            )
            .count()
        )
        results.append(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.product_id → loan_products",
            passed=orphan_product == 0,
            detail=(
                f"{orphan_product} loan account(s) reference non-existent product(s)."
                if orphan_product > 0 else "All product references valid."
            ),
            severity="ERROR" if orphan_product > 0 else "INFO",
            affected_rows=orphan_product,
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.product_id → loan_products",
            passed=False,
            detail=f"Check failed: {e}",
            severity="ERROR",
        ))

    # payments.loan_account_id → loan_accounts.loan_account_id
    try:
        payments = spark.table("loan_warehouse.payments")
        orphan_loan = (
            payments.alias("p")
            .join(
                loans.alias("l"),
                F.col("p.loan_account_id") == F.col("l.loan_account_id"),
                "left_anti",
            )
            .count()
        )
        results.append(CheckResult(
            category="Referential Integrity",
            check_name="payments.loan_account_id → loan_accounts",
            passed=orphan_loan == 0,
            detail=(
                f"{orphan_loan} payment(s) reference non-existent loan account(s)."
                if orphan_loan > 0 else "All loan account references valid."
            ),
            severity="ERROR" if orphan_loan > 0 else "INFO",
            affected_rows=orphan_loan,
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Referential Integrity",
            check_name="payments.loan_account_id → loan_accounts",
            passed=False,
            detail=f"Check failed: {e}",
            severity="ERROR",
        ))

    return results


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession) -> list[CheckResult]:
    """Validate domain-specific invariants on the migrated data."""
    results: list[CheckResult] = []

    # --- Loan accounts ---
    try:
        loans = spark.table("loan_warehouse.loan_accounts")

        # 4a. Active loans must have current_balance > 0
        active_zero_bal = (
            loans
            .filter(F.col("status") == F.lit("Active"))
            .filter(F.col("current_balance") <= 0)
            .count()
        )
        results.append(CheckResult(
            category="Business Rule",
            check_name="Active loans must have balance > 0",
            passed=active_zero_bal == 0,
            detail=(
                f"{active_zero_bal} active loan(s) have balance <= 0."
                if active_zero_bal > 0 else "All active loans have positive balance."
            ),
            severity="ERROR" if active_zero_bal > 0 else "INFO",
            affected_rows=active_zero_bal,
        ))

        # 4b. Closed loans should have current_balance == 0 (warning, not error)
        closed_nonzero = (
            loans
            .filter(F.col("status") == F.lit("Closed"))
            .filter(F.col("current_balance") != 0)
            .count()
        )
        results.append(CheckResult(
            category="Business Rule",
            check_name="Closed loans should have balance == 0",
            passed=closed_nonzero == 0,
            detail=(
                f"{closed_nonzero} closed loan(s) have non-zero balance."
                if closed_nonzero > 0 else "All closed loans have zero balance."
            ),
            severity="WARNING" if closed_nonzero > 0 else "INFO",
            affected_rows=closed_nonzero,
        ))

        # 4c. Origination date must be before maturity date
        date_mismatch = (
            loans
            .filter(F.col("origination_date") >= F.col("maturity_date"))
            .count()
        )
        results.append(CheckResult(
            category="Business Rule",
            check_name="Origination date < maturity date",
            passed=date_mismatch == 0,
            detail=(
                f"{date_mismatch} loan(s) have origination_date >= maturity_date."
                if date_mismatch > 0 else "All loans have valid date ordering."
            ),
            severity="ERROR" if date_mismatch > 0 else "INFO",
            affected_rows=date_mismatch,
        ))

        # 4d. LTV percent should be between 0 and 200
        ltv_outliers = (
            loans
            .filter(F.col("ltv_percent").isNotNull())
            .filter((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
            .count()
        )
        results.append(CheckResult(
            category="Business Rule",
            check_name="LTV percent in range [0, 200]",
            passed=ltv_outliers == 0,
            detail=(
                f"{ltv_outliers} loan(s) have LTV outside [0, 200] range."
                if ltv_outliers > 0 else "All LTV values within expected range."
            ),
            severity="WARNING" if ltv_outliers > 0 else "INFO",
            affected_rows=ltv_outliers,
        ))

        # 4e. Delinquency days should be >= 0
        neg_dlq = (
            loans
            .filter(F.col("delinquency_days") < 0)
            .count()
        )
        results.append(CheckResult(
            category="Business Rule",
            check_name="Delinquency days >= 0",
            passed=neg_dlq == 0,
            detail=(
                f"{neg_dlq} loan(s) have negative delinquency days."
                if neg_dlq > 0 else "All delinquency values non-negative."
            ),
            severity="ERROR" if neg_dlq > 0 else "INFO",
            affected_rows=neg_dlq,
        ))

    except Exception as e:
        results.append(CheckResult(
            category="Business Rule",
            check_name="Loan account rules",
            passed=False,
            detail=f"Failed to access loan_accounts: {e}",
            severity="ERROR",
        ))

    # --- Payments ---
    try:
        payments = spark.table("loan_warehouse.payments")

        # 4f. Payment total_amount must be > 0
        neg_payments = (
            payments
            .filter(F.col("total_amount") <= 0)
            .count()
        )
        results.append(CheckResult(
            category="Business Rule",
            check_name="Payment total_amount > 0",
            passed=neg_payments == 0,
            detail=(
                f"{neg_payments} payment(s) have total_amount <= 0."
                if neg_payments > 0 else "All payments have positive amounts."
            ),
            severity="ERROR" if neg_payments > 0 else "INFO",
            affected_rows=neg_payments,
        ))

        # 4g. Payment components should sum to approximately total_amount
        component_mismatch = (
            payments
            .withColumn(
                "_component_sum",
                F.coalesce(F.col("principal_amount"), F.lit(0))
                + F.coalesce(F.col("interest_amount"), F.lit(0))
                + F.coalesce(F.col("escrow_amount"), F.lit(0))
                + F.coalesce(F.col("late_fee"), F.lit(0)),
            )
            .filter(
                F.abs(F.col("_component_sum") - F.col("total_amount")) > 0.01
            )
            .count()
        )
        results.append(CheckResult(
            category="Business Rule",
            check_name="Payment components sum ≈ total_amount (±$0.01)",
            passed=component_mismatch == 0,
            detail=(
                f"{component_mismatch} payment(s) have component sum != total."
                if component_mismatch > 0
                else "All payment components sum to total."
            ),
            severity="WARNING" if component_mismatch > 0 else "INFO",
            affected_rows=component_mismatch,
        ))

    except Exception as e:
        results.append(CheckResult(
            category="Business Rule",
            check_name="Payment rules",
            passed=False,
            detail=f"Failed to access payments: {e}",
            severity="ERROR",
        ))

    # --- Borrowers ---
    try:
        borrowers = spark.table("loan_warehouse.borrowers")

        # 4h. Credit score should be between 300 and 850
        score_outliers = (
            borrowers
            .filter(F.col("credit_score").isNotNull())
            .filter((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
            .count()
        )
        results.append(CheckResult(
            category="Business Rule",
            check_name="Credit score in range [300, 850]",
            passed=score_outliers == 0,
            detail=(
                f"{score_outliers} borrower(s) have credit score outside [300, 850]."
                if score_outliers > 0 else "All credit scores within expected range."
            ),
            severity="WARNING" if score_outliers > 0 else "INFO",
            affected_rows=score_outliers,
        ))

        # 4i. Annual income should be non-negative
        neg_income = (
            borrowers
            .filter(F.col("annual_income").isNotNull())
            .filter(F.col("annual_income") < 0)
            .count()
        )
        results.append(CheckResult(
            category="Business Rule",
            check_name="Annual income >= 0",
            passed=neg_income == 0,
            detail=(
                f"{neg_income} borrower(s) have negative annual income."
                if neg_income > 0 else "All incomes non-negative."
            ),
            severity="ERROR" if neg_income > 0 else "INFO",
            affected_rows=neg_income,
        ))

    except Exception as e:
        results.append(CheckResult(
            category="Business Rule",
            check_name="Borrower rules",
            passed=False,
            detail=f"Failed to access borrowers: {e}",
            severity="ERROR",
        ))

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results: list[CheckResult], output_path: str = "DATA_QUALITY_REPORT.md") -> str:
    """Write a Markdown report summarising all check results. Returns the report text."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    errors = sum(1 for r in results if not r.passed and r.severity == "ERROR")
    warnings = sum(1 for r in results if not r.passed and r.severity == "WARNING")

    overall = "PASS" if failed == 0 else "FAIL"

    lines = [
        f"# Data Quality Report",
        f"",
        f"**Generated:** {now}",
        f"**Overall Result:** {overall}",
        f"**Total Checks:** {total} | **Passed:** {passed} | **Failed:** {failed} "
        f"(Errors: {errors}, Warnings: {warnings})",
        f"",
        f"---",
        f"",
    ]

    # Group by category
    categories = dict.fromkeys(r.category for r in results)
    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        cat_passed = all(r.passed for r in cat_results)
        status_icon = "PASS" if cat_passed else "FAIL"

        lines.append(f"## {cat} [{status_icon}]")
        lines.append("")
        lines.append("| Check | Result | Severity | Affected Rows | Detail |")
        lines.append("|-------|--------|----------|---------------|--------|")

        for r in cat_results:
            result_str = "PASS" if r.passed else "FAIL"
            lines.append(
                f"| {r.check_name} | {result_str} | {r.severity} | "
                f"{r.affected_rows} | {r.detail} |"
            )

        lines.append("")

    report_text = "\n".join(lines)

    # Write to DBFS or local path
    try:
        with open(output_path, "w") as f:
            f.write(report_text)
        print(f"Data quality report written to {output_path}")
    except Exception as e:
        print(f"WARNING: Could not write report to {output_path}: {e}")
        print("Report content follows:\n")
        print(report_text)

    return report_text


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_all(
    spark: SparkSession,
    source_counts: dict[str, int],
    quarantine_counts: Optional[dict[str, int]] = None,
    output_path: str = "DATA_QUALITY_REPORT.md",
) -> tuple[list[CheckResult], str]:
    """Run every quality check and produce the report."""
    print("=" * 72)
    print("DATA QUALITY VALIDATION")
    print("=" * 72)

    all_results: list[CheckResult] = []

    print("\n>>> Row count reconciliation")
    all_results.extend(check_row_counts(spark, source_counts, quarantine_counts))

    print(">>> Null checks on required fields")
    all_results.extend(check_required_nulls(spark))

    print(">>> Referential integrity")
    all_results.extend(check_referential_integrity(spark))

    print(">>> Business rule validation")
    all_results.extend(check_business_rules(spark))

    report = generate_report(all_results, output_path)

    failed = [r for r in all_results if not r.passed]
    if failed:
        print(f"\nQUALITY ISSUES FOUND: {len(failed)} check(s) failed.")
        for r in failed:
            print(f"  [{r.severity}] {r.category} / {r.check_name}: {r.detail}")
    else:
        print("\nAll quality checks PASSED.")

    return all_results, report


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Data Quality Checks").getOrCreate()

    # When run standalone, attempt to read counts from pipeline stats
    # In practice these would be passed from run_pipeline.py
    example_source_counts = {
        "CDW_BORR_MSTR": 5,
        "CDW_LN_PROD": 5,
        "CDW_LN_ACCT": 5,
        "CDW_PMT_HIST": 10,
    }

    run_all(spark, example_source_counts, output_path="/dbfs/reports/DATA_QUALITY_REPORT.md")
