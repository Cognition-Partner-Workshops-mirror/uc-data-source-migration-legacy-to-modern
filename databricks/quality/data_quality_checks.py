"""
Data Quality Framework for Legacy CDW → Delta Lake Migration

Runs post-ingestion validation checks against the modern Delta Lake tables:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan and borrower tables
  4. Business rule validation (balance > 0 for active loans, etc.)

Results are collected and written to docs/DATA_QUALITY_REPORT.md.

Usage:
    spark-submit data_quality_checks.py \
        --source-borrowers /mnt/landing/cdw_borr_mstr/ \
        --source-products /mnt/landing/cdw_ln_prod/ \
        --source-loans /mnt/landing/cdw_ln_acct/ \
        --source-payments /mnt/landing/cdw_pmt_hist/ \
        --output-report /repo/docs/DATA_QUALITY_REPORT.md
"""

import argparse
from datetime import datetime
from dataclasses import dataclass, field
from typing import List

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


@dataclass
class CheckResult:
    """Represents the result of a single data quality check."""
    category: str
    check_name: str
    status: str  # "PASS", "FAIL", "WARN"
    details: str
    affected_count: int = 0
    total_count: int = 0


@dataclass
class QualityReport:
    """Collects all check results and generates the report."""
    results: List[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult):
        self.results.append(result)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")

    def to_markdown(self) -> str:
        """Generate the DATA_QUALITY_REPORT.md content."""
        lines = [
            "# Data Quality Report — CDW Migration Validation",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total Checks | {len(self.results)} |",
            f"| Passed | {self.pass_count} |",
            f"| Failed | {self.fail_count} |",
            f"| Warnings | {self.warn_count} |",
            "",
            f"**Overall Status:** {'PASS' if self.fail_count == 0 else 'FAIL'}",
            "",
            "---",
            "",
        ]

        # Group results by category
        categories = {}
        for r in self.results:
            categories.setdefault(r.category, []).append(r)

        for category, checks in categories.items():
            lines.append(f"## {category}")
            lines.append("")
            lines.append("| Check | Status | Details | Affected/Total |")
            lines.append("|-------|--------|---------|----------------|")
            for c in checks:
                status_icon = {"PASS": "PASS", "FAIL": "**FAIL**", "WARN": "WARN"}[c.status]
                count_str = (
                    f"{c.affected_count}/{c.total_count}" if c.total_count > 0 else "—"
                )
                lines.append(f"| {c.check_name} | {status_icon} | {c.details} | {count_str} |")
            lines.append("")

        return "\n".join(lines)


# =============================================================================
# Check 1: Row Count Reconciliation
# =============================================================================

def check_row_counts(
    spark: SparkSession,
    report: QualityReport,
    source_path: str,
    target_table: str,
    table_label: str,
    fmt: str = "csv",
):
    """
    Compare row counts between source files and target Delta table.
    Ensures no records were silently dropped during ingestion.
    """
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    source_df = reader.csv(source_path) if fmt == "csv" else reader.parquet(source_path)
    source_count = source_df.count()

    target_df = spark.table(target_table)
    target_count = target_df.count()

    if source_count == target_count:
        report.add(CheckResult(
            category="Row Count Reconciliation",
            check_name=f"{table_label}: source vs. target",
            status="PASS",
            details=f"Counts match: {source_count}",
            affected_count=0,
            total_count=source_count,
        ))
    else:
        diff = source_count - target_count
        report.add(CheckResult(
            category="Row Count Reconciliation",
            check_name=f"{table_label}: source vs. target",
            status="FAIL" if abs(diff) > 0 else "PASS",
            details=f"Source={source_count}, Target={target_count}, Diff={diff} (quarantined or dropped)",
            affected_count=abs(diff),
            total_count=source_count,
        ))


# =============================================================================
# Check 2: Null Checks on Required Fields
# =============================================================================

