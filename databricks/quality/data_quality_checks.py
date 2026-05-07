"""
Data Quality Validation Framework for CDW -> Delta Lake Migration.

Runs post-ingestion checks against the Delta Lake target tables and produces
a structured results list that can be rendered into DATA_QUALITY_REPORT.md.

Check categories:
    1. Row count reconciliation (source vs target)
    2. Null checks on required fields
    3. Referential integrity between loan_accounts <-> borrowers,
       loan_accounts <-> loan_products, payments <-> loan_accounts
    4. Business rule validation
"""

from dataclasses import dataclass, field
from typing import List, Tuple
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dq_checks")


@dataclass
class CheckResult:
    """Result of a single data quality check."""
    category: str
    table: str
    check_name: str
    passed: bool
    detail: str
    expected: str = ""
    actual: str = ""


@dataclass
class QualityReport:
    """Aggregated data quality report."""
    results: List[CheckResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def add(self, result: CheckResult):
        status = "PASS" if result.passed else "FAIL"
        logger.info("[%s] %s / %s: %s", status, result.table, result.check_name, result.detail)
        self.results.append(result)


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------
def check_row_counts(spark: SparkSession, report: QualityReport,
                     source_counts: dict):
    """Compare source row counts against target Delta Lake tables.

    Args:
        source_counts: Dict mapping target table name to expected source row count.
                       Example: {"loan_warehouse.borrowers": 5, ...}
    """
    for table_name, expected_count in source_counts.items():
        try:
            target_df = spark.table(table_name)
            actual_count = target_df.count()
            passed = actual_count == expected_count
            report.add(CheckResult(
                category="Row Count",
                table=table_name,
                check_name="row_count_reconciliation",
                passed=passed,
                detail=f"Expected {expected_count} rows, found {actual_count}",
                expected=str(expected_count),
                actual=str(actual_count),
            ))
        except Exception as e:
            report.add(CheckResult(
                category="Row Count",
                table=table_name,
                check_name="row_count_reconciliation",
                passed=False,
                detail=f"Error reading table: {e}",
                expected=str(expected_count),
                actual="ERROR",
            ))


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_warehouse.loan_products": ["code", "name", "type", "term_months", "rate_type"],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_external_id", "product_code",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date", "status",
    ],
    "loan_warehouse.payments": [
        "loan_account_number", "payment_date", "total_amount", "type", "status",
    ],
}


def check_required_nulls(spark: SparkSession, report: QualityReport):
    """Check that required fields have no NULL values in target tables."""
    for table_name, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table_name)
            for col_name in columns:
                null_count = df.filter(F.col(col_name).isNull()).count()
                passed = null_count == 0
                report.add(CheckResult(
                    category="Null Check",
                    table=table_name,
                    check_name=f"not_null_{col_name}",
                    passed=passed,
                    detail=f"{null_count} NULL values in required column '{col_name}'",
                    expected="0",
                    actual=str(null_count),
                ))
        except Exception as e:
            report.add(CheckResult(
                category="Null Check",
                table=table_name,
                check_name="null_check_error",
                passed=False,
                detail=f"Error checking nulls: {e}",
            ))


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------
def check_referential_integrity(spark: SparkSession, report: QualityReport):
    """Validate foreign key relationships between target tables."""

    # loan_accounts.borrower_external_id -> borrowers.external_id
    _check_fk(
        spark, report,
        child_table="loan_warehouse.loan_accounts",
        child_col="borrower_external_id",
        parent_table="loan_warehouse.borrowers",
        parent_col="external_id",
    )

    # loan_accounts.product_code -> loan_products.code
    _check_fk(
        spark, report,
        child_table="loan_warehouse.loan_accounts",
        child_col="product_code",
        parent_table="loan_warehouse.loan_products",
        parent_col="code",
    )

    # payments.loan_account_number -> loan_accounts.account_number
    _check_fk(
        spark, report,
        child_table="loan_warehouse.payments",
        child_col="loan_account_number",
        parent_table="loan_warehouse.loan_accounts",
        parent_col="account_number",
    )


