"""
Data Quality Validators for the Loan Warehouse.

Each validator returns a ValidationResult with pass/fail status,
details, and counts for reporting.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    check_name: str
    category: str
    table: str
    status: str  # PASS, FAIL, WARN
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    failing_count: int = 0
    total_count: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


# =============================================================================
# Row Count Reconciliation
# =============================================================================


def check_row_count_reconciliation(
    spark: SparkSession,
    source_path: str,
    target_table: str,
    source_format: str = "csv",
    tolerance_pct: float = 0.0,
) -> ValidationResult:
    """
    Verify that the target table has the expected number of rows
    relative to the source file.

    Args:
        spark: Active SparkSession
        source_path: Path to source data files
        target_table: Target Delta table name
        source_format: Format of source files (csv or parquet)
        tolerance_pct: Acceptable percentage difference (0.0 = exact match)

    Returns:
        ValidationResult with pass/fail status
    """
    if source_format == "parquet":
        source_df = spark.read.parquet(source_path)
    else:
        source_df = spark.read.option("header", "true").csv(source_path)

    source_count = source_df.count()
    target_count = spark.read.table(target_table).count()

    if source_count == 0:
        return ValidationResult(
            check_name="row_count_reconciliation",
            category="completeness",
            table=target_table,
            status="WARN",
            message="Source has 0 rows; cannot validate row count",
            expected="0",
            actual=str(target_count),
        )

    diff_pct = abs(source_count - target_count) / source_count * 100.0

    if diff_pct <= tolerance_pct:
        return ValidationResult(
            check_name="row_count_reconciliation",
            category="completeness",
            table=target_table,
            status="PASS",
            message=f"Row counts match within tolerance ({tolerance_pct}%)",
            expected=str(source_count),
            actual=str(target_count),
            total_count=source_count,
        )

    return ValidationResult(
        check_name="row_count_reconciliation",
        category="completeness",
        table=target_table,
        status="FAIL",
        message=f"Row count mismatch: source={source_count}, target={target_count} (diff={diff_pct:.2f}%)",
        expected=str(source_count),
        actual=str(target_count),
        failing_count=abs(source_count - target_count),
        total_count=source_count,
    )


# =============================================================================
# Null Checks on Required Fields
# =============================================================================


def check_required_not_null(
    spark: SparkSession,
    table: str,
    columns: list,
) -> list:
    """
    Check that required columns contain no NULL values.

    Args:
        spark: Active SparkSession
        table: Delta table name to check
        columns: List of column names that must not be null

    Returns:
        List of ValidationResult (one per column)
    """
    df = spark.read.table(table)
    total_count = df.count()
    results = []

    for col_name in columns:
        null_count = df.filter(F.col(col_name).isNull()).count()

        if null_count == 0:
            results.append(ValidationResult(
                check_name=f"not_null_{col_name}",
                category="completeness",
                table=table,
                status="PASS",
                message=f"Column '{col_name}' has no NULL values",
                expected="0 nulls",
                actual="0 nulls",
                total_count=total_count,
            ))
        else:
            results.append(ValidationResult(
                check_name=f"not_null_{col_name}",
                category="completeness",
                table=table,
                status="FAIL",
                message=f"Column '{col_name}' has {null_count} NULL values ({null_count / max(total_count, 1) * 100:.2f}%)",
                expected="0 nulls",
                actual=f"{null_count} nulls",
                failing_count=null_count,
                total_count=total_count,
            ))

    return results


# =============================================================================
# Referential Integrity
# =============================================================================


def check_referential_integrity(
    spark: SparkSession,
    child_table: str,
    child_column: str,
    parent_table: str,
    parent_column: str,
) -> ValidationResult:
    """
    Verify that all non-null FK values in child table exist in parent table.

    Args:
        spark: Active SparkSession
        child_table: Table containing the foreign key
        child_column: FK column name
        parent_table: Referenced parent table
        parent_column: Referenced column in parent table

    Returns:
        ValidationResult with orphan count details
    """
    child_df = spark.read.table(child_table)
    parent_df = spark.read.table(parent_table)

    # Get distinct non-null FK values from child
    child_keys = child_df.filter(
        F.col(child_column).isNotNull()
    ).select(child_column).distinct()

    # Get parent keys
    parent_keys = parent_df.select(
        F.col(parent_column).alias(child_column)
    ).distinct()

    # Find orphans
    orphans = child_keys.subtract(parent_keys)
    orphan_count = orphans.count()
    total_fk_count = child_keys.count()

    if orphan_count == 0:
        return ValidationResult(
            check_name=f"ref_integrity_{child_table}_{child_column}",
            category="referential_integrity",
            table=child_table,
            status="PASS",
            message=f"All '{child_column}' values in {child_table} exist in {parent_table}.{parent_column}",
            expected="0 orphans",
            actual="0 orphans",
            total_count=total_fk_count,
        )

    return ValidationResult(
        check_name=f"ref_integrity_{child_table}_{child_column}",
        category="referential_integrity",
        table=child_table,
        status="FAIL",
        message=f"{orphan_count} orphan '{child_column}' values in {child_table} not found in {parent_table}.{parent_column}",
        expected="0 orphans",
        actual=f"{orphan_count} orphans",
        failing_count=orphan_count,
        total_count=total_fk_count,
    )


# =============================================================================
# Business Rule Validations
# =============================================================================


def check_active_loan_positive_balance(
    spark: SparkSession,
    table: str = "loan_warehouse.loan_accounts",
) -> ValidationResult:
    """
    Business Rule: Active loans must have a positive current balance.

    Loans with status='ACTIVE' should have current_balance > 0.
    """
    df = spark.read.table(table)
    active_loans = df.filter(F.col("status") == "ACTIVE")
    total_active = active_loans.count()

    violations = active_loans.filter(
        (F.col("current_balance").isNull()) | (F.col("current_balance") <= 0)
    )
    violation_count = violations.count()

    if violation_count == 0:
        return ValidationResult(
            check_name="active_loan_positive_balance",
            category="business_rule",
            table=table,
            status="PASS",
            message="All active loans have positive current_balance",
            expected="0 violations",
            actual="0 violations",
            total_count=total_active,
        )

    return ValidationResult(
        check_name="active_loan_positive_balance",
        category="business_rule",
        table=table,
        status="FAIL",
        message=f"{violation_count} active loans have zero/negative/null balance",
        expected="0 violations",
        actual=f"{violation_count} violations",
        failing_count=violation_count,
        total_count=total_active,
    )


def check_closed_loan_has_closed_date(
    spark: SparkSession,
    table: str = "loan_warehouse.loan_accounts",
) -> ValidationResult:
    """
    Business Rule: Closed loans should have an updated_at timestamp
    (as proxy for close date in the current schema).

    Note: The legacy schema doesn't have an explicit close_date field.
    We validate that closed loans at minimum have updated_at populated.
    """
    df = spark.read.table(table)
    closed_loans = df.filter(F.col("status") == "CLOSED")
    total_closed = closed_loans.count()

    if total_closed == 0:
        return ValidationResult(
            check_name="closed_loan_has_date",
            category="business_rule",
            table=table,
            status="PASS",
            message="No closed loans to validate (0 records with CLOSED status)",
            expected="N/A",
            actual="N/A",
            total_count=0,
        )

    violations = closed_loans.filter(F.col("updated_at").isNull())
    violation_count = violations.count()

    if violation_count == 0:
        return ValidationResult(
            check_name="closed_loan_has_date",
            category="business_rule",
            table=table,
            status="PASS",
            message="All closed loans have updated_at timestamp",
            expected="0 violations",
            actual="0 violations",
            total_count=total_closed,
        )

    return ValidationResult(
        check_name="closed_loan_has_date",
        category="business_rule",
        table=table,
        status="FAIL",
        message=f"{violation_count} closed loans missing updated_at date",
        expected="0 violations",
        actual=f"{violation_count} violations",
        failing_count=violation_count,
        total_count=total_closed,
    )


def check_payment_amounts_consistent(
    spark: SparkSession,
    table: str = "loan_warehouse.payments",
) -> ValidationResult:
    """
    Business Rule: Payment component amounts should sum to approximately
    the total amount (principal + interest + escrow + late_fee ≈ total_amount).

    Allows 1 cent tolerance for rounding.
    """
    df = spark.read.table(table)
    total_payments = df.count()

    payments_with_components = df.filter(
        F.col("principal_amount").isNotNull()
        & F.col("interest_amount").isNotNull()
        & F.col("total_amount").isNotNull()
    )

    violations = payments_with_components.withColumn(
        "_computed_total",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0)),
    ).filter(
        F.abs(F.col("_computed_total") - F.col("total_amount")) > 0.01
    )

    violation_count = violations.count()

    if violation_count == 0:
        return ValidationResult(
            check_name="payment_amounts_consistent",
            category="business_rule",
            table=table,
            status="PASS",
            message="All payment component amounts sum to total_amount (within $0.01)",
            expected="0 violations",
            actual="0 violations",
            total_count=total_payments,
        )

    return ValidationResult(
        check_name="payment_amounts_consistent",
        category="business_rule",
        table=table,
        status="FAIL",
        message=f"{violation_count} payments where components don't sum to total",
        expected="0 violations",
        actual=f"{violation_count} violations",
        failing_count=violation_count,
        total_count=total_payments,
    )


def check_loan_term_valid(
    spark: SparkSession,
    table: str = "loan_warehouse.loan_accounts",
) -> ValidationResult:
    """
    Business Rule: Loan term should be a standard mortgage term
    (typically 60, 120, 180, 240, 300, or 360 months).
    """
    valid_terms = [60, 120, 180, 240, 300, 360]
    df = spark.read.table(table)
    total_loans = df.count()

    violations = df.filter(
        ~F.col("term_months").isin(valid_terms) & F.col("term_months").isNotNull()
    )
    violation_count = violations.count()

    if violation_count == 0:
        return ValidationResult(
            check_name="loan_term_valid",
            category="business_rule",
            table=table,
            status="PASS",
            message="All loan terms are standard mortgage terms",
            expected="0 non-standard terms",
            actual="0 non-standard terms",
            total_count=total_loans,
        )

    return ValidationResult(
        check_name="loan_term_valid",
        category="business_rule",
        table=table,
        status="WARN",
        message=f"{violation_count} loans have non-standard term lengths",
        expected="0 non-standard terms",
        actual=f"{violation_count} non-standard",
        failing_count=violation_count,
        total_count=total_loans,
    )


def check_credit_score_range(
    spark: SparkSession,
    table: str = "loan_warehouse.borrowers",
) -> ValidationResult:
    """
    Business Rule: Credit scores must be between 300 and 850.
    """
    df = spark.read.table(table)
    scored = df.filter(F.col("credit_score").isNotNull())
    total_scored = scored.count()

    violations = scored.filter(
        (F.col("credit_score") < 300) | (F.col("credit_score") > 850)
    )
    violation_count = violations.count()

    if violation_count == 0:
        return ValidationResult(
            check_name="credit_score_range",
            category="business_rule",
            table=table,
            status="PASS",
            message="All credit scores within valid range (300-850)",
            expected="0 out-of-range",
            actual="0 out-of-range",
            total_count=total_scored,
        )

    return ValidationResult(
        check_name="credit_score_range",
        category="business_rule",
        table=table,
        status="FAIL",
        message=f"{violation_count} borrowers have credit scores outside 300-850 range",
        expected="0 out-of-range",
        actual=f"{violation_count} out-of-range",
        failing_count=violation_count,
        total_count=total_scored,
    )