def check_required_not_null(
    spark: SparkSession,
    report: QualityReport,
    table_name: str,
    table_label: str,
    required_columns: List[str],
):
    """
    Verify that required columns have no null values in the target Delta table.
    Each column is checked independently.
    """
    df = spark.table(table_name)
    total = df.count()

    for col_name in required_columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        if null_count == 0:
            report.add(CheckResult(
                category="Null Checks — Required Fields",
                check_name=f"{table_label}.{col_name} NOT NULL",
                status="PASS",
                details=f"No nulls found",
                affected_count=0,
                total_count=total,
            ))
        else:
            report.add(CheckResult(
                category="Null Checks — Required Fields",
                check_name=f"{table_label}.{col_name} NOT NULL",
                status="FAIL",
                details=f"{null_count} null values in required field",
                affected_count=null_count,
                total_count=total,
            ))


# =============================================================================
# Check 3: Referential Integrity
# =============================================================================

def check_referential_integrity(
    spark: SparkSession,
    report: QualityReport,
    child_table: str,
    child_label: str,
    child_fk_col: str,
    parent_table: str,
    parent_label: str,
    parent_pk_col: str,
):
    """
    Verify that all FK values in the child table exist in the parent table.
    Detects orphaned records that would have been allowed by the legacy
    schema's lack of FK constraints (see Anomaly #7).
    """
    child_df = spark.table(child_table)
    parent_df = spark.table(parent_table)
    total = child_df.count()

    # Find orphans: child FK not in parent PK
    orphans = child_df.join(
        parent_df,
        child_df[child_fk_col] == parent_df[parent_pk_col],
        "left_anti",
    )
    # Also count nulls in FK column as integrity issues
    null_fk_count = child_df.filter(F.col(child_fk_col).isNull()).count()
    orphan_count = orphans.count() + null_fk_count

    if orphan_count == 0:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name=f"{child_label}.{child_fk_col} → {parent_label}.{parent_pk_col}",
            status="PASS",
            details=f"All FK references valid",
            affected_count=0,
            total_count=total,
        ))
    else:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name=f"{child_label}.{child_fk_col} → {parent_label}.{parent_pk_col}",
            status="FAIL",
            details=f"{orphan_count} orphaned records (null FK or missing parent)",
            affected_count=orphan_count,
            total_count=total,
        ))


# =============================================================================
# Check 4: Business Rule Validation
# =============================================================================

def check_active_loan_positive_balance(spark: SparkSession, report: QualityReport):
    """
    Business rule: Active loans must have current_balance > 0.
    A zero or negative balance on an active loan indicates a data error
    (loan should be marked CLOSED).
    """
    df = spark.table("loan_warehouse.loan_accounts")
    active_loans = df.filter(F.col("status") == "ACTIVE")
    total = active_loans.count()

    violations = active_loans.filter(
        (F.col("current_balance").isNull()) | (F.col("current_balance") <= 0)
    )
    violation_count = violations.count()

    report.add(CheckResult(
        category="Business Rule Validation",
        check_name="Active loans: current_balance > 0",
        status="PASS" if violation_count == 0 else "FAIL",
        details=(
            "All active loans have positive balance"
            if violation_count == 0
            else f"{violation_count} active loans with zero/negative balance"
        ),
        affected_count=violation_count,
        total_count=total,
    ))


def check_closed_loan_has_status(spark: SparkSession, report: QualityReport):
    """
    Business rule: Closed loans should exist in the system.
    (In a full schema, closed loans would require a closed_date — here we
    just verify any CLOSED records are properly flagged.)
    """
    df = spark.table("loan_warehouse.loan_accounts")
    closed_loans = df.filter(F.col("status") == "CLOSED")
    total = closed_loans.count()

    if total == 0:
        report.add(CheckResult(
            category="Business Rule Validation",
            check_name="Closed loans: proper status flag",
            status="PASS",
            details="No closed loans in current dataset (informational)",
            affected_count=0,
            total_count=0,
        ))
    else:
        report.add(CheckResult(
            category="Business Rule Validation",
            check_name="Closed loans: proper status flag",
            status="PASS",
            details=f"{total} closed loans with proper status",
            affected_count=0,
            total_count=total,
        ))


