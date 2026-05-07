"""
Post-ingestion data quality validation framework.

Runs a suite of checks against the migrated Delta Lake tables and produces
a structured results list that is rendered into DATA_QUALITY_REPORT.md.

Usage (Databricks notebook or spark-submit):
    spark-submit data_quality_checks.py \
        --source-root /mnt/landing \
        --source-format csv \
        --report-path /dbfs/reports/DATA_QUALITY_REPORT.md
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("data_quality")


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------
class CheckResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class QualityCheck:
    category: str
    name: str
    result: CheckResult
    detail: str
    expected: Optional[str] = None
    actual: Optional[str] = None


@dataclass
class QualityReport:
    checks: List[QualityCheck] = field(default_factory=list)
    run_timestamp: str = ""
    elapsed_seconds: float = 0.0

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.result == CheckResult.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.result == CheckResult.FAIL)

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.result == CheckResult.WARN)


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------
def _read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(path)
    return reader.parquet(path)


def check_row_counts(
    spark: SparkSession, source_root: str, source_format: str, report: QualityReport
) -> None:
    """Reconcile row counts between source files and target Delta tables."""
    table_map = {
        "cdw_borr_mstr": ("loan_warehouse.borrowers", "Borrowers"),
        "cdw_ln_prod": ("loan_warehouse.loan_products", "Loan Products"),
        "cdw_ln_acct": ("loan_warehouse.loan_accounts", "Loan Accounts"),
        "cdw_pmt_hist": ("loan_warehouse.payments", "Payments"),
    }

    for source_dir, (target_table, label) in table_map.items():
        source_path = f"{source_root}/{source_dir}"
        try:
            source_df = _read_source(spark, source_path, source_format)
            source_count = source_df.count()
        except Exception as e:
            report.checks.append(
                QualityCheck(
                    category="Row Count",
                    name=f"{label} source readable",
                    result=CheckResult.FAIL,
                    detail=f"Could not read source at {source_path}: {e}",
                )
            )
            continue

        try:
            target_df = spark.read.table(target_table)
            target_count = target_df.count()
        except Exception as e:
            report.checks.append(
                QualityCheck(
                    category="Row Count",
                    name=f"{label} target readable",
                    result=CheckResult.FAIL,
                    detail=f"Could not read target table {target_table}: {e}",
                )
            )
            continue

        if source_count == target_count:
            report.checks.append(
                QualityCheck(
                    category="Row Count",
                    name=f"{label} row count match",
                    result=CheckResult.PASS,
                    detail=f"Source and target both have {source_count} rows.",
                    expected=str(source_count),
                    actual=str(target_count),
                )
            )
        else:
            diff = source_count - target_count
            report.checks.append(
                QualityCheck(
                    category="Row Count",
                    name=f"{label} row count match",
                    result=CheckResult.FAIL,
                    detail=(
                        f"Row count mismatch: source={source_count}, "
                        f"target={target_count} (delta={diff}). "
                        "Check quarantine tables for dropped records."
                    ),
                    expected=str(source_count),
                    actual=str(target_count),
                )
            )


def check_null_required_fields(spark: SparkSession, report: QualityReport) -> None:
    """Verify that required (NOT NULL) columns have no nulls in the target."""
    required_columns = {
        "loan_warehouse.borrowers": [
            ("external_id", "Borrower external_id"),
            ("first_name", "Borrower first_name"),
            ("last_name", "Borrower last_name"),
        ],
        "loan_warehouse.loan_products": [
            ("code", "Product code"),
            ("name", "Product name"),
            ("type", "Product type"),
            ("term_months", "Product term_months"),
            ("rate_type", "Product rate_type"),
        ],
        "loan_warehouse.loan_accounts": [
            ("account_number", "Loan account_number"),
            ("borrower_id", "Loan borrower_id"),
            ("product_id", "Loan product_id"),
            ("original_amount", "Loan original_amount"),
            ("current_balance", "Loan current_balance"),
            ("interest_rate", "Loan interest_rate"),
            ("term_months", "Loan term_months"),
            ("monthly_payment", "Loan monthly_payment"),
            ("origination_date", "Loan origination_date"),
            ("maturity_date", "Loan maturity_date"),
        ],
        "loan_warehouse.payments": [
            ("legacy_sequence_nbr", "Payment legacy_sequence_nbr"),
            ("loan_account_id", "Payment loan_account_id"),
            ("payment_date", "Payment payment_date"),
            ("total_amount", "Payment total_amount"),
            ("type", "Payment type"),
            ("status", "Payment status"),
        ],
    }

    for table, columns in required_columns.items():
        try:
            df = spark.read.table(table)
        except Exception as e:
            report.checks.append(
                QualityCheck(
                    category="Null Check",
                    name=f"{table} readable",
                    result=CheckResult.FAIL,
                    detail=f"Could not read {table}: {e}",
                )
            )
            continue

        for col_name, label in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            if null_count == 0:
                report.checks.append(
                    QualityCheck(
                        category="Null Check",
                        name=f"{label} NOT NULL",
                        result=CheckResult.PASS,
                        detail=f"No nulls found in {table}.{col_name}.",
                    )
                )
            else:
                report.checks.append(
                    QualityCheck(
                        category="Null Check",
                        name=f"{label} NOT NULL",
                        result=CheckResult.FAIL,
                        detail=f"{null_count} null(s) in {table}.{col_name}.",
                        expected="0",
                        actual=str(null_count),
                    )
                )


def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Verify FK relationships between loan_accounts->borrowers, loan_accounts->loan_products, payments->loan_accounts."""
    fk_checks = [
        (
            "loan_warehouse.loan_accounts",
            "borrower_id",
            "loan_warehouse.borrowers",
            "borrower_id",
            "Loan -> Borrower FK",
        ),
        (
            "loan_warehouse.loan_accounts",
            "product_id",
            "loan_warehouse.loan_products",
            "product_id",
            "Loan -> Product FK",
        ),
        (
            "loan_warehouse.payments",
            "loan_account_id",
            "loan_warehouse.loan_accounts",
            "loan_account_id",
            "Payment -> Loan FK",
        ),
    ]

    for child_table, child_col, parent_table, parent_col, label in fk_checks:
        try:
            child_df = spark.read.table(child_table)
            parent_df = spark.read.table(parent_table)
        except Exception as e:
            report.checks.append(
                QualityCheck(
                    category="Referential Integrity",
                    name=label,
                    result=CheckResult.FAIL,
                    detail=f"Could not read tables for check: {e}",
                )
            )
            continue

        child_ids = child_df.select(F.col(child_col).alias("id")).distinct()
        parent_ids = parent_df.select(F.col(parent_col).alias("id")).distinct()

        orphans = child_ids.join(parent_ids, "id", "left_anti")
        orphan_count = orphans.count()

        if orphan_count == 0:
            report.checks.append(
                QualityCheck(
                    category="Referential Integrity",
                    name=label,
                    result=CheckResult.PASS,
                    detail=f"All {child_table}.{child_col} values exist in {parent_table}.{parent_col}.",
                )
            )
        else:
            report.checks.append(
                QualityCheck(
                    category="Referential Integrity",
                    name=label,
                    result=CheckResult.FAIL,
                    detail=(
                        f"{orphan_count} orphan(s) in {child_table}.{child_col} "
                        f"with no match in {parent_table}.{parent_col}."
                    ),
                    expected="0",
                    actual=str(orphan_count),
                )
            )


