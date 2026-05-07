"""Data quality validation framework for the CDW-to-Delta-Lake migration.

Runs post-ingestion checks across all four target tables and produces a
structured report. Designed to be called from a Databricks notebook or as
a standalone module.

Check categories:
    1. Row count reconciliation (source vs. target)
    2. Null checks on required fields
    3. Referential integrity between loan/borrower/product/payment tables
    4. Business rule validation (domain-specific invariants)

Usage:
    from databricks.quality.data_quality_checks import run_all_checks
    report = run_all_checks(spark, source_counts={...})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


@dataclass
class CheckResult:
    """Result of a single data quality check."""

    category: str
    table: str
    check_name: str
    passed: bool
    details: str
    actual_value: Any = None
    expected_value: Any = None


@dataclass
class QualityReport:
    """Aggregated data quality report."""

    results: list[CheckResult] = field(default_factory=list)
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    def summary_lines(self) -> list[str]:
        lines = []
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"[{status}] {r.category} | {r.table} | {r.check_name}: {r.details}")
        return lines

    def to_markdown(self) -> str:
        """Generate a markdown report suitable for DATA_QUALITY_REPORT.md."""
        md = []
        md.append("# Data Quality Report")
        md.append("")
        md.append(f"**Run timestamp:** {self.run_timestamp}")
        md.append(f"**Overall result:** {'PASS' if self.all_passed else 'FAIL'}")
        md.append(f"**Checks passed:** {self.passed}/{self.total}")
        md.append(f"**Checks failed:** {self.failed}/{self.total}")
        md.append("")

        categories = sorted(set(r.category for r in self.results))
        for cat in categories:
            md.append(f"## {cat}")
            md.append("")
            md.append("| Status | Table | Check | Details |")
            md.append("|--------|-------|-------|---------|")
            for r in self.results:
                if r.category == cat:
                    icon = "PASS" if r.passed else "**FAIL**"
                    md.append(f"| {icon} | {r.table} | {r.check_name} | {r.details} |")
            md.append("")

        if self.failed > 0:
            md.append("## Failed Checks Detail")
            md.append("")
            for r in self.results:
                if not r.passed:
                    md.append(f"### {r.table} — {r.check_name}")
                    md.append(f"- **Category:** {r.category}")
                    md.append(f"- **Expected:** {r.expected_value}")
                    md.append(f"- **Actual:** {r.actual_value}")
                    md.append(f"- **Details:** {r.details}")
                    md.append("")

        return "\n".join(md)


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(
    spark: SparkSession,
    report: QualityReport,
    source_counts: dict[str, int],
    table_map: dict[str, str] | None = None,
) -> None:
    """Compare source row counts against target Delta table row counts.

    Parameters
    ----------
    source_counts : dict
        Mapping of table name → expected row count from the source system.
        Example: {"borrowers": 5, "loan_products": 5, "loan_accounts": 5, "payments": 10}
    table_map : dict or None
        Mapping of logical name → fully qualified Delta table name.
    """
    if table_map is None:
        table_map = {
            "borrowers": "loan_warehouse.borrowers",
            "loan_products": "loan_warehouse.loan_products",
            "loan_accounts": "loan_warehouse.loan_accounts",
            "payments": "loan_warehouse.payments",
        }

    for logical_name, expected in source_counts.items():
        fq_table = table_map.get(logical_name)
        if fq_table is None:
            report.add(CheckResult(
                category="Row Count Reconciliation",
                table=logical_name,
                check_name="table_exists",
                passed=False,
                details=f"No table mapping found for '{logical_name}'",
            ))
            continue

        try:
            actual = spark.table(fq_table).count()
        except Exception as e:
            report.add(CheckResult(
                category="Row Count Reconciliation",
                table=logical_name,
                check_name="table_readable",
                passed=False,
                details=f"Cannot read table {fq_table}: {e}",
            ))
            continue

        passed = actual == expected
        report.add(CheckResult(
            category="Row Count Reconciliation",
            table=logical_name,
            check_name="row_count_match",
            passed=passed,
            expected_value=expected,
            actual_value=actual,
            details=f"Expected {expected}, got {actual}" + ("" if passed else " — MISMATCH"),
        ))


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "borrowers": ["external_id", "first_name", "last_name"],
    "loan_products": ["code", "name", "type", "term_months", "rate_type"],
    "loan_accounts": [
        "account_number", "borrower_key", "product_key",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date",
    ],
    "payments": [
        "loan_account_key", "payment_date", "total_amount", "type", "status",
    ],
}


def check_nulls(
    spark: SparkSession,
    report: QualityReport,
    table_map: dict[str, str] | None = None,
) -> None:
    """Check that required fields have no NULLs in target tables."""
    if table_map is None:
        table_map = {
            "borrowers": "loan_warehouse.borrowers",
            "loan_products": "loan_warehouse.loan_products",
            "loan_accounts": "loan_warehouse.loan_accounts",
            "payments": "loan_warehouse.payments",
        }

    for logical_name, required_cols in REQUIRED_FIELDS.items():
        fq_table = table_map.get(logical_name)
        if fq_table is None:
            continue

        try:
            df = spark.table(fq_table)
        except Exception:
            continue

        total = df.count()
        for col_name in required_cols:
            if col_name not in df.columns:
                report.add(CheckResult(
                    category="Null Checks",
                    table=logical_name,
                    check_name=f"column_exists_{col_name}",
                    passed=False,
                    details=f"Column '{col_name}' not found in {fq_table}",
                ))
                continue

            null_count = df.filter(F.col(col_name).isNull()).count()
            passed = null_count == 0
            report.add(CheckResult(
                category="Null Checks",
                table=logical_name,
                check_name=f"no_nulls_{col_name}",
                passed=passed,
                expected_value=0,
                actual_value=null_count,
                details=f"{col_name}: {null_count}/{total} nulls" + ("" if passed else " — VIOLATION"),
            ))


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(
    spark: SparkSession,
    report: QualityReport,
    table_map: dict[str, str] | None = None,
) -> None:
    """Verify FK relationships between tables."""
    if table_map is None:
        table_map = {
            "borrowers": "loan_warehouse.borrowers",
            "loan_products": "loan_warehouse.loan_products",
            "loan_accounts": "loan_warehouse.loan_accounts",
            "payments": "loan_warehouse.payments",
        }

    # loan_accounts.borrower_key → borrowers.borrower_key
    _check_fk(
        spark, report, table_map,
        child_table="loan_accounts",
        child_col="borrower_key",
        parent_table="borrowers",
        parent_col="borrower_key",
    )

    # loan_accounts.product_key → loan_products.product_key
    _check_fk(
        spark, report, table_map,
        child_table="loan_accounts",
        child_col="product_key",
        parent_table="loan_products",
        parent_col="product_key",
    )

    # payments.loan_account_key → loan_accounts.loan_account_key
    _check_fk(
        spark, report, table_map,
        child_table="payments",
        child_col="loan_account_key",
        parent_table="loan_accounts",
        parent_col="loan_account_key",
    )


def _check_fk(
    spark: SparkSession,
    report: QualityReport,
    table_map: dict[str, str],
    child_table: str,
    child_col: str,
    parent_table: str,
    parent_col: str,
) -> None:
    try:
        child_df = spark.table(table_map[child_table])
        parent_df = spark.table(table_map[parent_table])
    except Exception as e:
        report.add(CheckResult(
            category="Referential Integrity",
            table=child_table,
            check_name=f"fk_{child_col}_to_{parent_table}",
            passed=False,
            details=f"Cannot read tables: {e}",
        ))
        return

    child_keys = child_df.select(F.col(child_col)).distinct()
    parent_keys = parent_df.select(F.col(parent_col).alias(child_col)).distinct()

    orphans = child_keys.join(parent_keys, on=child_col, how="left_anti")
    orphan_count = orphans.count()
    total_children = child_keys.count()
    passed = orphan_count == 0

    report.add(CheckResult(
        category="Referential Integrity",
        table=child_table,
        check_name=f"fk_{child_col}_to_{parent_table}",
        passed=passed,
        expected_value=0,
        actual_value=orphan_count,
        details=(
            f"{orphan_count}/{total_children} orphan keys in {child_table}.{child_col} "
            f"not found in {parent_table}.{parent_col}"
            + ("" if passed else " — INTEGRITY VIOLATION")
        ),
    ))


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------

def check_business_rules(
    spark: SparkSession,
    report: QualityReport,
    table_map: dict[str, str] | None = None,
) -> None:
    """Domain-specific business rule checks."""
    if table_map is None:
        table_map = {
            "borrowers": "loan_warehouse.borrowers",
            "loan_products": "loan_warehouse.loan_products",
            "loan_accounts": "loan_warehouse.loan_accounts",
            "payments": "loan_warehouse.payments",
        }

    # --- Loan Accounts rules ---
    try:
        loans_df = spark.table(table_map["loan_accounts"])
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            table="loan_accounts",
            check_name="table_readable",
            passed=False,
            details=f"Cannot read table: {e}",
        ))
        return

    # Rule 1: Active loans must have current_balance > 0
    active_loans = loans_df.filter(F.col("status") == "ACTIVE")
    active_count = active_loans.count()
    bad_balance = active_loans.filter(
        (F.col("current_balance").isNull()) | (F.col("current_balance") <= 0)
    ).count()
    passed = bad_balance == 0
    report.add(CheckResult(
        category="Business Rules",
        table="loan_accounts",
        check_name="active_loan_positive_balance",
        passed=passed,
        expected_value=0,
        actual_value=bad_balance,
        details=(
            f"{bad_balance}/{active_count} active loans have balance <= 0"
            + ("" if passed else " — RULE VIOLATION")
        ),
    ))

    # Rule 2: Active loans must have origination_date <= today
    future_orig = active_loans.filter(F.col("origination_date") > F.current_date()).count()
    passed = future_orig == 0
    report.add(CheckResult(
        category="Business Rules",
        table="loan_accounts",
        check_name="active_loan_origination_not_future",
        passed=passed,
        expected_value=0,
        actual_value=future_orig,
        details=f"{future_orig}/{active_count} active loans have future origination dates",
    ))

    # Rule 3: Maturity date must be after origination date
    bad_maturity = loans_df.filter(
        F.col("maturity_date").isNotNull()
        & F.col("origination_date").isNotNull()
        & (F.col("maturity_date") <= F.col("origination_date"))
    ).count()
    total_loans = loans_df.count()
    passed = bad_maturity == 0
    report.add(CheckResult(
        category="Business Rules",
        table="loan_accounts",
        check_name="maturity_after_origination",
        passed=passed,
        expected_value=0,
        actual_value=bad_maturity,
        details=f"{bad_maturity}/{total_loans} loans have maturity_date <= origination_date",
    ))

    # Rule 4: Interest rate must be positive for all loans
    bad_rate = loans_df.filter(
        (F.col("interest_rate").isNull()) | (F.col("interest_rate") <= 0)
    ).count()
    passed = bad_rate == 0
    report.add(CheckResult(
        category="Business Rules",
        table="loan_accounts",
        check_name="positive_interest_rate",
        passed=passed,
        expected_value=0,
        actual_value=bad_rate,
        details=f"{bad_rate}/{total_loans} loans have interest_rate <= 0 or NULL",
    ))

    # Rule 5: LTV percent should be between 0 and 200 (reasonable range)
    bad_ltv = loans_df.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    passed = bad_ltv == 0
    report.add(CheckResult(
        category="Business Rules",
        table="loan_accounts",
        check_name="ltv_in_range_0_200",
        passed=passed,
        expected_value=0,
        actual_value=bad_ltv,
        details=f"{bad_ltv}/{total_loans} loans have LTV outside 0–200%",
    ))

    # Rule 6: Loan status must be a known value
    valid_statuses = {"ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE"}
    unknown_status = loans_df.filter(~F.col("status").isin(valid_statuses)).count()
    passed = unknown_status == 0
    report.add(CheckResult(
        category="Business Rules",
        table="loan_accounts",
        check_name="valid_loan_status",
        passed=passed,
        expected_value=0,
        actual_value=unknown_status,
        details=f"{unknown_status}/{total_loans} loans have unknown status values",
    ))

    # --- Payment rules ---
    try:
        payments_df = spark.table(table_map["payments"])
    except Exception:
        return

    # Rule 7: Payment total_amount must be > 0
    total_payments = payments_df.count()
    bad_pmt_amt = payments_df.filter(
        (F.col("total_amount").isNull()) | (F.col("total_amount") <= 0)
    ).count()
    passed = bad_pmt_amt == 0
    report.add(CheckResult(
        category="Business Rules",
        table="payments",
        check_name="positive_payment_amount",
        passed=passed,
        expected_value=0,
        actual_value=bad_pmt_amt,
        details=f"{bad_pmt_amt}/{total_payments} payments have total_amount <= 0 or NULL",
    ))

    # Rule 8: Payment type must be a known value
    valid_types = {"REGULAR", "EXTRA", "PARTIAL", "PREPAYMENT"}
    unknown_type = payments_df.filter(~F.col("type").isin(valid_types)).count()
    passed = unknown_type == 0
    report.add(CheckResult(
        category="Business Rules",
        table="payments",
        check_name="valid_payment_type",
        passed=passed,
        expected_value=0,
        actual_value=unknown_type,
        details=f"{unknown_type}/{total_payments} payments have unknown type values",
    ))

    # Rule 9: Payment status must be a known value
    valid_pmt_statuses = {"POSTED", "REVERSED", "NSF", "PENDING"}
    unknown_pmt_status = payments_df.filter(~F.col("status").isin(valid_pmt_statuses)).count()
    passed = unknown_pmt_status == 0
    report.add(CheckResult(
        category="Business Rules",
        table="payments",
        check_name="valid_payment_status",
        passed=passed,
        expected_value=0,
        actual_value=unknown_pmt_status,
        details=f"{unknown_pmt_status}/{total_payments} payments have unknown status values",
    ))

    # --- Borrower rules ---
    try:
        borrowers_df = spark.table(table_map["borrowers"])
    except Exception:
        return

    # Rule 10: Credit score should be between 300 and 850
    total_borrowers = borrowers_df.count()
    bad_credit = borrowers_df.filter(
        F.col("credit_score").isNotNull()
        & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()
    passed = bad_credit == 0
    report.add(CheckResult(
        category="Business Rules",
        table="borrowers",
        check_name="credit_score_in_range",
        passed=passed,
        expected_value=0,
        actual_value=bad_credit,
        details=f"{bad_credit}/{total_borrowers} borrowers have credit_score outside 300–850",
    ))

    # Rule 11: Annual income should be non-negative
    bad_income = borrowers_df.filter(
        F.col("annual_income").isNotNull() & (F.col("annual_income") < 0)
    ).count()
    passed = bad_income == 0
    report.add(CheckResult(
        category="Business Rules",
        table="borrowers",
        check_name="non_negative_income",
        passed=passed,
        expected_value=0,
        actual_value=bad_income,
        details=f"{bad_income}/{total_borrowers} borrowers have negative annual_income",
    ))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all_checks(
    spark: SparkSession,
    source_counts: dict[str, int] | None = None,
    table_map: dict[str, str] | None = None,
    output_path: str | None = None,
) -> QualityReport:
    """Run all data quality checks and return a QualityReport.

    Parameters
    ----------
    spark : SparkSession
    source_counts : dict or None
        Expected row counts per table from the source system.
        If None, row count reconciliation is skipped.
    table_map : dict or None
        Override the default table name mapping.
    output_path : str or None
        If provided, write the markdown report to this DBFS/local path.

    Returns
    -------
    QualityReport
    """
    report = QualityReport()

    print("=" * 60)
    print("DATA QUALITY CHECKS")
    print(f"Run started: {report.run_timestamp}")
    print("=" * 60)

    # 1. Row count reconciliation
    if source_counts:
        print("\n--- Row Count Reconciliation ---")
        check_row_counts(spark, report, source_counts, table_map)

    # 2. Null checks
    print("\n--- Null Checks on Required Fields ---")
    check_nulls(spark, report, table_map)

    # 3. Referential integrity
    print("\n--- Referential Integrity ---")
    check_referential_integrity(spark, report, table_map)

    # 4. Business rules
    print("\n--- Business Rule Validation ---")
    check_business_rules(spark, report, table_map)

    # Print summary
    print("\n" + "=" * 60)
    print("CHECK RESULTS")
    print("=" * 60)
    for line in report.summary_lines():
        print(f"  {line}")
    print(f"\n  TOTAL: {report.passed} passed, {report.failed} failed out of {report.total}")
    print(f"  OVERALL: {'PASS' if report.all_passed else 'FAIL'}")
    print("=" * 60)

    # Write markdown report if path provided
    if output_path:
        md_content = report.to_markdown()
        spark.sparkContext.parallelize([md_content]).coalesce(1).saveAsTextFile(output_path)
        print(f"\nReport written to {output_path}")

    return report
