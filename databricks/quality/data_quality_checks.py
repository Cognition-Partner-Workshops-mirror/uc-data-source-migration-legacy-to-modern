"""
Data Quality Validation Framework for CDW Legacy-to-Modern Migration.

Runs post-ingestion checks and produces a structured report:
  1. Row count reconciliation (source vs target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts and borrowers/products
  4. Business rule validation (balance > 0 for active loans, etc.)

Usage (Databricks notebook):
    %run ./data_quality_checks

Usage (spark-submit):
    spark-submit data_quality_checks.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str
    check_name: str
    status: str  # PASS, FAIL, WARN
    details: str
    expected: Any = None
    actual: Any = None


@dataclass
class QualityReport:
    run_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warnings(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")

    @property
    def total(self) -> int:
        return len(self.results)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(
    spark: SparkSession,
    report: QualityReport,
    source_counts: dict[str, int] | None = None,
) -> None:
    """Compare source vs target row counts for each table.

    If source_counts is None, reads from the legacy landing zone CSVs.
    """
    tables = {
        "borrowers": "/mnt/landing/cdw_borr_mstr/",
        "loan_products": "/mnt/landing/cdw_ln_prod/",
        "loan_accounts": "/mnt/landing/cdw_ln_acct/",
        "payments": "/mnt/landing/cdw_pmt_hist/",
    }

    for table_name, source_path in tables.items():
        target_fq = f"loan_warehouse.{table_name}"

        # Get source count
        if source_counts and table_name in source_counts:
            src_count = source_counts[table_name]
        else:
            try:
                src_df = spark.read.option("header", "true").csv(source_path)
                src_count = src_df.count()
            except Exception:
                try:
                    src_df = spark.read.parquet(source_path)
                    src_count = src_df.count()
                except Exception:
                    report.add(CheckResult(
                        category="Row Count",
                        check_name=f"{table_name}: source readable",
                        status="WARN",
                        details=f"Could not read source at {source_path}. Skipping count check.",
                    ))
                    continue

        # Get target count
        try:
            tgt_count = spark.table(target_fq).count()
        except Exception:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"{table_name}: target exists",
                status="FAIL",
                details=f"Target table {target_fq} does not exist or is not readable.",
            ))
            continue

        # Also check quarantine
        quarantine_path = f"/mnt/quarantine/{source_path.split('/')[-2]}/"
        quarantine_count = 0
        try:
            quarantine_count = spark.read.format("delta").load(quarantine_path).count()
        except Exception:
            pass  # no quarantine records

        total_accounted = tgt_count + quarantine_count
        status = "PASS" if total_accounted == src_count else "FAIL"

        report.add(CheckResult(
            category="Row Count",
            check_name=f"{table_name}: source vs target+quarantine",
            status=status,
            details=(
                f"source={src_count}, target={tgt_count}, "
                f"quarantine={quarantine_count}, accounted={total_accounted}"
            ),
            expected=src_count,
            actual=total_accounted,
        ))


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": [
        "external_id", "first_name", "last_name", "status",
    ],
    "loan_warehouse.loan_products": [
        "code", "name", "type", "term_months", "rate_type",
    ],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_key", "product_key",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "status",
    ],
    "loan_warehouse.payments": [
        "loan_account_key", "payment_date", "total_amount", "type", "status",
    ],
}


def check_required_nulls(spark: SparkSession, report: QualityReport) -> None:
    """Check that required columns have no NULL values."""
    for table_fq, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table_fq)
        except Exception:
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table_fq}: table readable",
                status="FAIL",
                details=f"Cannot read table {table_fq}.",
            ))
            continue

        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            total = df.count()
            status = "PASS" if null_count == 0 else "FAIL"

            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table_fq}.{col_name}: no nulls",
                status=status,
                details=f"{null_count}/{total} rows have NULL in {col_name}",
                expected=0,
                actual=null_count,
            ))


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Verify FK relationships between tables."""

    # loan_accounts.borrower_key -> borrowers.borrower_key
    _check_fk(
        spark, report,
        child_table="loan_warehouse.loan_accounts",
        child_col="borrower_key",
        parent_table="loan_warehouse.borrowers",
        parent_col="borrower_key",
    )

    # loan_accounts.product_key -> loan_products.product_key
    _check_fk(
        spark, report,
        child_table="loan_warehouse.loan_accounts",
        child_col="product_key",
        parent_table="loan_warehouse.loan_products",
        parent_col="product_key",
    )

    # payments.loan_account_key -> loan_accounts.loan_account_key
    _check_fk(
        spark, report,
        child_table="loan_warehouse.payments",
        child_col="loan_account_key",
        parent_table="loan_warehouse.loan_accounts",
        parent_col="loan_account_key",
    )


