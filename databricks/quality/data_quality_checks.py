"""
Data Quality Framework for CDW Legacy-to-Modern Migration.

Runs post-ingestion validation checks against the modern Delta Lake tables
and generates a DATA_QUALITY_REPORT.md summarising pass/fail results.

Check categories:
  1. Row-count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts <-> borrowers, loan_products, payments
  4. Business-rule validation (balance > 0 for active loans, closed date required, etc.)
"""

from __future__ import annotations

import datetime
import textwrap
from dataclasses import dataclass, field
from typing import Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_COUNTS = {
    "CDW_BORR_MSTR": "dbfs:/mnt/legacy-export/CDW_BORR_MSTR",
    "CDW_LN_PROD": "dbfs:/mnt/legacy-export/CDW_LN_PROD",
    "CDW_LN_ACCT": "dbfs:/mnt/legacy-export/CDW_LN_ACCT",
    "CDW_PMT_HIST": "dbfs:/mnt/legacy-export/CDW_PMT_HIST",
}
SOURCE_FORMAT = "csv"

TARGET_TABLES = {
    "CDW_BORR_MSTR": "loan_warehouse.borrowers",
    "CDW_LN_PROD": "loan_warehouse.loan_products",
    "CDW_LN_ACCT": "loan_warehouse.loan_accounts",
    "CDW_PMT_HIST": "loan_warehouse.payments",
}

REPORT_PATH = "dbfs:/mnt/migration-reports/DATA_QUALITY_REPORT.md"
REPORT_LOCAL_PATH = "/dbfs/mnt/migration-reports/DATA_QUALITY_REPORT.md"

# ---------------------------------------------------------------------------
# Spark session
# ---------------------------------------------------------------------------
spark = SparkSession.builder.appName("data_quality_checks").getOrCreate()

_LOG_TAG = "[data_quality]"


def _log(msg: str) -> None:
    print(f"{_LOG_TAG} {msg}")


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str
    table: str
    check_name: str
    passed: bool
    detail: str
    severity: str = "ERROR"  # ERROR | WARNING


@dataclass
class QualityReport:
    results: list[CheckResult] = field(default_factory=list)
    run_ts: str = field(
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

    @property
    def overall_pass(self) -> bool:
        return all(r.passed for r in self.results if r.severity == "ERROR")


# ---------------------------------------------------------------------------
# 1. Row-count reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(report: QualityReport) -> None:
    _log("Running row-count reconciliation checks...")
    for source_name, source_path in SOURCE_COUNTS.items():
        target_table = TARGET_TABLES[source_name]
        try:
            src_reader = spark.read.format(SOURCE_FORMAT)
            if SOURCE_FORMAT == "csv":
                src_reader = src_reader.option("header", "true")
            src_count = src_reader.load(source_path).count()
            tgt_count = spark.table(target_table).count()

            passed = src_count == tgt_count
            detail = (
                f"Source ({source_name}): {src_count} rows, "
                f"Target ({target_table}): {tgt_count} rows"
            )
            if not passed:
                detail += f" — DELTA: {abs(src_count - tgt_count)} rows"

            report.add(CheckResult(
                category="Row Count",
                table=target_table,
                check_name=f"row_count_{source_name}",
                passed=passed,
                detail=detail,
            ))
        except Exception as exc:
            report.add(CheckResult(
                category="Row Count",
                table=target_table,
                check_name=f"row_count_{source_name}",
                passed=False,
                detail=f"Error reading source or target: {exc}",
            ))


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[str, list[str]] = {
    "loan_warehouse.borrowers": ["external_id", "first_name", "last_name"],
    "loan_warehouse.loan_products": ["code", "name", "type"],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "status",
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount", "status",
    ],
}


