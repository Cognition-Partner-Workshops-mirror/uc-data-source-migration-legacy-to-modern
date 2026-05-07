"""
Data quality validation checks for the loan data warehouse.

Check categories:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts -> borrowers, loan_products
     and payments -> loan_accounts
  4. Business rule validation (domain-specific invariants)
"""

import logging
from dataclasses import dataclass, field

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

logger = logging.getLogger("loan_migration.quality")


@dataclass
class CheckResult:
    """Result of a single data quality check."""
    category: str
    check_name: str
    table: str
    passed: bool
    details: str
    expected: str = ""
    actual: str = ""


@dataclass
class QualityReport:
    """Aggregated quality report across all checks."""
    results: list[CheckResult] = field(default_factory=list)

    @property
    def total_checks(self) -> int:
        return len(self.results)

    @property
    def passed_checks(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_checks(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info("[%s] %s / %s: %s", status, result.category, result.check_name, result.details)


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------


def check_row_counts(
    report: QualityReport,
    spark: SparkSession,
    source_path: str,
    target_path: str,
    table_name: str,
    fmt: str = "csv",
) -> None:
    """Verify that source and target have the same number of rows."""
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        source_df = reader.csv(source_path)
    else:
        source_df = reader.parquet(source_path)

    target_df = spark.read.format("delta").load(target_path)

    source_count = source_df.count()
    target_count = target_df.count()

    report.add(CheckResult(
        category="Row Count",
        check_name=f"{table_name}_row_count_match",
        table=table_name,
        passed=source_count == target_count,
        details=f"Source: {source_count}, Target: {target_count}",
        expected=str(source_count),
        actual=str(target_count),
    ))


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------


def check_required_not_null(
    report: QualityReport,
    spark: SparkSession,
    target_path: str,
    table_name: str,
    required_columns: list[str],
) -> None:
    """Verify that required columns contain no null values."""
    df = spark.read.format("delta").load(target_path)
    total_rows = df.count()

    for col_name in required_columns:
        if col_name not in df.columns:
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table_name}.{col_name}_not_null",
                table=table_name,
                passed=False,
                details=f"Column '{col_name}' does not exist in target table",
                expected="Column exists",
                actual="Column missing",
            ))
            continue

        null_count = df.filter(F.col(col_name).isNull()).count()
        report.add(CheckResult(
            category="Null Check",
            check_name=f"{table_name}.{col_name}_not_null",
            table=table_name,
            passed=null_count == 0,
            details=f"{null_count}/{total_rows} rows have null '{col_name}'",
            expected="0 nulls",
            actual=f"{null_count} nulls",
        ))


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------


def check_referential_integrity(
    report: QualityReport,
    spark: SparkSession,
    child_path: str,
    child_table: str,
    child_fk_col: str,
    parent_path: str,
    parent_table: str,
    parent_pk_col: str,
) -> None:
    """Verify that every FK in child table references a valid PK in parent table."""
    child_df = spark.read.format("delta").load(child_path)
    parent_df = spark.read.format("delta").load(parent_path)

    parent_ids = parent_df.select(F.col(parent_pk_col).alias("_pk"))

    orphans = child_df.join(
        parent_ids,
        child_df[child_fk_col] == parent_ids["_pk"],
        "left_anti",
    )
    orphan_count = orphans.count()
    total_count = child_df.count()

    report.add(CheckResult(
        category="Referential Integrity",
        check_name=f"{child_table}.{child_fk_col}_references_{parent_table}.{parent_pk_col}",
        table=child_table,
        passed=orphan_count == 0,
        details=f"{orphan_count}/{total_count} orphaned records in {child_table}.{child_fk_col}",
        expected="0 orphans",
        actual=f"{orphan_count} orphans",
    ))


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------


def check_active_loan_positive_balance(
    report: QualityReport,
    spark: SparkSession,
    loan_accounts_path: str,
) -> None:
    """Active loans must have a current_balance > 0."""
    df = spark.read.format("delta").load(loan_accounts_path)
    active_loans = df.filter(F.col("status") == "ACTIVE")
    violations = active_loans.filter(
        (F.col("current_balance").isNull()) | (F.col("current_balance") <= 0)
    )
    violation_count = violations.count()
    total_active = active_loans.count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="active_loan_positive_balance",
        table="loan_accounts",
        passed=violation_count == 0,
        details=f"{violation_count}/{total_active} active loans with balance <= 0",
        expected="0 violations",
        actual=f"{violation_count} violations",
    ))


