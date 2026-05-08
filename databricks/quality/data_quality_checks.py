"""
Data Quality Framework for the legacy CDW → modern Delta Lake migration.

Runs post-ingestion and validates:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts ↔ borrowers / loan_products,
     and payments ↔ loan_accounts
  4. Business rule validation (e.g., active loans must have balance > 0)
  5. Generates a DATA_QUALITY_REPORT.md summarizing pass/fail results

Usage:
  spark-submit data_quality_checks.py
  — or —
  %run ./data_quality_checks   (Databricks notebook)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import List

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Single quality-check outcome."""
    category: str
    check_name: str
    passed: bool
    detail: str


@dataclass
class QualityReport:
    """Aggregated report across all checks."""
    results: List[CheckResult] = field(default_factory=list)
    run_timestamp: str = field(
        default_factory=lambda: datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    )

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed


# ---------------------------------------------------------------------------
# 1. Row count reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession, report: QualityReport,
                     source_counts: dict[str, int]) -> None:
    """Compare expected source row counts against modern target tables.

    source_counts maps legacy table names to their expected row counts,
    e.g. {"CDW_BORR_MSTR": 5, "CDW_LN_PROD": 5, ...}.
    """
    target_map = {
        "CDW_BORR_MSTR": "loan_warehouse.borrowers",
        "CDW_LN_PROD": "loan_warehouse.loan_products",
        "CDW_LN_ACCT": "loan_warehouse.loan_accounts",
        "CDW_PMT_HIST": "loan_warehouse.payments",
    }

    for legacy_name, target_table in target_map.items():
        expected = source_counts.get(legacy_name, 0)
        actual = spark.table(target_table).count()
        ok = expected == actual
        report.add(CheckResult(
            category="Row Count Reconciliation",
            check_name=f"{legacy_name} → {target_table}",
            passed=ok,
            detail=f"Expected {expected}, got {actual}" if not ok
                   else f"{actual} rows — match",
        ))


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------

# Mapping: table → list of columns that must NOT be null
REQUIRED_COLUMNS = {
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
        "loan_account_id", "payment_date", "total_amount", "type", "status",
    ],
}


def check_required_nulls(spark: SparkSession, report: QualityReport) -> None:
    """Verify that required columns contain no NULLs."""
    for table, columns in REQUIRED_COLUMNS.items():
        df = spark.table(table)
        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            ok = null_count == 0
            report.add(CheckResult(
                category="Required Field Null Check",
                check_name=f"{table}.{col_name}",
                passed=ok,
                detail=f"{null_count} NULL(s) found" if not ok else "No NULLs",
            ))


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------

def _check_fk(spark: SparkSession, report: QualityReport,
              child_table: str, child_col: str,
              parent_table: str, parent_col: str) -> None:
    """Verify every child FK value exists in the parent table."""
    child_df = spark.table(child_table).select(F.col(child_col).alias("fk_val")).distinct()
    parent_df = spark.table(parent_table).select(F.col(parent_col).alias("pk_val")).distinct()

    orphans = child_df.join(parent_df, child_df["fk_val"] == parent_df["pk_val"], "left_anti")
    orphan_count = orphans.count()
    ok = orphan_count == 0

    report.add(CheckResult(
        category="Referential Integrity",
        check_name=f"{child_table}.{child_col} → {parent_table}.{parent_col}",
        passed=ok,
        detail=f"{orphan_count} orphan(s)" if not ok else "All FKs resolve",
    ))


