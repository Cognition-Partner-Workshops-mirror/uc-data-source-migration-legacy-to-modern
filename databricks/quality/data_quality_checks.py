"""Post-ingestion data quality validation framework.

Runs a suite of checks against the modern Delta Lake tables and produces a
structured results list that can be rendered into DATA_QUALITY_REPORT.md.

Check categories:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between tables
  4. Business rule validation
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

logger = logging.getLogger("quality.checks")
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str
    check_name: str
    table: str
    status: str  # PASS, FAIL, WARN
    detail: str
    row_count: Optional[int] = None


@dataclass
class QualityReport:
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    results: list = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)
        level = logging.WARNING if result.status == "FAIL" else logging.INFO
        logger.log(level, "[%s] %s — %s: %s", result.status, result.table, result.check_name, result.detail)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warnings(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")


# ---------------------------------------------------------------------------
# 1. Row count reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(
    spark: SparkSession,
    report: QualityReport,
    source_counts: dict,
) -> None:
    """Compare source row counts against target table row counts."""
    table_map = {
        "cdw_borr_mstr": "loan_warehouse.borrowers",
        "cdw_ln_prod": "loan_warehouse.loan_products",
        "cdw_ln_acct": "loan_warehouse.loan_accounts",
        "cdw_pmt_hist": "loan_warehouse.payments",
    }

    for source_name, target_table in table_map.items():
        source_count = source_counts.get(source_name, 0)
        try:
            target_count = spark.table(target_table).count()
        except Exception as exc:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"count_{source_name}",
                table=target_table,
                status="FAIL",
                detail=f"Cannot read target table: {exc}",
            ))
            continue

        if source_count == target_count:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"count_{source_name}",
                table=target_table,
                status="PASS",
                detail=f"Source={source_count}, Target={target_count}",
                row_count=target_count,
            ))
        else:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"count_{source_name}",
                table=target_table,
                status="FAIL",
                detail=f"MISMATCH — Source={source_count}, Target={target_count}",
                row_count=target_count,
            ))


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": [
        "external_id", "first_name", "last_name", "status",
    ],
    "loan_warehouse.loan_products": [
        "code", "name", "type", "term_months", "rate_type", "is_active",
    ],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "status",
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount", "type", "status",
    ],
}


def check_nulls(spark: SparkSession, report: QualityReport) -> None:
    """Check that required fields contain no NULLs."""
    for table, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table)
        except Exception as exc:
            report.add(CheckResult(
                category="Null Check",
                check_name=f"nulls_{table}",
                table=table,
                status="FAIL",
                detail=f"Cannot read table: {exc}",
            ))
            continue

        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            if null_count == 0:
                report.add(CheckResult(
                    category="Null Check",
                    check_name=f"not_null_{col_name}",
                    table=table,
                    status="PASS",
                    detail=f"No NULLs in {col_name}",
                ))
            else:
                report.add(CheckResult(
                    category="Null Check",
                    check_name=f"not_null_{col_name}",
                    table=table,
                    status="FAIL",
                    detail=f"{null_count} NULL(s) found in {col_name}",
                    row_count=null_count,
                ))


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Verify FK relationships between modern tables."""
    # loan_accounts.borrower_id → borrowers.id
    _check_fk(
        spark, report,
        child_table="loan_warehouse.loan_accounts",
        child_col="borrower_id",
        parent_table="loan_warehouse.borrowers",
        parent_col="id",
    )

    # loan_accounts.product_id → loan_products.id
    _check_fk(
        spark, report,
        child_table="loan_warehouse.loan_accounts",
        child_col="product_id",
        parent_table="loan_warehouse.loan_products",
        parent_col="id",
    )

    # payments.loan_account_id → loan_accounts.id
    _check_fk(
        spark, report,
        child_table="loan_warehouse.payments",
        child_col="loan_account_id",
        parent_table="loan_warehouse.loan_accounts",
        parent_col="id",
    )