def check_nulls(report: QualityReport) -> None:
    _log("Running null checks on required fields...")
    for table, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table)
            for col_name in columns:
                null_count = df.filter(F.col(col_name).isNull()).count()
                passed = null_count == 0
                detail = f"{col_name}: {null_count} NULL values found"
                report.add(CheckResult(
                    category="Null Check",
                    table=table,
                    check_name=f"null_{table.split('.')[-1]}_{col_name}",
                    passed=passed,
                    detail=detail,
                ))
        except Exception as exc:
            report.add(CheckResult(
                category="Null Check",
                table=table,
                check_name=f"null_{table.split('.')[-1]}_read",
                passed=False,
                detail=f"Error reading table: {exc}",
            ))


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(report: QualityReport) -> None:
    _log("Running referential integrity checks...")

    # loan_accounts.borrower_id -> borrowers.id
    _check_fk(
        report,
        child_table="loan_warehouse.loan_accounts",
        child_col="borrower_id",
        parent_table="loan_warehouse.borrowers",
        parent_col="id",
    )

    # loan_accounts.product_id -> loan_products.id
    _check_fk(
        report,
        child_table="loan_warehouse.loan_accounts",
        child_col="product_id",
        parent_table="loan_warehouse.loan_products",
        parent_col="id",
    )

    # payments.loan_account_id -> loan_accounts.id
    _check_fk(
        report,
        child_table="loan_warehouse.payments",
        child_col="loan_account_id",
        parent_table="loan_warehouse.loan_accounts",
        parent_col="id",
    )


def _check_fk(
    report: QualityReport,
    child_table: str,
    child_col: str,
    parent_table: str,
    parent_col: str,
) -> None:
    try:
        child_df = spark.table(child_table)
        parent_df = spark.table(parent_table)

        orphans = (
            child_df.select(F.col(child_col).alias("_fk"))
            .join(
                parent_df.select(F.col(parent_col).alias("_pk")),
                F.col("_fk") == F.col("_pk"),
                "left_anti",
            )
            .filter(F.col("_fk").isNotNull())
            .count()
        )

        passed = orphans == 0
        detail = (
            f"{child_table}.{child_col} -> {parent_table}.{parent_col}: "
            f"{orphans} orphan rows"
        )
        report.add(CheckResult(
            category="Referential Integrity",
            table=child_table,
            check_name=f"fk_{child_table.split('.')[-1]}_{child_col}",
            passed=passed,
            detail=detail,
        ))
    except Exception as exc:
        report.add(CheckResult(
            category="Referential Integrity",
            table=child_table,
            check_name=f"fk_{child_table.split('.')[-1]}_{child_col}",
            passed=False,
            detail=f"Error: {exc}",
        ))


# ---------------------------------------------------------------------------
# 4. Business-rule validation
# ---------------------------------------------------------------------------

def check_business_rules(report: QualityReport) -> None:
    _log("Running business rule validations...")

    # 4a. Active loans must have current_balance > 0
    _check_active_loan_balance(report)

    # 4b. Closed loans must have a maturity_date (proxy for closed date)
    _check_closed_loan_date(report)

    # 4c. Payment total should equal sum of components (principal + interest + escrow + late_fee)
    _check_payment_component_sum(report)

    # 4d. Delinquency days must be >= 0
    _check_delinquency_non_negative(report)

    # 4e. Interest rate must be > 0
    _check_interest_rate_positive(report)

    # 4f. origination_date must be before maturity_date
    _check_origination_before_maturity(report)


def _check_active_loan_balance(report: QualityReport) -> None:
    try:
        df = spark.table("loan_warehouse.loan_accounts")
        violations = df.filter(
            (F.col("status") == "Active") & (F.col("current_balance") <= 0)
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="active_loan_positive_balance",
            passed=violations == 0,
            detail=f"Active loans with balance <= 0: {violations}",
        ))
    except Exception as exc:
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="active_loan_positive_balance",
            passed=False,
            detail=f"Error: {exc}",
        ))


def _check_closed_loan_date(report: QualityReport) -> None:
    try:
        df = spark.table("loan_warehouse.loan_accounts")
        violations = df.filter(
            (F.col("status") == "Closed") & F.col("maturity_date").isNull()
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="closed_loan_has_maturity_date",
            passed=violations == 0,
            detail=f"Closed loans missing maturity_date: {violations}",
        ))
    except Exception as exc:
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="closed_loan_has_maturity_date",
            passed=False,
            detail=f"Error: {exc}",
        ))