def check_closed_loan_has_closed_date(
    report: QualityReport,
    spark: SparkSession,
    loan_accounts_path: str,
) -> None:
    """
    Closed loans should have a maturity_date that is in the past
    (as a proxy for having a closed/completion date).
    """
    df = spark.read.format("delta").load(loan_accounts_path)
    closed_loans = df.filter(F.col("status") == "CLOSED")
    violations = closed_loans.filter(F.col("maturity_date").isNull())
    violation_count = violations.count()
    total_closed = closed_loans.count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="closed_loan_has_maturity_date",
        table="loan_accounts",
        passed=violation_count == 0,
        details=f"{violation_count}/{total_closed} closed loans missing maturity_date",
        expected="0 violations",
        actual=f"{violation_count} violations",
    ))


def check_payment_amount_positive(
    report: QualityReport,
    spark: SparkSession,
    payments_path: str,
) -> None:
    """Posted payments must have total_amount > 0."""
    df = spark.read.format("delta").load(payments_path)
    posted = df.filter(F.col("status") == "POSTED")
    violations = posted.filter(
        (F.col("total_amount").isNull()) | (F.col("total_amount") <= 0)
    )
    violation_count = violations.count()
    total_posted = posted.count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="posted_payment_positive_amount",
        table="payments",
        passed=violation_count == 0,
        details=f"{violation_count}/{total_posted} posted payments with amount <= 0",
        expected="0 violations",
        actual=f"{violation_count} violations",
    ))


def check_payment_components_sum(
    report: QualityReport,
    spark: SparkSession,
    payments_path: str,
    tolerance: float = 0.01,
) -> None:
    """
    For posted payments, principal + interest + escrow + late_fee
    should approximately equal total_amount.
    """
    df = spark.read.format("delta").load(payments_path)
    posted = df.filter(F.col("status") == "POSTED")

    with_sum = posted.withColumn(
        "_component_sum",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0)),
    ).withColumn(
        "_diff", F.abs(F.col("total_amount") - F.col("_component_sum")),
    )

    violations = with_sum.filter(F.col("_diff") > tolerance)
    violation_count = violations.count()
    total_posted = posted.count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="payment_components_sum_matches_total",
        table="payments",
        passed=violation_count == 0,
        details=(
            f"{violation_count}/{total_posted} posted payments where "
            f"principal+interest+escrow+late_fee differs from total by > ${tolerance}"
        ),
        expected="0 violations",
        actual=f"{violation_count} violations",
    ))


def check_origination_before_maturity(
    report: QualityReport,
    spark: SparkSession,
    loan_accounts_path: str,
) -> None:
    """Loan origination_date must be before maturity_date."""
    df = spark.read.format("delta").load(loan_accounts_path)
    violations = df.filter(
        F.col("origination_date").isNotNull()
        & F.col("maturity_date").isNotNull()
        & (F.col("origination_date") >= F.col("maturity_date"))
    )
    violation_count = violations.count()
    total = df.count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="origination_before_maturity",
        table="loan_accounts",
        passed=violation_count == 0,
        details=f"{violation_count}/{total} loans where origination_date >= maturity_date",
        expected="0 violations",
        actual=f"{violation_count} violations",
    ))


def check_interest_rate_range(
    report: QualityReport,
    spark: SparkSession,
    loan_accounts_path: str,
) -> None:
    """Interest rate should be between 0 and 30 (reasonable range for mortgages)."""
    df = spark.read.format("delta").load(loan_accounts_path)
    violations = df.filter(
        F.col("interest_rate").isNotNull()
        & ((F.col("interest_rate") < 0) | (F.col("interest_rate") > 30))
    )
    violation_count = violations.count()
    total = df.count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="interest_rate_in_range_0_to_30",
        table="loan_accounts",
        passed=violation_count == 0,
        details=f"{violation_count}/{total} loans with interest rate outside 0-30%",
        expected="0 violations",
        actual=f"{violation_count} violations",
    ))