def _check_fk(
    spark: SparkSession,
    report: QualityReport,
    child_table: str,
    child_col: str,
    parent_table: str,
    parent_col: str,
) -> None:
    """Check that all non-null FK values in child exist in parent."""
    check_name = f"{child_table}.{child_col} -> {parent_table}.{parent_col}"
    try:
        child_df = spark.table(child_table)
        parent_df = spark.table(parent_table)
    except Exception as e:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name=check_name,
            status="FAIL",
            details=f"Cannot read tables: {e}",
        ))
        return

    orphans = (
        child_df.select(F.col(child_col).alias("fk"))
        .filter(F.col("fk").isNotNull())
        .join(
            parent_df.select(F.col(parent_col).alias("pk")),
            F.col("fk") == F.col("pk"),
            "left_anti",
        )
        .count()
    )

    total = child_df.filter(F.col(child_col).isNotNull()).count()
    status = "PASS" if orphans == 0 else "FAIL"

    report.add(CheckResult(
        category="Referential Integrity",
        check_name=check_name,
        status=status,
        details=f"{orphans}/{total} orphaned FK values",
        expected=0,
        actual=orphans,
    ))


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules."""

    try:
        loans = spark.table("loan_warehouse.loan_accounts")
    except Exception:
        report.add(CheckResult(
            category="Business Rule",
            check_name="loan_accounts: table readable",
            status="FAIL",
            details="Cannot read loan_warehouse.loan_accounts.",
        ))
        return

    # Rule 1: Active loans must have current_balance > 0
    active_zero_balance = loans.filter(
        (F.col("status") == "Active") & (F.col("current_balance") <= 0)
    ).count()
    active_count = loans.filter(F.col("status") == "Active").count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans: balance > 0",
        status="PASS" if active_zero_balance == 0 else "FAIL",
        details=f"{active_zero_balance}/{active_count} active loans have balance <= 0",
        expected=0,
        actual=active_zero_balance,
    ))

    # Rule 2: Active loans must have maturity_date in the future relative to origination
    active_bad_maturity = loans.filter(
        (F.col("status") == "Active")
        & (F.col("maturity_date") <= F.col("origination_date"))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans: maturity > origination",
        status="PASS" if active_bad_maturity == 0 else "FAIL",
        details=f"{active_bad_maturity}/{active_count} active loans have maturity <= origination",
        expected=0,
        actual=active_bad_maturity,
    ))

    # Rule 3: interest_rate must be between 0 and 100
    bad_rate = loans.filter(
        (F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)
    ).count()
    total_loans = loans.count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Loans: interest_rate in [0, 100]",
        status="PASS" if bad_rate == 0 else "FAIL",
        details=f"{bad_rate}/{total_loans} loans have interest rate outside [0, 100]",
        expected=0,
        actual=bad_rate,
    ))

    # Rule 4: LTV percent should be between 0 and 200 (if present)
    bad_ltv = loans.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Loans: ltv_percent in [0, 200]",
        status="PASS" if bad_ltv == 0 else "FAIL",
        details=f"{bad_ltv}/{total_loans} loans have LTV outside [0, 200]",
        expected=0,
        actual=bad_ltv,
    ))

    # Rule 5: delinquency_days >= 0
    bad_dlq = loans.filter(F.col("delinquency_days") < 0).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Loans: delinquency_days >= 0",
        status="PASS" if bad_dlq == 0 else "FAIL",
        details=f"{bad_dlq}/{total_loans} loans have negative delinquency days",
        expected=0,
        actual=bad_dlq,
    ))

    # Rule 6: Payment component sum <= total_amount (tolerance 0.01)
    try:
        payments = spark.table("loan_warehouse.payments")
        payments_with_sum = payments.withColumn(
            "_component_sum",
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0)),
        )
        bad_sums = payments_with_sum.filter(
            F.abs(F.col("_component_sum") - F.col("total_amount")) > 0.01
        ).count()
        total_payments = payments.count()
        report.add(CheckResult(
            category="Business Rule",
            check_name="Payments: component sum matches total",
            status="PASS" if bad_sums == 0 else "WARN",
            details=f"{bad_sums}/{total_payments} payments have component sum != total (tolerance 0.01)",
            expected=0,
            actual=bad_sums,
        ))
    except Exception:
        report.add(CheckResult(
            category="Business Rule",
            check_name="Payments: component sum matches total",
            status="FAIL",
            details="Cannot read loan_warehouse.payments.",
        ))

    # Rule 7: Borrower credit_score in valid range [300, 850] (if present)
    try:
        borrowers = spark.table("loan_warehouse.borrowers")
        bad_credit = borrowers.filter(
            F.col("credit_score").isNotNull()
            & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()
        total_borrowers = borrowers.count()
        report.add(CheckResult(
            category="Business Rule",
            check_name="Borrowers: credit_score in [300, 850]",
            status="PASS" if bad_credit == 0 else "WARN",
            details=f"{bad_credit}/{total_borrowers} borrowers have credit score outside [300, 850]",
            expected=0,
            actual=bad_credit,
        ))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_markdown_report(report: QualityReport) -> str:
    """Render the quality report as a Markdown document."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run Timestamp:** {report.run_timestamp}",
        "",
        "## Summary",
        "",
        f"| Metric   | Count |",
        f"|----------|-------|",
        f"| Total    | {report.total} |",
        f"| Passed   | {report.passed} |",
        f"| Failed   | {report.failed} |",
        f"| Warnings | {report.warnings} |",
        "",
        f"**Overall Status:** {'PASS' if report.failed == 0 else 'FAIL'}",
        "",
        "## Detailed Results",
        "",
    ]

    # Group by category
    categories: dict[str, list[CheckResult]] = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for cat, checks in categories.items():
        lines.append(f"### {cat}")
        lines.append("")
        lines.append("| Check | Status | Details |")
        lines.append("|-------|--------|---------|")
        for c in checks:
            icon = {"PASS": "PASS", "FAIL": "**FAIL**", "WARN": "WARN"}[c.status]
            details = c.details.replace("|", "\\|")
            lines.append(f"| {c.check_name} | {icon} | {details} |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_all_checks(
    spark: SparkSession | None = None,
    source_counts: dict[str, int] | None = None,
    output_path: str = "/mnt/reports/DATA_QUALITY_REPORT.md",
) -> QualityReport:
    """Run all data quality checks and write the report."""
    if spark is None:
        spark = SparkSession.builder.appName("DataQualityChecks").getOrCreate()

    report = QualityReport()

    print("Running row count reconciliation...")
    check_row_counts(spark, report, source_counts)

    print("Running null checks on required fields...")
    check_required_nulls(spark, report)

    print("Running referential integrity checks...")
    check_referential_integrity(spark, report)

    print("Running business rule validation...")
    check_business_rules(spark, report)

    # Generate markdown report
    md = generate_markdown_report(report)

    # Write report to DBFS / mounted storage
    try:
        spark.sparkContext.parallelize([md]).coalesce(1).saveAsTextFile(output_path)
        print(f"Report written to {output_path}")
    except Exception as e:
        print(f"WARNING: Could not write report to {output_path}: {e}")
        print("Report content follows:")
        print(md)

    # Also print summary
    print(f"\n{'='*60}")
    print(f"  DATA QUALITY SUMMARY")
    print(f"{'='*60}")
    print(f"  Total checks:  {report.total}")
    print(f"  Passed:        {report.passed}")
    print(f"  Failed:        {report.failed}")
    print(f"  Warnings:      {report.warnings}")
    print(f"  Overall:       {'PASS' if report.failed == 0 else 'FAIL'}")

    return report


if __name__ == "__main__":
    run_all_checks()
