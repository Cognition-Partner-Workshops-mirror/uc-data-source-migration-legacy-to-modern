"""
Data Quality Validation Framework

Runs post-ingestion checks against the migrated Delta Lake tables:
  1. Row count reconciliation (source vs target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts <-> borrowers / loan_products
     and payments <-> loan_accounts
  4. Business rule validation (balance > 0 for active loans, etc.)

Produces a structured results list consumed by the report generator.

Usage (Databricks notebook):
    %run ./data_quality_checks
    results = run_all_checks(spark, source_counts)
"""

from dataclasses import dataclass, field
from typing import List

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


@dataclass
class CheckResult:
    """Single data quality check result."""

    category: str
    table: str
    check_name: str
    passed: bool
    detail: str
    severity: str = "ERROR"  # ERROR, WARNING, INFO


@dataclass
class QualityReport:
    """Aggregated quality report."""

    results: List[CheckResult] = field(default_factory=list)

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

    def add(self, result: CheckResult):
        self.results.append(result)

    def summary(self) -> str:
        return f"Total: {self.total} | Passed: {self.passed} | Failed: {self.failed}"


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------
def check_row_counts(spark: SparkSession, source_counts: dict, report: QualityReport):
    """
    Compare source record counts against target table counts.
    source_counts: dict like {"borrowers": 5, "loan_products": 5, ...}
    """
    table_map = {
        "borrowers": "loan_warehouse.borrowers",
        "loan_products": "loan_warehouse.loan_products",
        "loan_accounts": "loan_warehouse.loan_accounts",
        "payments": "loan_warehouse.payments",
    }

    for key, table_name in table_map.items():
        expected = source_counts.get(key, 0)
        try:
            actual = spark.table(table_name).count()
            passed = actual == expected
            detail = f"Expected {expected} rows, found {actual}"
            if not passed:
                detail += f" (delta: {actual - expected:+d})"
        except Exception as e:
            passed = False
            actual = -1
            detail = f"Could not read table: {e}"

        report.add(
            CheckResult(
                category="Row Count",
                table=key,
                check_name=f"row_count_{key}",
                passed=passed,
                detail=detail,
                severity="ERROR",
            )
        )
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] Row count {key}: {detail}")


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": ["external_id", "first_name", "last_name"],
    "loan_warehouse.loan_products": ["code", "name", "type", "term_months", "rate_type"],
    "loan_warehouse.loan_accounts": [
        "account_number",
        "borrower_external_id",
        "product_code",
        "original_amount",
        "current_balance",
        "interest_rate",
        "term_months",
        "monthly_payment",
        "origination_date",
        "maturity_date",
        "status",
    ],
    "loan_warehouse.payments": [
        "loan_account_number",
        "payment_date",
        "total_amount",
        "type",
        "status",
    ],
}