def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules on the migrated data."""

    # ---- Loan balance > 0 for active loans ----
    try:
        loans = spark.read.table("loan_warehouse.loan_accounts")

        active_negative = loans.filter(
            (F.col("status") == "Active") & (F.col("current_balance") <= 0)
        ).count()

        if active_negative == 0:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Active loans have positive balance",
                    result=CheckResult.PASS,
                    detail="All active loans have current_balance > 0.",
                )
            )
        else:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Active loans have positive balance",
                    result=CheckResult.FAIL,
                    detail=f"{active_negative} active loan(s) have current_balance <= 0.",
                    expected="0",
                    actual=str(active_negative),
                )
            )

        # ---- Closed loans must have maturity_date <= today or status rationale ----
        # (Relaxed: we check that closed loans exist and have a maturity_date set)
        closed_no_maturity = loans.filter(
            (F.col("status") == "Closed") & F.col("maturity_date").isNull()
        ).count()

        if closed_no_maturity == 0:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Closed loans have maturity_date",
                    result=CheckResult.PASS,
                    detail="All closed loans have a maturity_date set.",
                )
            )
        else:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Closed loans have maturity_date",
                    result=CheckResult.FAIL,
                    detail=f"{closed_no_maturity} closed loan(s) missing maturity_date.",
                    expected="0",
                    actual=str(closed_no_maturity),
                )
            )

        # ---- LTV percent should be between 0 and 200 ----
        bad_ltv = loans.filter(
            F.col("ltv_percent").isNotNull()
            & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
        ).count()

        if bad_ltv == 0:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="LTV percent in valid range (0-200)",
                    result=CheckResult.PASS,
                    detail="All non-null ltv_percent values are between 0 and 200.",
                )
            )
        else:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="LTV percent in valid range (0-200)",
                    result=CheckResult.WARN,
                    detail=f"{bad_ltv} loan(s) have ltv_percent outside 0-200 range.",
                    expected="0",
                    actual=str(bad_ltv),
                )
            )

        # ---- Origination date before maturity date ----
        bad_dates = loans.filter(
            F.col("origination_date").isNotNull()
            & F.col("maturity_date").isNotNull()
            & (F.col("origination_date") >= F.col("maturity_date"))
        ).count()

        if bad_dates == 0:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Origination before maturity date",
                    result=CheckResult.PASS,
                    detail="All loans have origination_date < maturity_date.",
                )
            )
        else:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Origination before maturity date",
                    result=CheckResult.FAIL,
                    detail=f"{bad_dates} loan(s) have origination_date >= maturity_date.",
                    expected="0",
                    actual=str(bad_dates),
                )
            )

    except Exception as e:
        report.checks.append(
            QualityCheck(
                category="Business Rule",
                name="Loan table readable",
                result=CheckResult.FAIL,
                detail=f"Could not read loan_accounts for business rules: {e}",
            )
        )

    # ---- Payment amounts should be positive for posted payments ----
    try:
        payments = spark.read.table("loan_warehouse.payments")

        negative_posted = payments.filter(
            (F.col("status") == "Posted") & (F.col("total_amount") <= 0)
        ).count()

        if negative_posted == 0:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Posted payments have positive amount",
                    result=CheckResult.PASS,
                    detail="All posted payments have total_amount > 0.",
                )
            )
        else:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Posted payments have positive amount",
                    result=CheckResult.FAIL,
                    detail=f"{negative_posted} posted payment(s) have total_amount <= 0.",
                    expected="0",
                    actual=str(negative_posted),
                )
            )

        # ---- Payment component sum check ----
        component_mismatch = payments.filter(
            F.col("principal_amount").isNotNull()
            & F.col("interest_amount").isNotNull()
        ).withColumn(
            "_component_sum",
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0)),
        ).filter(
            F.abs(F.col("total_amount") - F.col("_component_sum")) > 0.01
        ).count()

        if component_mismatch == 0:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Payment components sum to total",
                    result=CheckResult.PASS,
                    detail="principal + interest + escrow + late_fee == total_amount (within 0.01) for all payments.",
                )
            )
        else:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Payment components sum to total",
                    result=CheckResult.WARN,
                    detail=(
                        f"{component_mismatch} payment(s) where component sum "
                        "differs from total_amount by more than $0.01."
                    ),
                    expected="0",
                    actual=str(component_mismatch),
                )
            )

    except Exception as e:
        report.checks.append(
            QualityCheck(
                category="Business Rule",
                name="Payment table readable",
                result=CheckResult.FAIL,
                detail=f"Could not read payments for business rules: {e}",
            )
        )

    # ---- Borrower credit score range ----
    try:
        borrowers = spark.read.table("loan_warehouse.borrowers")
        bad_credit = borrowers.filter(
            F.col("credit_score").isNotNull()
            & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()

        if bad_credit == 0:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Credit scores in valid range (300-850)",
                    result=CheckResult.PASS,
                    detail="All non-null credit scores are between 300 and 850.",
                )
            )
        else:
            report.checks.append(
                QualityCheck(
                    category="Business Rule",
                    name="Credit scores in valid range (300-850)",
                    result=CheckResult.WARN,
                    detail=f"{bad_credit} borrower(s) have credit_score outside 300-850.",
                    expected="0",
                    actual=str(bad_credit),
                )
            )
    except Exception as e:
        report.checks.append(
            QualityCheck(
                category="Business Rule",
                name="Borrower table readable",
                result=CheckResult.FAIL,
                detail=f"Could not read borrowers for business rules: {e}",
            )
        )


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
def render_report(report: QualityReport) -> str:
    """Render the quality report as Markdown."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run timestamp:** {report.run_timestamp}",
        f"**Duration:** {report.elapsed_seconds:.1f}s",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total checks | {report.total} |",
        f"| Passed | {report.passed} |",
        f"| Failed | {report.failed} |",
        f"| Warnings | {report.warnings} |",
        "",
    ]

    # Group by category
    categories = {}
    for check in report.checks:
        categories.setdefault(check.category, []).append(check)

    for category, checks in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Check | Result | Detail | Expected | Actual |")
        lines.append("|-------|--------|--------|----------|--------|")
        for c in checks:
            icon = {"PASS": "PASS", "FAIL": "**FAIL**", "WARN": "WARN"}[c.result.value]
            expected = c.expected or "-"
            actual = c.actual or "-"
            lines.append(f"| {c.name} | {icon} | {c.detail} | {expected} | {actual} |")
        lines.append("")

    # Overall verdict
    if report.failed == 0:
        lines.append("## Verdict: ALL CHECKS PASSED")
    else:
        lines.append(f"## Verdict: {report.failed} CHECK(S) FAILED")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_all_checks(
    spark: SparkSession, source_root: str, source_format: str
) -> QualityReport:
    """Execute all quality checks and return the report."""
    from datetime import datetime, timezone

    report = QualityReport()
    report.run_timestamp = datetime.now(timezone.utc).isoformat()
    start = time.time()

    logger.info("Running row count reconciliation...")
    check_row_counts(spark, source_root, source_format, report)

    logger.info("Running null checks on required fields...")
    check_null_required_fields(spark, report)

    logger.info("Running referential integrity checks...")
    check_referential_integrity(spark, report)

    logger.info("Running business rule validations...")
    check_business_rules(spark, report)

    report.elapsed_seconds = time.time() - start
    logger.info(
        "Quality checks complete: %d passed, %d failed, %d warnings (%.1fs)",
        report.passed,
        report.failed,
        report.warnings,
        report.elapsed_seconds,
    )
    return report


def main() -> None:
    from argparse import ArgumentParser

    parser = ArgumentParser(description="Run post-ingestion data quality checks")
    parser.add_argument(
        "--source-root",
        required=True,
        help="Root path to source landing directory",
    )
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument(
        "--report-path",
        default="/dbfs/reports/DATA_QUALITY_REPORT.md",
        help="Output path for the quality report",
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName("DataQualityChecks").getOrCreate()
    report = run_all_checks(spark, args.source_root, args.source_format)
    markdown = render_report(report)

    # Write report
    with open(args.report_path, "w") as f:
        f.write(markdown)
    logger.info("Report written to %s", args.report_path)

    # Print to stdout as well
    print(markdown)

    if report.failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
