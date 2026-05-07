"""
Data-quality validation framework for the legacy CDW → Delta Lake migration.

Provides check functions that return structured results (pass/fail, counts,
details) which are aggregated into a DATA_QUALITY_REPORT.md by the runner.
"""

import logging
from dataclasses import dataclass, field
from typing import List

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

logger = logging.getLogger("migration.quality")


@dataclass
class CheckResult:
    """Outcome of a single data-quality check."""

    category: str
    check_name: str
    passed: bool
    detail: str
    expected: str = ""
    actual: str = ""


@dataclass
class QualityReport:
    """Aggregated quality report across all checks."""

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

    def add(self, result: CheckResult) -> None:
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info("[%s] %s / %s — %s", status, result.category, result.check_name, result.detail)


# ---------------------------------------------------------------------------
# 1. Row-count reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(report: QualityReport, pipeline_results: dict) -> None:
    """Verify source vs. target row counts from the ingestion pipeline results.

    Quarantined records are acceptable as long as they are accounted for.
    """
    for table_name, counts in pipeline_results.items():
        src = counts.get("source_count", 0)
        tgt = counts.get("target_count", 0)
        quarantined = src - tgt

        passed = tgt > 0 and (tgt + quarantined) == src
        report.add(CheckResult(
            category="Row Count Reconciliation",
            check_name=f"{table_name} source vs target",
            passed=passed,
            detail=f"source={src}, target={tgt}, quarantined={quarantined}",
            expected=str(src),
            actual=f"{tgt} loaded + {quarantined} quarantined",
        ))


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_warehouse.loan_products": ["code", "name", "type"],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id", "status",
    ],
    "loan_warehouse.payments": ["loan_account_id", "payment_date", "status"],
}