def check_nulls(spark: SparkSession, report: QualityReport):
    """Check that required fields have no null values in target tables."""
    for table_name, columns in REQUIRED_FIELDS.items():
        short_name = table_name.split(".")[-1]
        try:
            df = spark.table(table_name)
        except Exception as e:
            report.add(
                CheckResult(
                    category="Null Check",
                    table=short_name,
                    check_name=f"null_check_{short_name}_read",
                    passed=False,
                    detail=f"Could not read table: {e}",
                    severity="ERROR",
                )
            )
            continue

        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            passed = null_count == 0
            detail = f"Column '{col_name}': {null_count} null(s) found"

            report.add(
                CheckResult(
                    category="Null Check",
                    table=short_name,
                    check_name=f"null_{short_name}_{col_name}",
                    passed=passed,
                    detail=detail,
                    severity="ERROR",
                )
            )
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] Null check {short_name}.{col_name}: {detail}")


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------
def check_referential_integrity(spark: SparkSession, report: QualityReport):
    """
    Verify FK-like relationships:
      - loan_accounts.borrower_external_id -> borrowers.external_id
      - loan_accounts.product_code -> loan_products.code
      - payments.loan_account_number -> loan_accounts.account_number
    """
    checks = [
        {
            "name": "loan_accounts -> borrowers",
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "borrower_external_id",
            "parent_table": "loan_warehouse.borrowers",
            "parent_col": "external_id",
        },
        {
            "name": "loan_accounts -> loan_products",
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "product_code",
            "parent_table": "loan_warehouse.loan_products",
            "parent_col": "code",
        },
        {
            "name": "payments -> loan_accounts",
            "child_table": "loan_warehouse.payments",
            "child_col": "loan_account_number",
            "parent_table": "loan_warehouse.loan_accounts",
            "parent_col": "account_number",
        },
    ]

    for chk in checks:
        try:
            child_df = spark.table(chk["child_table"])
            parent_df = spark.table(chk["parent_table"])

            orphans = child_df.join(
                parent_df,
                child_df[chk["child_col"]] == parent_df[chk["parent_col"]],
                "left_anti",
            )
            orphan_count = orphans.count()
            passed = orphan_count == 0
            detail = (
                f"{chk['name']}: {orphan_count} orphaned record(s)"
                if not passed
                else f"{chk['name']}: all references valid"
            )
        except Exception as e:
            passed = False
            detail = f"{chk['name']}: check failed - {e}"

        report.add(
            CheckResult(
                category="Referential Integrity",
                table=chk["child_table"].split(".")[-1],
                check_name=f"ri_{chk['name'].replace(' ', '_').replace('->', 'to')}",
                passed=passed,
                detail=detail,
                severity="ERROR",
            )
        )
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] RI {chk['name']}: {detail}")


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------
def check_business_rules(spark: SparkSession, report: QualityReport):
    """
    Validate domain-specific business rules:
      - Active loans must have current_balance > 0
      - Closed loans should have a maturity_date <= today (or closed_date if present)
      - Delinquency days >= 0
      - Payment total_amount must equal principal + interest + escrow + late_fee
      - Credit score between 300 and 850 (when not null)
    """
    # --- Rule: Active loans must have positive balance ---
    try:
        loans_df = spark.table("loan_warehouse.loan_accounts")

        active_zero_bal = loans_df.filter(
            (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
        ).count()
        passed = active_zero_bal == 0
        detail = (
            f"Active loans with balance <= 0: {active_zero_bal}"
            if not passed
            else "All active loans have positive balance"
        )
        report.add(
            CheckResult(
                category="Business Rule",
                table="loan_accounts",
                check_name="biz_active_positive_balance",
                passed=passed,
                detail=detail,
                severity="ERROR",
            )
        )
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] Active loan balance: {detail}")
    except Exception as e:
        report.add(
            CheckResult(
                category="Business Rule",
                table="loan_accounts",
                check_name="biz_active_positive_balance",
                passed=False,
                detail=f"Check failed: {e}",
                severity="ERROR",
            )
        )

    # --- Rule: Delinquency days must be >= 0 ---
    try:
        neg_delinquency = loans_df.filter(F.col("delinquency_days") < 0).count()
        passed = neg_delinquency == 0
        detail = (
            f"Records with negative delinquency_days: {neg_delinquency}"
            if not passed
            else "All delinquency_days >= 0"
        )
        report.add(
            CheckResult(
                category="Business Rule",
                table="loan_accounts",
                check_name="biz_non_negative_delinquency",
                passed=passed,
                detail=detail,
                severity="WARNING",
            )
        )
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] Delinquency days: {detail}")
    except Exception as e:
        report.add(
            CheckResult(
                category="Business Rule",
                table="loan_accounts",
                check_name="biz_non_negative_delinquency",
                passed=False,
                detail=f"Check failed: {e}",
                severity="WARNING",
            )
        )

    # --- Rule: Closed loans should have status = CLOSED (informational) ---
    try:
        closed_future_maturity = loans_df.filter(
            (F.col("status") == "CLOSED") & (F.col("maturity_date") > F.current_date())
        ).count()
        passed = closed_future_maturity == 0
        detail = (
            f"Closed loans with future maturity date: {closed_future_maturity}"
            if not passed
            else "All closed loans have past/present maturity dates"
        )
        report.add(
            CheckResult(
                category="Business Rule",
                table="loan_accounts",
                check_name="biz_closed_loan_maturity",
                passed=passed,
                detail=detail,
                severity="WARNING",
            )
        )
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] Closed loan maturity: {detail}")
    except Exception as e:
        report.add(
            CheckResult(
                category="Business Rule",
                table="loan_accounts",
                check_name="biz_closed_loan_maturity",
                passed=False,
                detail=f"Check failed: {e}",
                severity="WARNING",
            )
        )

    # --- Rule: Payment component amounts should sum to total ---
    try:
        payments_df = spark.table("loan_warehouse.payments")

        component_sum = (
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0))
        )

        mismatched = payments_df.filter(
            F.abs(F.col("total_amount") - component_sum) > 0.01
        ).count()
        passed = mismatched == 0
        detail = (
            f"Payments where components != total: {mismatched}"
            if not passed
            else "All payment components sum to total_amount"
        )
        report.add(
            CheckResult(
                category="Business Rule",
                table="payments",
                check_name="biz_payment_component_sum",
                passed=passed,
                detail=detail,
                severity="WARNING",
            )
        )
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] Payment sum: {detail}")
    except Exception as e:
        report.add(
            CheckResult(
                category="Business Rule",
                table="payments",
                check_name="biz_payment_component_sum",
                passed=False,
                detail=f"Check failed: {e}",
                severity="WARNING",
            )
        )

    # --- Rule: Credit score between 300 and 850 when present ---
    try:
        borrowers_df = spark.table("loan_warehouse.borrowers")

        bad_scores = borrowers_df.filter(
            F.col("credit_score").isNotNull()
            & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()
        passed = bad_scores == 0
        detail = (
            f"Borrowers with credit score outside 300-850: {bad_scores}"
            if not passed
            else "All credit scores in valid range (300-850)"
        )
        report.add(
            CheckResult(
                category="Business Rule",
                table="borrowers",
                check_name="biz_credit_score_range",
                passed=passed,
                detail=detail,
                severity="WARNING",
            )
        )
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] Credit score range: {detail}")
    except Exception as e:
        report.add(
            CheckResult(
                category="Business Rule",
                table="borrowers",
                check_name="biz_credit_score_range",
                passed=False,
                detail=f"Check failed: {e}",
                severity="WARNING",
            )
        )


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------
def run_all_checks(spark: SparkSession, source_counts: dict) -> QualityReport:
    """
    Execute the full data quality suite and return the report.

    Args:
        spark: Active SparkSession.
        source_counts: Dict of expected row counts per table, e.g.:
            {"borrowers": 5, "loan_products": 5, "loan_accounts": 5, "payments": 10}
    """
    report = QualityReport()

    print("=" * 70)
    print("DATA QUALITY VALIDATION")
    print("=" * 70)

    print("\n--- 1. Row Count Reconciliation ---")
    check_row_counts(spark, source_counts, report)

    print("\n--- 2. Null Checks on Required Fields ---")
    check_nulls(spark, report)

    print("\n--- 3. Referential Integrity ---")
    check_referential_integrity(spark, report)

    print("\n--- 4. Business Rule Validation ---")
    check_business_rules(spark, report)

    print("\n" + "=" * 70)
    print(f"QUALITY REPORT: {report.summary()}")
    overall = "PASSED" if report.all_passed else "FAILED"
    print(f"OVERALL STATUS: {overall}")
    print("=" * 70)

    return report