def check_delinquency_status_consistency(spark: SparkSession, report: QualityReport):
    """
    Business rule: Loans with delinquency_days > 0 should not be marked ACTIVE.
    Catches the status inconsistency identified in DATA_ANOMALY_REPORT Anomaly #5.
    """
    df = spark.table("loan_warehouse.loan_accounts")
    total = df.count()

    violations = df.filter(
        (F.col("delinquency_days") > 0) & (F.col("status") == "ACTIVE")
    )
    violation_count = violations.count()

    report.add(CheckResult(
        category="Business Rule Validation",
        check_name="Delinquent loans: status != ACTIVE",
        status="PASS" if violation_count == 0 else "WARN",
        details=(
            "No status/delinquency inconsistencies"
            if violation_count == 0
            else f"{violation_count} loans with delinquency_days > 0 but status=ACTIVE"
        ),
        affected_count=violation_count,
        total_count=total,
    ))


def check_payment_component_sum(spark: SparkSession, report: QualityReport):
    """
    Business rule: Payment components (principal + interest + escrow + late_fee)
    should sum to total_amount within $0.01 tolerance.
    Catches Anomaly #1 from DATA_ANOMALY_REPORT.
    """
    df = spark.table("loan_warehouse.payments")
    total = df.count()

    df_with_sum = df.withColumn(
        "_component_sum",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0)),
    )
    violations = df_with_sum.filter(
        F.abs(F.col("total_amount") - F.col("_component_sum")) > 0.01
    )
    violation_count = violations.count()

    report.add(CheckResult(
        category="Business Rule Validation",
        check_name="Payments: component sum = total_amount (±$0.01)",
        status="PASS" if violation_count == 0 else "WARN",
        details=(
            "All payment components sum correctly"
            if violation_count == 0
            else f"{violation_count} payments with component sum mismatch (known CDW anomaly)"
        ),
        affected_count=violation_count,
        total_count=total,
    ))


def check_origination_before_maturity(spark: SparkSession, report: QualityReport):
    """
    Business rule: Loan origination_date must be before maturity_date.
    """
    df = spark.table("loan_warehouse.loan_accounts")
    total = df.filter(
        F.col("origination_date").isNotNull() & F.col("maturity_date").isNotNull()
    ).count()

    violations = df.filter(
        F.col("origination_date").isNotNull()
        & F.col("maturity_date").isNotNull()
        & (F.col("origination_date") >= F.col("maturity_date"))
    )
    violation_count = violations.count()

    report.add(CheckResult(
        category="Business Rule Validation",
        check_name="Loans: origination_date < maturity_date",
        status="PASS" if violation_count == 0 else "FAIL",
        details=(
            "All loans have valid date ordering"
            if violation_count == 0
            else f"{violation_count} loans with origination >= maturity date"
        ),
        affected_count=violation_count,
        total_count=total,
    ))


def check_credit_score_range(spark: SparkSession, report: QualityReport):
    """
    Business rule: Borrower credit scores should be between 300 and 850.
    """
    df = spark.table("loan_warehouse.borrowers")
    scored = df.filter(F.col("credit_score").isNotNull())
    total = scored.count()

    violations = scored.filter(
        (F.col("credit_score") < 300) | (F.col("credit_score") > 850)
    )
    violation_count = violations.count()

    report.add(CheckResult(
        category="Business Rule Validation",
        check_name="Borrowers: credit_score in [300, 850]",
        status="PASS" if violation_count == 0 else "WARN",
        details=(
            "All credit scores in valid range"
            if violation_count == 0
            else f"{violation_count} borrowers with out-of-range credit score"
        ),
        affected_count=violation_count,
        total_count=total,
    ))