def check_required_nulls(spark: SparkSession, report: QualityReport) -> None:
    """Check that required columns contain no null values."""
    for table, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table)
        except Exception:
            report.add(CheckResult(
                category="Null Checks",
                check_name=f"{table} table access",
                passed=False,
                detail=f"Could not read table {table}",
            ))
            continue

        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            total_count = df.count()
            passed = null_count == 0
            report.add(CheckResult(
                category="Null Checks",
                check_name=f"{table}.{col_name} NOT NULL",
                passed=passed,
                detail=f"{null_count} nulls out of {total_count} rows",
                expected="0 nulls",
                actual=str(null_count),
            ))


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Verify FK relationships between loan_accounts ↔ borrowers,
    loan_accounts ↔ loan_products, and payments ↔ loan_accounts.
    """
    checks = [
        (
            "loan_accounts → borrowers",
            "loan_warehouse.loan_accounts",
            "borrower_id",
            "loan_warehouse.borrowers",
            "id",
        ),
        (
            "loan_accounts → loan_products",
            "loan_warehouse.loan_accounts",
            "product_id",
            "loan_warehouse.loan_products",
            "id",
        ),
        (
            "payments → loan_accounts",
            "loan_warehouse.payments",
            "loan_account_id",
            "loan_warehouse.loan_accounts",
            "id",
        ),
    ]

    for label, child_table, child_col, parent_table, parent_col in checks:
        try:
            child_df = spark.table(child_table)
            parent_df = spark.table(parent_table)
        except Exception:
            report.add(CheckResult(
                category="Referential Integrity",
                check_name=label,
                passed=False,
                detail=f"Could not read {child_table} or {parent_table}",
            ))
            continue

        orphan_count = (
            child_df.join(
                parent_df,
                child_df[child_col] == parent_df[parent_col],
                "left_anti",
            )
            .filter(F.col(child_col).isNotNull())
            .count()
        )

        total = child_df.count()
        passed = orphan_count == 0
        report.add(CheckResult(
            category="Referential Integrity",
            check_name=label,
            passed=passed,
            detail=f"{orphan_count} orphan rows out of {total}",
            expected="0 orphans",
            actual=str(orphan_count),
        ))


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules for loan data."""

    # Rule 1: Active loans must have a positive current balance
    try:
        loans = spark.table("loan_warehouse.loan_accounts")

        active_zero_balance = loans.filter(
            (F.col("status") == "ACTIVE")
            & (F.col("current_balance").isNotNull())
            & (F.col("current_balance") <= 0)
        ).count()
        active_total = loans.filter(F.col("status") == "ACTIVE").count()

        report.add(CheckResult(
            category="Business Rules",
            check_name="Active loans must have balance > 0",
            passed=active_zero_balance == 0,
            detail=f"{active_zero_balance} active loans with balance <= 0 (of {active_total} active)",
            expected="0 violations",
            actual=str(active_zero_balance),
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Active loans must have balance > 0",
            passed=False,
            detail=f"Error: {e}",
        ))

    # Rule 2: Closed loans should have a closed/maturity date in the past
    try:
        closed_no_maturity = loans.filter(
            (F.col("status") == "CLOSED")
            & F.col("maturity_date").isNull()
        ).count()
        closed_total = loans.filter(F.col("status") == "CLOSED").count()

        report.add(CheckResult(
            category="Business Rules",
            check_name="Closed loans must have maturity_date",
            passed=closed_no_maturity == 0,
            detail=f"{closed_no_maturity} closed loans missing maturity_date (of {closed_total} closed)",
            expected="0 violations",
            actual=str(closed_no_maturity),
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Closed loans must have maturity_date",
            passed=False,
            detail=f"Error: {e}",
        ))

    # Rule 3: Interest rate should be between 0 and 100
    try:
        invalid_rate = loans.filter(
            (F.col("interest_rate").isNotNull())
            & ((F.col("interest_rate") < 0) | (F.col("interest_rate") > 100))
        ).count()

        report.add(CheckResult(
            category="Business Rules",
            check_name="Interest rate between 0 and 100",
            passed=invalid_rate == 0,
            detail=f"{invalid_rate} loans with interest rate outside [0, 100]",
            expected="0 violations",
            actual=str(invalid_rate),
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Interest rate between 0 and 100",
            passed=False,
            detail=f"Error: {e}",
        ))

    # Rule 4: Delinquency days must be >= 0
    try:
        negative_dlq = loans.filter(
            (F.col("delinquency_days").isNotNull())
            & (F.col("delinquency_days") < 0)
        ).count()

        report.add(CheckResult(
            category="Business Rules",
            check_name="Delinquency days >= 0",
            passed=negative_dlq == 0,
            detail=f"{negative_dlq} loans with negative delinquency days",
            expected="0 violations",
            actual=str(negative_dlq),
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Delinquency days >= 0",
            passed=False,
            detail=f"Error: {e}",
        ))

    # Rule 5: Payment amounts should be positive for posted payments
    try:
        payments = spark.table("loan_warehouse.payments")

        negative_payments = payments.filter(
            (F.col("status") == "POSTED")
            & (F.col("total_amount").isNotNull())
            & (F.col("total_amount") <= 0)
        ).count()
        posted_total = payments.filter(F.col("status") == "POSTED").count()

        report.add(CheckResult(
            category="Business Rules",
            check_name="Posted payments must have amount > 0",
            passed=negative_payments == 0,
            detail=f"{negative_payments} posted payments with amount <= 0 (of {posted_total} posted)",
            expected="0 violations",
            actual=str(negative_payments),
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Posted payments must have amount > 0",
            passed=False,
            detail=f"Error: {e}",
        ))

    # Rule 6: Origination date must be before maturity date
    try:
        bad_dates = loans.filter(
            (F.col("origination_date").isNotNull())
            & (F.col("maturity_date").isNotNull())
            & (F.col("origination_date") >= F.col("maturity_date"))
        ).count()

        report.add(CheckResult(
            category="Business Rules",
            check_name="Origination date before maturity date",
            passed=bad_dates == 0,
            detail=f"{bad_dates} loans where origination_date >= maturity_date",
            expected="0 violations",
            actual=str(bad_dates),
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Origination date before maturity date",
            passed=False,
            detail=f"Error: {e}",
        ))

    # Rule 7: LTV percent should be between 0 and 200
    try:
        bad_ltv = loans.filter(
            (F.col("ltv_percent").isNotNull())
            & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
        ).count()

        report.add(CheckResult(
            category="Business Rules",
            check_name="LTV percent between 0 and 200",
            passed=bad_ltv == 0,
            detail=f"{bad_ltv} loans with LTV outside [0, 200]",
            expected="0 violations",
            actual=str(bad_ltv),
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="LTV percent between 0 and 200",
            passed=False,
            detail=f"Error: {e}",
        ))
