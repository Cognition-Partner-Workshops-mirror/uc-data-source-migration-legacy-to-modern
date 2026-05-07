"""
Data Quality Framework for the CDW -> Delta Lake migration.

Runs post-ingestion validation checks and produces a structured report:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts <-> borrowers, loan_products, payments
  4. Business rule validation (balance > 0 for active loans, closed date checks, etc.)

Usage (Databricks notebook):
    from quality.data_quality_checks import run_all_checks
    results = run_all_checks(spark, source_counts={...})
    generate_report(results, output_path="dbfs:/mnt/reports/DATA_QUALITY_REPORT.md")
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------
@dataclass
class CheckResult:
    category: str
    check_name: str
    passed: bool
    details: str
    severity: str = "ERROR"
    affected_rows: int = 0


@dataclass
class QualityReport:
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    results: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)


# ---------------------------------------------------------------------------
# 1. Row count reconciliation
# ---------------------------------------------------------------------------
def check_row_counts(
    spark: SparkSession,
    source_counts: dict,
    report: QualityReport,
) -> None:
    """Compare expected source row counts against target Delta tables."""
    table_map = {
        "CDW_BORR_MSTR": "loan_warehouse.borrowers",
        "CDW_LN_PROD": "loan_warehouse.loan_products",
        "CDW_LN_ACCT": "loan_warehouse.loan_accounts",
        "CDW_PMT_HIST": "loan_warehouse.payments",
    }

    for source_name, target_table in table_map.items():
        expected = source_counts.get(source_name)
        if expected is None:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"{source_name} count provided",
                passed=False,
                details=f"No source count supplied for {source_name}",
                severity="WARNING",
            ))
            continue

        actual = spark.table(target_table).count()
        match = actual == expected
        report.add(CheckResult(
            category="Row Count",
            check_name=f"{source_name} -> {target_table}",
            passed=match,
            details=(
                f"Source={expected}, Target={actual}"
                + ("" if match else " ** MISMATCH **")
            ),
            affected_rows=0 if match else abs(expected - actual),
        ))


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": [
        "external_id", "first_name", "last_name", "status",
    ],
    "loan_warehouse.loan_products": [
        "code", "name", "type", "term_months", "rate_type",
    ],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "status",
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount",
        "type", "status",
    ],
}


def check_required_nulls(
    spark: SparkSession,
    report: QualityReport,
) -> None:
    """Verify that required columns contain no NULL values."""
    for table, columns in REQUIRED_FIELDS.items():
        df = spark.table(table)
        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table}.{col_name} NOT NULL",
                passed=null_count == 0,
                details=(
                    f"No nulls found"
                    if null_count == 0
                    else f"{null_count} null(s) in required column"
                ),
                affected_rows=null_count,
            ))


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------
def check_referential_integrity(
    spark: SparkSession,
    report: QualityReport,
) -> None:
    """Verify foreign key relationships between tables."""

    # loan_accounts.borrower_id -> borrowers.borrower_id
    loans = spark.table("loan_warehouse.loan_accounts")
    borrowers = spark.table("loan_warehouse.borrowers")
    orphan_borrower = loans.join(
        borrowers,
        loans["borrower_id"] == borrowers["borrower_id"],
        "left_anti",
    ).count()
    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.borrower_id -> borrowers",
        passed=orphan_borrower == 0,
        details=(
            "All loan accounts reference a valid borrower"
            if orphan_borrower == 0
            else f"{orphan_borrower} loan(s) reference non-existent borrower"
        ),
        affected_rows=orphan_borrower,
    ))

    # loan_accounts.product_id -> loan_products.product_id
    products = spark.table("loan_warehouse.loan_products")
    orphan_product = loans.join(
        products,
        loans["product_id"] == products["product_id"],
        "left_anti",
    ).count()
    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.product_id -> loan_products",
        passed=orphan_product == 0,
        details=(
            "All loan accounts reference a valid product"
            if orphan_product == 0
            else f"{orphan_product} loan(s) reference non-existent product"
        ),
        affected_rows=orphan_product,
    ))

    # payments.loan_account_id -> loan_accounts.loan_account_id
    payments = spark.table("loan_warehouse.payments")
    orphan_payment = payments.join(
        loans,
        payments["loan_account_id"] == loans["loan_account_id"],
        "left_anti",
    ).count()
    report.add(CheckResult(
        category="Referential Integrity",
        check_name="payments.loan_account_id -> loan_accounts",
        passed=orphan_payment == 0,
        details=(
            "All payments reference a valid loan account"
            if orphan_payment == 0
            else f"{orphan_payment} payment(s) reference non-existent loan account"
        ),
        affected_rows=orphan_payment,
    ))


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------
def check_business_rules(
    spark: SparkSession,
    report: QualityReport,
) -> None:
    """Validate domain-specific business rules."""

    loans = spark.table("loan_warehouse.loan_accounts")
    payments = spark.table("loan_warehouse.payments")

    # Rule 1: Active loans must have current_balance > 0
    active_zero = loans.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans have positive balance",
        passed=active_zero == 0,
        details=(
            "All active loans have current_balance > 0"
            if active_zero == 0
            else f"{active_zero} active loan(s) with balance <= 0"
        ),
        affected_rows=active_zero,
    ))

    # Rule 2: Active loans must have a future or current next_payment_date
    # (relative to migration date; we check for non-null)
    active_no_next = loans.filter(
        (F.col("status") == "ACTIVE") & F.col("next_payment_date").isNull()
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans have next_payment_date",
        passed=active_no_next == 0,
        details=(
            "All active loans have a next_payment_date set"
            if active_no_next == 0
            else f"{active_no_next} active loan(s) missing next_payment_date"
        ),
        severity="WARNING",
        affected_rows=active_no_next,
    ))

    # Rule 3: Loan origination_date must be before maturity_date
    bad_dates = loans.filter(
        F.col("origination_date") >= F.col("maturity_date")
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="origination_date < maturity_date",
        passed=bad_dates == 0,
        details=(
            "All loans have origination before maturity"
            if bad_dates == 0
            else f"{bad_dates} loan(s) have origination >= maturity"
        ),
        affected_rows=bad_dates,
    ))

    # Rule 4: Interest rate must be within a sane range (0, 30]
    bad_rate = loans.filter(
        (F.col("interest_rate") <= 0) | (F.col("interest_rate") > 30)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Interest rate in (0, 30]",
        passed=bad_rate == 0,
        details=(
            "All interest rates are within expected range"
            if bad_rate == 0
            else f"{bad_rate} loan(s) have out-of-range interest rate"
        ),
        severity="WARNING",
        affected_rows=bad_rate,
    ))

    # Rule 5: LTV percent should be between 0 and 200 if present
    bad_ltv = loans.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="LTV percent in [0, 200]",
        passed=bad_ltv == 0,
        details=(
            "All LTV values are within expected range"
            if bad_ltv == 0
            else f"{bad_ltv} loan(s) have out-of-range LTV"
        ),
        severity="WARNING",
        affected_rows=bad_ltv,
    ))

    # Rule 6: Payment total should equal sum of components (within rounding tolerance)
    pmt_check = payments.withColumn(
        "_sum_components",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0)),
    )
    tolerance = 0.02  # allow 2-cent rounding tolerance
    bad_pmt_sum = pmt_check.filter(
        F.abs(F.col("total_amount") - F.col("_sum_components")) > tolerance
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Payment total = principal + interest + escrow + late_fee",
        passed=bad_pmt_sum == 0,
        details=(
            "All payment totals reconcile with component amounts"
            if bad_pmt_sum == 0
            else f"{bad_pmt_sum} payment(s) where total != sum of components (tolerance={tolerance})"
        ),
        affected_rows=bad_pmt_sum,
    ))

    # Rule 7: Delinquency days should be 0 for non-delinquent active loans
    # (just a warning-level sanity check)
    delinquent = loans.filter(
        (F.col("status") == "ACTIVE")
        & (F.col("delinquency_days") > 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loan delinquency awareness",
        passed=True,  # informational
        details=f"{delinquent} active loan(s) have delinquency_days > 0 (informational)",
        severity="INFO",
        affected_rows=delinquent,
    ))

    # Rule 8: Credit score should be in [300, 850] if present
    borrowers = spark.table("loan_warehouse.borrowers")
    bad_credit = borrowers.filter(
        F.col("credit_score").isNotNull()
        & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Credit score in [300, 850]",
        passed=bad_credit == 0,
        details=(
            "All credit scores are within expected range"
            if bad_credit == 0
            else f"{bad_credit} borrower(s) have out-of-range credit score"
        ),
        severity="WARNING",
        affected_rows=bad_credit,
    ))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_all_checks(
    spark: SparkSession,
    source_counts: Optional[dict] = None,
) -> QualityReport:
    """Execute every data quality check and return the consolidated report."""
    report = QualityReport()

    if source_counts:
        check_row_counts(spark, source_counts, report)

    check_required_nulls(spark, report)
    check_referential_integrity(spark, report)
    check_business_rules(spark, report)

    return report


# ---------------------------------------------------------------------------
# Markdown report generator
# ---------------------------------------------------------------------------
def generate_report(
    report: QualityReport,
    output_path: Optional[str] = None,
) -> str:
    """Render the QualityReport as a Markdown document.

    If ``output_path`` is provided, writes to DBFS / local path.
    Always returns the Markdown string.
    """
    lines = [
        "# Data Quality Report",
        "",
        f"**Run timestamp:** {report.run_timestamp}",
        f"**Total checks:** {report.total}",
        f"**Passed:** {report.passed}",
        f"**Failed:** {report.failed}",
        "",
        "---",
        "",
    ]

    # Group by category
    categories = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for cat, checks in categories.items():
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Status | Check | Severity | Details | Affected Rows |")
        lines.append("|--------|-------|----------|---------|---------------|")
        for c in checks:
            icon = "PASS" if c.passed else "FAIL"
            lines.append(
                f"| {icon} | {c.check_name} | {c.severity} | "
                f"{c.details} | {c.affected_rows} |"
            )
        lines.append("")

    # Summary
    lines.append("---")
    lines.append("")
    if report.failed == 0:
        lines.append("**Result: ALL CHECKS PASSED**")
    else:
        lines.append(
            f"**Result: {report.failed} CHECK(S) FAILED** - review details above"
        )

    md_content = "\n".join(lines) + "\n"

    if output_path:
        with open(output_path, "w") as f:
            f.write(md_content)
        print(f"Report written to {output_path}")

    return md_content