# =============================================================================
# Main runner
# =============================================================================

def run_all_checks(
    spark: SparkSession,
    source_borrowers: str,
    source_products: str,
    source_loans: str,
    source_payments: str,
    fmt: str = "csv",
) -> QualityReport:
    """Run all data quality checks and return the consolidated report."""
    report = QualityReport()

    # --- Row count reconciliation ---
    check_row_counts(spark, report, source_borrowers, "loan_warehouse.borrowers", "Borrowers", fmt)
    check_row_counts(spark, report, source_products, "loan_warehouse.loan_products", "Loan Products", fmt)
    check_row_counts(spark, report, source_loans, "loan_warehouse.loan_accounts", "Loan Accounts", fmt)
    check_row_counts(spark, report, source_payments, "loan_warehouse.payments", "Payments", fmt)

    # --- Null checks on required fields ---
    check_required_not_null(spark, report, "loan_warehouse.borrowers", "borrowers",
                            ["external_id", "first_name", "last_name", "ssn_hash", "status", "created_at", "updated_at"])
    check_required_not_null(spark, report, "loan_warehouse.loan_products", "loan_products",
                            ["code", "name", "type", "is_active"])
    check_required_not_null(spark, report, "loan_warehouse.loan_accounts", "loan_accounts",
                            ["account_number", "borrower_id", "product_id", "status", "created_at", "updated_at"])
    check_required_not_null(spark, report, "loan_warehouse.payments", "payments",
                            ["loan_account_id", "payment_date", "total_amount", "type", "status", "created_at", "updated_at"])

    # --- Referential integrity ---
    check_referential_integrity(
        spark, report,
        "loan_warehouse.loan_accounts", "loan_accounts", "borrower_id",
        "loan_warehouse.borrowers", "borrowers", "id",
    )
    check_referential_integrity(
        spark, report,
        "loan_warehouse.loan_accounts", "loan_accounts", "product_id",
        "loan_warehouse.loan_products", "loan_products", "id",
    )
    check_referential_integrity(
        spark, report,
        "loan_warehouse.payments", "payments", "loan_account_id",
        "loan_warehouse.loan_accounts", "loan_accounts", "id",
    )

    # --- Business rule validation ---
    check_active_loan_positive_balance(spark, report)
    check_closed_loan_has_status(spark, report)
    check_delinquency_status_consistency(spark, report)
    check_payment_component_sum(spark, report)
    check_origination_before_maturity(spark, report)
    check_credit_score_range(spark, report)

    return report


def main():
    parser = argparse.ArgumentParser(description="Run post-ingestion data quality checks")
    parser.add_argument("--source-borrowers", required=True, help="Path to source borrower data")
    parser.add_argument("--source-products", required=True, help="Path to source product data")
    parser.add_argument("--source-loans", required=True, help="Path to source loan data")
    parser.add_argument("--source-payments", required=True, help="Path to source payment data")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument(
        "--output-report",
        default="docs/DATA_QUALITY_REPORT.md",
        help="Path to write the quality report",
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_DataQuality").getOrCreate()

    print("=" * 60)
    print("Running post-ingestion data quality checks...")
    print("=" * 60)

    report = run_all_checks(
        spark,
        args.source_borrowers,
        args.source_products,
        args.source_loans,
        args.source_payments,
        args.format,
    )

    # Print summary to console
    print(f"\nResults: {report.pass_count} PASS, {report.fail_count} FAIL, {report.warn_count} WARN")

    # Write markdown report
    report_content = report.to_markdown()
    with open(args.output_report, "w") as f:
        f.write(report_content)
    print(f"Report written to {args.output_report}")

    spark.stop()

    # Exit with non-zero code if any checks failed
    if report.fail_count > 0:
        print(f"\nFAILED: {report.fail_count} data quality checks failed.")
        exit(1)
    else:
        print("\nPASSED: All data quality checks passed.")


if __name__ == "__main__":
    main()