def _check_fk(
    spark: SparkSession,
    report: QualityReport,
    child_table: str,
    child_col: str,
    parent_table: str,
    parent_col: str,
) -> None:
    check_name = f"fk_{child_table.split('.')[-1]}_{child_col}"
    try:
        child_df = spark.table(child_table)
        parent_df = spark.table(parent_table)
    except Exception as exc:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name=check_name,
            table=child_table,
            status="FAIL",
            detail=f"Cannot read tables: {exc}",
        ))
        return

    orphans = (
        child_df
        .join(parent_df, child_df[child_col] == parent_df[parent_col], "left_anti")
        .count()
    )

    if orphans == 0:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name=check_name,
            table=child_table,
            status="PASS",
            detail=f"All {child_col} values exist in {parent_table}.{parent_col}",
        ))
    else:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name=check_name,
            table=child_table,
            status="FAIL",
            detail=f"{orphans} orphan(s): {child_col} not found in {parent_table}.{parent_col}",
            row_count=orphans,
        ))


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules on the modern tables."""
    _check_active_loan_positive_balance(spark, report)
    _check_closed_loan_has_closed_date(spark, report)
    _check_payment_amounts_non_negative(spark, report)
    _check_origination_before_maturity(spark, report)
    _check_credit_score_range(spark, report)
    _check_ltv_range(spark, report)


def _check_active_loan_positive_balance(spark: SparkSession, report: QualityReport) -> None:
    """Active loans must have a current_balance > 0."""
    table = "loan_warehouse.loan_accounts"
    try:
        df = spark.table(table)
    except Exception:
        return

    violations = df.filter(
        (F.col("status") == "Active") & (F.col("current_balance") <= 0)
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="active_loan_positive_balance",
        table=table,
        status="PASS" if violations == 0 else "FAIL",
        detail=(
            "All active loans have positive balance"
            if violations == 0
            else f"{violations} active loan(s) with balance <= 0"
        ),
        row_count=violations,
    ))


def _check_closed_loan_has_closed_date(spark: SparkSession, report: QualityReport) -> None:
    """Closed loans should have an updated_at date (proxy for closed date).

    The legacy schema does not have an explicit closed_date column. We use
    updated_at as a reasonable proxy — if it is NULL for a Closed loan, that
    is suspicious.
    """
    table = "loan_warehouse.loan_accounts"
    try:
        df = spark.table(table)
    except Exception:
        return

    violations = df.filter(
        (F.col("status") == "Closed") & F.col("updated_at").isNull()
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="closed_loan_has_date",
        table=table,
        status="PASS" if violations == 0 else "WARN",
        detail=(
            "All closed loans have an updated_at timestamp"
            if violations == 0
            else f"{violations} closed loan(s) missing updated_at (used as closed-date proxy)"
        ),
        row_count=violations,
    ))


def _check_payment_amounts_non_negative(spark: SparkSession, report: QualityReport) -> None:
    """Payment total_amount should be >= 0."""
    table = "loan_warehouse.payments"
    try:
        df = spark.table(table)
    except Exception:
        return

    violations = df.filter(F.col("total_amount") < 0).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="payment_non_negative",
        table=table,
        status="PASS" if violations == 0 else "FAIL",
        detail=(
            "All payments have non-negative total_amount"
            if violations == 0
            else f"{violations} payment(s) with negative total_amount"
        ),
        row_count=violations,
    ))


def _check_origination_before_maturity(spark: SparkSession, report: QualityReport) -> None:
    """Loan origination_date must be before maturity_date."""
    table = "loan_warehouse.loan_accounts"
    try:
        df = spark.table(table)
    except Exception:
        return

    violations = df.filter(
        F.col("origination_date") >= F.col("maturity_date")
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="origination_before_maturity",
        table=table,
        status="PASS" if violations == 0 else "FAIL",
        detail=(
            "All loans have origination_date < maturity_date"
            if violations == 0
            else f"{violations} loan(s) where origination_date >= maturity_date"
        ),
        row_count=violations,
    ))


def _check_credit_score_range(spark: SparkSession, report: QualityReport) -> None:
    """Borrower credit_score should be between 300 and 850."""
    table = "loan_warehouse.borrowers"
    try:
        df = spark.table(table)
    except Exception:
        return

    violations = df.filter(
        F.col("credit_score").isNotNull()
        & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="credit_score_range",
        table=table,
        status="PASS" if violations == 0 else "WARN",
        detail=(
            "All credit scores in valid range [300, 850]"
            if violations == 0
            else f"{violations} borrower(s) with credit score outside [300, 850]"
        ),
        row_count=violations,
    ))


def _check_ltv_range(spark: SparkSession, report: QualityReport) -> None:
    """Loan LTV percent should be between 0 and 200 (generous upper bound)."""
    table = "loan_warehouse.loan_accounts"
    try:
        df = spark.table(table)
    except Exception:
        return

    violations = df.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="ltv_range",
        table=table,
        status="PASS" if violations == 0 else "WARN",
        detail=(
            "All LTV values in range [0, 200]"
            if violations == 0
            else f"{violations} loan(s) with LTV outside [0, 200]"
        ),
        row_count=violations,
    ))