def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Run FK checks for all declared relationships."""
    # loan_accounts.borrower_id → borrowers.id
    _check_fk(spark, report,
              "loan_warehouse.loan_accounts", "borrower_id",
              "loan_warehouse.borrowers", "id")

    # loan_accounts.product_id → loan_products.id
    _check_fk(spark, report,
              "loan_warehouse.loan_accounts", "product_id",
              "loan_warehouse.loan_products", "id")

    # payments.loan_account_id → loan_accounts.id
    _check_fk(spark, report,
              "loan_warehouse.payments", "loan_account_id",
              "loan_warehouse.loan_accounts", "id")


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules on the migrated data."""

    loans = spark.table("loan_warehouse.loan_accounts")
    payments = spark.table("loan_warehouse.payments")

    # Rule 1: Active loans must have current_balance > 0
    active_zero_balance = loans.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Active loans must have balance > 0",
        passed=active_zero_balance == 0,
        detail=f"{active_zero_balance} active loan(s) with balance <= 0"
               if active_zero_balance > 0 else "All active loans have positive balance",
    ))

    # Rule 2: Closed loans should have a maturity_date that is not null
    closed_no_maturity = loans.filter(
        (F.col("status") == "CLOSED") & F.col("maturity_date").isNull()
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Closed loans must have maturity_date",
        passed=closed_no_maturity == 0,
        detail=f"{closed_no_maturity} closed loan(s) missing maturity_date"
               if closed_no_maturity > 0 else "All closed loans have maturity_date",
    ))

    # Rule 3: Interest rate must be between 0 and 100 (percent)
    bad_rate = loans.filter(
        (F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Interest rate must be in [0, 100]",
        passed=bad_rate == 0,
        detail=f"{bad_rate} loan(s) with out-of-range rate" if bad_rate > 0
               else "All rates within range",
    ))

    # Rule 4: Delinquency days must be >= 0
    neg_dlq = loans.filter(F.col("delinquency_days") < 0).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Delinquency days must be >= 0",
        passed=neg_dlq == 0,
        detail=f"{neg_dlq} loan(s) with negative delinquency days" if neg_dlq > 0
               else "All delinquency days non-negative",
    ))

    # Rule 5: Payment total_amount must be > 0 for POSTED payments
    posted_zero = payments.filter(
        (F.col("status") == "POSTED") & (F.col("total_amount") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Posted payments must have total_amount > 0",
        passed=posted_zero == 0,
        detail=f"{posted_zero} posted payment(s) with amount <= 0" if posted_zero > 0
               else "All posted payments have positive amount",
    ))

    # Rule 6: Origination date must be before maturity date
    bad_dates = loans.filter(
        F.col("origination_date") >= F.col("maturity_date")
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Origination date must precede maturity date",
        passed=bad_dates == 0,
        detail=f"{bad_dates} loan(s) where origination >= maturity" if bad_dates > 0
               else "All origination dates precede maturity dates",
    ))

    # Rule 7: LTV percent should be in [0, 200] (reasonable range)
    bad_ltv = loans.filter(
        F.col("ltv_percent").isNotNull() &
        ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="LTV percent must be in [0, 200]",
        passed=bad_ltv == 0,
        detail=f"{bad_ltv} loan(s) with out-of-range LTV" if bad_ltv > 0
               else "All LTV values within range",
    ))

    # Rule 8: Credit score must be in [300, 850]
    borrowers = spark.table("loan_warehouse.borrowers")
    bad_credit = borrowers.filter(
        F.col("credit_score").isNotNull() &
        ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Credit score must be in [300, 850]",
        passed=bad_credit == 0,
        detail=f"{bad_credit} borrower(s) with out-of-range credit score" if bad_credit > 0
               else "All credit scores within range",
    ))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report_markdown(report: QualityReport) -> str:
    """Render the QualityReport as a Markdown document."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run timestamp:** {report.run_timestamp}",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total checks | {report.total} |",
        f"| Passed | {report.passed} |",
        f"| Failed | {report.failed} |",
        "",
    ]

    # Group results by category for readability
    categories: dict[str, list[CheckResult]] = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for cat, checks in categories.items():
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Check | Result | Detail |")
        lines.append("|-------|--------|--------|")
        for c in checks:
            icon = "PASS" if c.passed else "**FAIL**"
            lines.append(f"| {c.check_name} | {icon} | {c.detail} |")
        lines.append("")

    # Overall verdict
    if report.failed == 0:
        lines.append("---")
        lines.append("**Overall: ALL CHECKS PASSED**")
    else:
        lines.append("---")
        lines.append(f"**Overall: {report.failed} CHECK(S) FAILED — review details above**")

    return "\n".join(lines)


def save_report(report: QualityReport, path: str = "/dbfs/mnt/loan_warehouse/DATA_QUALITY_REPORT.md") -> str:
    """Write the Markdown report to DBFS and return the content."""
    content = generate_report_markdown(report)

    # Write via Python file I/O (works on Databricks driver node)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[INFO] Data quality report saved to {path}")
    return content


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(source_counts: dict[str, int] | None = None) -> QualityReport:
    """Run all quality checks and produce a report.

    Args:
        source_counts: Optional dict of legacy table name → expected row count.
                       If None, row-count reconciliation is skipped.
    """
    spark = SparkSession.builder.appName("DataQualityChecks").getOrCreate()
    report = QualityReport()

    print("[INFO] Running data quality checks …")

    # 1. Row counts (if source counts provided)
    if source_counts:
        print("[INFO]  → Row count reconciliation")
        check_row_counts(spark, report, source_counts)
    else:
        print("[WARN]  → Skipping row count reconciliation (no source counts provided)")

    # 2. Null checks
    print("[INFO]  → Required field null checks")
    check_required_nulls(spark, report)

    # 3. Referential integrity
    print("[INFO]  → Referential integrity checks")
    check_referential_integrity(spark, report)

    # 4. Business rules
    print("[INFO]  → Business rule validation")
    check_business_rules(spark, report)

    # Generate and save report
    content = save_report(report)
    print("\n" + content)

    return report


if __name__ == "__main__":
    # Default source counts from the legacy seed data
    default_source_counts = {
        "CDW_BORR_MSTR": 5,
        "CDW_LN_PROD": 5,
        "CDW_LN_ACCT": 5,
        "CDW_PMT_HIST": 10,
    }
    main(source_counts=default_source_counts)