def _check_payment_component_sum(report: QualityReport) -> None:
    try:
        df = spark.table("loan_warehouse.payments")
        tolerance = 0.01  # allow 1 cent rounding
        component_sum = (
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0))
        )
        violations = df.filter(
            F.abs(F.col("total_amount") - component_sum) > tolerance
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.payments",
            check_name="payment_components_sum_to_total",
            passed=violations == 0,
            detail=f"Payments where components != total (tolerance {tolerance}): {violations}",
            severity="WARNING",
        ))
    except Exception as exc:
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.payments",
            check_name="payment_components_sum_to_total",
            passed=False,
            detail=f"Error: {exc}",
            severity="WARNING",
        ))


def _check_delinquency_non_negative(report: QualityReport) -> None:
    try:
        df = spark.table("loan_warehouse.loan_accounts")
        violations = df.filter(F.col("delinquency_days") < 0).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="delinquency_non_negative",
            passed=violations == 0,
            detail=f"Loans with negative delinquency_days: {violations}",
        ))
    except Exception as exc:
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="delinquency_non_negative",
            passed=False,
            detail=f"Error: {exc}",
        ))


def _check_interest_rate_positive(report: QualityReport) -> None:
    try:
        df = spark.table("loan_warehouse.loan_accounts")
        violations = df.filter(
            F.col("interest_rate").isNotNull() & (F.col("interest_rate") <= 0)
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="interest_rate_positive",
            passed=violations == 0,
            detail=f"Loans with interest_rate <= 0: {violations}",
        ))
    except Exception as exc:
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="interest_rate_positive",
            passed=False,
            detail=f"Error: {exc}",
        ))


def _check_origination_before_maturity(report: QualityReport) -> None:
    try:
        df = spark.table("loan_warehouse.loan_accounts")
        violations = df.filter(
            F.col("origination_date").isNotNull()
            & F.col("maturity_date").isNotNull()
            & (F.col("origination_date") >= F.col("maturity_date"))
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="origination_before_maturity",
            passed=violations == 0,
            detail=f"Loans where origination_date >= maturity_date: {violations}",
        ))
    except Exception as exc:
        report.add(CheckResult(
            category="Business Rule",
            table="loan_warehouse.loan_accounts",
            check_name="origination_before_maturity",
            passed=False,
            detail=f"Error: {exc}",
        ))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(report: QualityReport, output_path: str) -> str:
    """Render the quality report as Markdown and write to DBFS."""
    lines: list[str] = []
    lines.append("# Data Quality Report")
    lines.append("")
    lines.append(f"**Run timestamp:** {report.run_ts}")
    lines.append(f"**Overall result:** {'PASS' if report.overall_pass else 'FAIL'}")
    lines.append(f"**Checks run:** {report.total}  |  "
                 f"**Passed:** {report.passed}  |  **Failed:** {report.failed}")
    lines.append("")

    # Group by category
    categories = sorted(set(r.category for r in report.results))
    for cat in categories:
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Table | Check | Result | Severity | Detail |")
        lines.append("|-------|-------|--------|----------|--------|")
        for r in report.results:
            if r.category != cat:
                continue
            status = "PASS" if r.passed else "FAIL"
            lines.append(
                f"| `{r.table}` | `{r.check_name}` | **{status}** "
                f"| {r.severity} | {r.detail} |"
            )
        lines.append("")

    md_content = "\n".join(lines)

    # Write to DBFS
    try:
        dbutils = spark._jvm.com.databricks.dbutils.DBUtilsHolder.dbutils()  # type: ignore[union-attr]
        dbutils.fs.put(output_path, md_content, True)
        _log(f"Report written to {output_path}")
    except Exception:
        _log("dbutils not available; writing report via Spark")
        rdd = spark.sparkContext.parallelize([md_content])
        rdd.saveAsTextFile(output_path + "_txt")
        _log(f"Report written to {output_path}_txt")

    return md_content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _log("=" * 60)
    _log("Starting data quality checks")
    _log("=" * 60)

    report = QualityReport()

    check_row_counts(report)
    check_nulls(report)
    check_referential_integrity(report)
    check_business_rules(report)

    md = generate_report(report, REPORT_PATH)

    _log("=" * 60)
    if report.overall_pass:
        _log("All ERROR-severity checks PASSED.")
    else:
        _log(f"QUALITY GATE FAILED: {report.failed} checks did not pass.")
    _log("=" * 60)

    # Print report to notebook output for visibility
    print(md)


if __name__ == "__main__":
    main()