def _check_fk(spark: SparkSession, report: QualityReport,
               child_table: str, child_col: str,
               parent_table: str, parent_col: str):
    """Check that all child FK values exist in the parent table."""
    try:
        child_df = spark.table(child_table).select(child_col).distinct()
        parent_df = spark.table(parent_table).select(parent_col).distinct()

        orphans = child_df.join(parent_df, child_df[child_col] == parent_df[parent_col], "left_anti")
        orphan_count = orphans.count()
        passed = orphan_count == 0

        detail = f"All {child_col} values found in {parent_table}.{parent_col}"
        if not passed:
            orphan_vals = [row[0] for row in orphans.take(10)]
            detail = f"{orphan_count} orphan(s) in {child_col}: {orphan_vals}"

        report.add(CheckResult(
            category="Referential Integrity",
            table=child_table,
            check_name=f"fk_{child_col}_to_{parent_table}",
            passed=passed,
            detail=detail,
            expected="0 orphans",
            actual=str(orphan_count),
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Referential Integrity",
            table=child_table,
            check_name=f"fk_{child_col}_to_{parent_table}",
            passed=False,
            detail=f"Error checking FK: {e}",
        ))


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------
def check_business_rules(spark: SparkSession, report: QualityReport):
    """Validate domain-specific business rules."""

    try:
        loans_df = spark.table("loan_warehouse.loan_accounts")

        # Rule 1: Active loans must have a positive current balance
        active_zero_balance = loans_df.filter(
            (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="active_loan_positive_balance",
            passed=active_zero_balance == 0,
            detail=f"{active_zero_balance} active loans with balance <= 0",
            expected="0",
            actual=str(active_zero_balance),
        ))

        # Rule 2: Loan origination date must be before maturity date
        bad_dates = loans_df.filter(
            F.col("origination_date") >= F.col("maturity_date")
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="origination_before_maturity",
            passed=bad_dates == 0,
            detail=f"{bad_dates} loans where origination_date >= maturity_date",
            expected="0",
            actual=str(bad_dates),
        ))

        # Rule 3: Interest rate must be between 0 and 100
        bad_rates = loans_df.filter(
            (F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="interest_rate_range",
            passed=bad_rates == 0,
            detail=f"{bad_rates} loans with interest rate outside 0-100%",
            expected="0",
            actual=str(bad_rates),
        ))

        # Rule 4: LTV percent should be between 0 and 200 (generous upper bound)
        bad_ltv = loans_df.filter(
            F.col("ltv_percent").isNotNull() &
            ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="ltv_percent_range",
            passed=bad_ltv == 0,
            detail=f"{bad_ltv} loans with LTV outside 0-200%",
            expected="0",
            actual=str(bad_ltv),
        ))

        # Rule 5: Delinquency days should be >= 0
        bad_dlq = loans_df.filter(
            F.col("delinquency_days").isNotNull() & (F.col("delinquency_days") < 0)
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="delinquency_days_nonneg",
            passed=bad_dlq == 0,
            detail=f"{bad_dlq} loans with negative delinquency days",
            expected="0",
            actual=str(bad_dlq),
        ))

    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="business_rules_error",
            passed=False,
            detail=f"Error running business rules: {e}",
        ))

    # Payment business rules
    try:
        payments_df = spark.table("loan_warehouse.payments")

        # Rule 6: Payment total_amount must be positive
        neg_payments = payments_df.filter(F.col("total_amount") <= 0).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.payments",
            check_name="payment_amount_positive",
            passed=neg_payments == 0,
            detail=f"{neg_payments} payments with total_amount <= 0",
            expected="0",
            actual=str(neg_payments),
        ))

        # Rule 7: Payment received_date should be on or before processed_date
        bad_recv = payments_df.filter(
            F.col("received_date").isNotNull() &
            F.col("processed_date").isNotNull() &
            (F.col("received_date") > F.col("processed_date"))
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.payments",
            check_name="received_before_processed",
            passed=bad_recv == 0,
            detail=f"{bad_recv} payments where received_date > processed_date",
            expected="0",
            actual=str(bad_recv),
        ))

        # Rule 8: Component amounts should approximately sum to total
        component_check = payments_df.filter(
            F.col("principal_amount").isNotNull() &
            F.col("interest_amount").isNotNull()
        ).withColumn(
            "component_sum",
            F.coalesce(F.col("principal_amount"), F.lit(0)) +
            F.coalesce(F.col("interest_amount"), F.lit(0)) +
            F.coalesce(F.col("escrow_amount"), F.lit(0)) +
            F.coalesce(F.col("late_fee"), F.lit(0))
        ).filter(
            F.abs(F.col("component_sum") - F.col("total_amount")) > 0.02
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.payments",
            check_name="payment_components_sum",
            passed=component_check == 0,
            detail=f"{component_check} payments where components don't sum to total (tolerance $0.02)",
            expected="0",
            actual=str(component_check),
        ))

    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.payments",
            check_name="payment_business_rules_error",
            passed=False,
            detail=f"Error running payment business rules: {e}",
        ))

    # Borrower business rules
    try:
        borrowers_df = spark.table("loan_warehouse.borrowers")

        # Rule 9: Credit score should be in valid range (300-850)
        bad_credit = borrowers_df.filter(
            F.col("credit_score").isNotNull() &
            ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.borrowers",
            check_name="credit_score_range",
            passed=bad_credit == 0,
            detail=f"{bad_credit} borrowers with credit score outside 300-850",
            expected="0",
            actual=str(bad_credit),
        ))

        # Rule 10: Annual income should be non-negative
        neg_income = borrowers_df.filter(
            F.col("annual_income").isNotNull() & (F.col("annual_income") < 0)
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.borrowers",
            check_name="annual_income_nonneg",
            passed=neg_income == 0,
            detail=f"{neg_income} borrowers with negative annual income",
            expected="0",
            actual=str(neg_income),
        ))

    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.borrowers",
            check_name="borrower_business_rules_error",
            passed=False,
            detail=f"Error running borrower business rules: {e}",
        ))


# ---------------------------------------------------------------------------
# 5. Status Value Validation
# ---------------------------------------------------------------------------
def check_status_values(spark: SparkSession, report: QualityReport):
    """Verify that all status code expansions produced valid values."""
    VALID_STATUSES = {
        "loan_warehouse.borrowers": {"status": {"ACTIVE", "INACTIVE"}},
        "loan_warehouse.loan_accounts": {"status": {"ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE"}},
        "loan_warehouse.payments": {
            "type": {"REGULAR", "EXTRA", "PARTIAL", "PREPAYMENT"},
            "status": {"POSTED", "REVERSED", "NSF", "PENDING"},
        },
    }

    for table_name, col_map in VALID_STATUSES.items():
        try:
            df = spark.table(table_name)
            for col_name, valid_set in col_map.items():
                distinct_vals = {row[0] for row in df.select(col_name).distinct().collect() if row[0]}
                invalid = distinct_vals - valid_set
                passed = len(invalid) == 0
                report.add(CheckResult(
                    category="Status Validation",
                    table=table_name,
                    check_name=f"valid_{col_name}_values",
                    passed=passed,
                    detail=f"Invalid values: {invalid}" if invalid else f"All {col_name} values valid",
                    expected=str(valid_set),
                    actual=str(distinct_vals),
                ))
        except Exception as e:
            report.add(CheckResult(
                category="Status Validation",
                table=table_name,
                check_name="status_validation_error",
                passed=False,
                detail=f"Error: {e}",
            ))


# ---------------------------------------------------------------------------
# Run All Checks
# ---------------------------------------------------------------------------
def run_all_checks(spark: SparkSession, source_counts: dict = None) -> QualityReport:
    """Execute the full data quality suite.

    Args:
        spark: Active SparkSession.
        source_counts: Optional dict of {table_name: expected_row_count}.
                       If None, row count checks are skipped.

    Returns:
        QualityReport with all check results.
    """
    report = QualityReport()

    logger.info("=" * 70)
    logger.info("DATA QUALITY CHECKS — START")
    logger.info("=" * 70)

    if source_counts:
        logger.info("--- Row Count Reconciliation ---")
        check_row_counts(spark, report, source_counts)

    logger.info("--- Null Checks ---")
    check_required_nulls(spark, report)

    logger.info("--- Referential Integrity ---")
    check_referential_integrity(spark, report)

    logger.info("--- Business Rules ---")
    check_business_rules(spark, report)

    logger.info("--- Status Value Validation ---")
    check_status_values(spark, report)

    logger.info("=" * 70)
    logger.info("DATA QUALITY CHECKS — COMPLETE: %d passed, %d failed, %d total",
                report.passed, report.failed, report.total)
    logger.info("=" * 70)

    return report
