"""
Data Quality Framework for CDW-to-Delta-Lake Migration

Runs post-ingestion validation checks and generates a structured report.
Checks include:
  - Row count reconciliation (source vs. target)
  - Null checks on required fields
  - Referential integrity between loan_accounts <-> borrowers, loan_products, payments
  - Business rule validation (active loan balances, closed loan dates, etc.)

Usage:
    spark-submit --master local[*] data_quality_checks.py \
        --landing-path /mnt/landing \
        --source-format csv \
        --report-path /mnt/reports/DATA_QUALITY_REPORT.md
"""

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("cdw_migration.quality")

CATALOG = "loan_catalog"
SCHEMA = "loan_warehouse"


@dataclass
class CheckResult:
    category: str
    check_name: str
    passed: bool
    detail: str
    severity: str = "ERROR"  # ERROR, WARNING, INFO


@dataclass
class QualityReport:
    results: list[CheckResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: datetime | None = None

    def add(self, result: CheckResult):
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info("[%s] %s / %s: %s", status, result.category, result.check_name, result.detail)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession, landing_path: str, fmt: str, report: QualityReport):
    """Compare source file row counts against target Delta table row counts."""
    tables = {
        "borrowers": ("cdw_borr_mstr", f"{CATALOG}.{SCHEMA}.borrowers"),
        "loan_products": ("cdw_ln_prod", f"{CATALOG}.{SCHEMA}.loan_products"),
        "loan_accounts": ("cdw_ln_acct", f"{CATALOG}.{SCHEMA}.loan_accounts"),
        "payments": ("cdw_pmt_hist", f"{CATALOG}.{SCHEMA}.payments"),
    }

    for name, (source_file, target_table) in tables.items():
        source_path = f"{landing_path}/{source_file}.{fmt}"
        try:
            if fmt == "csv":
                source_df = spark.read.option("header", "true").csv(source_path)
            else:
                source_df = spark.read.parquet(source_path)
            source_count = source_df.count()
        except Exception as e:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"{name}_source_readable",
                passed=False,
                detail=f"Cannot read source file {source_path}: {e}",
            ))
            continue

        try:
            target_count = spark.table(target_table).count()
        except Exception as e:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"{name}_target_readable",
                passed=False,
                detail=f"Cannot read target table {target_table}: {e}",
            ))
            continue

        match = source_count == target_count
        report.add(CheckResult(
            category="Row Count",
            check_name=f"{name}_count_match",
            passed=match,
            detail=f"source={source_count}, target={target_count}",
        ))


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------

def check_nulls(spark: SparkSession, report: QualityReport):
    """Verify that NOT NULL / required columns contain no nulls."""
    required_fields = {
        f"{CATALOG}.{SCHEMA}.borrowers": [
            "external_id", "first_name", "last_name", "status",
        ],
        f"{CATALOG}.{SCHEMA}.loan_products": [
            "code", "name", "type", "term_months", "rate_type", "is_active",
        ],
        f"{CATALOG}.{SCHEMA}.loan_accounts": [
            "account_number", "borrower_id", "product_id", "original_amount",
            "current_balance", "interest_rate", "term_months", "monthly_payment",
            "origination_date", "maturity_date", "status",
        ],
        f"{CATALOG}.{SCHEMA}.payments": [
            "loan_account_id", "payment_date", "total_amount", "type", "status",
        ],
    }

    for table, columns in required_fields.items():
        try:
            df = spark.table(table)
        except Exception as e:
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table}_table_access",
                passed=False,
                detail=f"Cannot access table: {e}",
            ))
            continue

        null_exprs = [
            F.sum(F.when(F.col(c).isNull(), 1).otherwise(0)).alias(c)
            for c in columns
        ]
        null_row = df.select(null_exprs).collect()[0]

        for col_name in columns:
            null_count = null_row[col_name]
            is_ok = null_count == 0
            short_table = table.split(".")[-1]
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{short_table}.{col_name}",
                passed=is_ok,
                detail=f"null_count={null_count}",
            ))


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport):
    """Verify FK relationships between tables."""
    checks = [
        (
            "loan_accounts.borrower_id -> borrowers",
            f"{CATALOG}.{SCHEMA}.loan_accounts",
            "borrower_id",
            f"{CATALOG}.{SCHEMA}.borrowers",
            "borrower_id",
        ),
        (
            "loan_accounts.product_id -> loan_products",
            f"{CATALOG}.{SCHEMA}.loan_accounts",
            "product_id",
            f"{CATALOG}.{SCHEMA}.loan_products",
            "product_id",
        ),
        (
            "payments.loan_account_id -> loan_accounts",
            f"{CATALOG}.{SCHEMA}.payments",
            "loan_account_id",
            f"{CATALOG}.{SCHEMA}.loan_accounts",
            "loan_account_id",
        ),
    ]

    for check_name, child_table, child_col, parent_table, parent_col in checks:
        try:
            child_df = spark.table(child_table).select(F.col(child_col).alias("_child_fk")).distinct()
            parent_df = spark.table(parent_table).select(F.col(parent_col).alias("_parent_pk")).distinct()

            orphans = child_df.join(parent_df, child_df["_child_fk"] == parent_df["_parent_pk"], "left_anti")
            orphan_count = orphans.count()

            report.add(CheckResult(
                category="Referential Integrity",
                check_name=check_name,
                passed=orphan_count == 0,
                detail=f"orphan_count={orphan_count}",
            ))
        except Exception as e:
            report.add(CheckResult(
                category="Referential Integrity",
                check_name=check_name,
                passed=False,
                detail=f"Check failed: {e}",
            ))


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport):
    """Validate domain-specific business rules."""
    loans_table = f"{CATALOG}.{SCHEMA}.loan_accounts"
    payments_table = f"{CATALOG}.{SCHEMA}.payments"

    try:
        loans_df = spark.table(loans_table)
    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            check_name="loans_table_access",
            passed=False,
            detail=f"Cannot access: {e}",
        ))
        return

    # Rule 1: Active loans must have current_balance > 0
    active_zero_balance = loans_df.filter(
        (F.col("status") == "Active") & (F.col("current_balance") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="active_loans_positive_balance",
        passed=active_zero_balance == 0,
        detail=f"Active loans with balance <= 0: {active_zero_balance}",
    ))

    # Rule 2: Interest rate must be between 0 and 100
    bad_rates = loans_df.filter(
        (F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="interest_rate_range",
        passed=bad_rates == 0,
        detail=f"Loans with rate outside 0-100: {bad_rates}",
    ))

    # Rule 3: Maturity date must be after origination date
    bad_dates = loans_df.filter(
        F.col("maturity_date") <= F.col("origination_date")
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="maturity_after_origination",
        passed=bad_dates == 0,
        detail=f"Loans with maturity <= origination: {bad_dates}",
    ))

    # Rule 4: LTV percent should be between 0 and 200 (sanity bound)
    bad_ltv = loans_df.filter(
        F.col("ltv_percent").isNotNull() &
        ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="ltv_percent_range",
        passed=bad_ltv == 0,
        detail=f"Loans with LTV outside 0-200: {bad_ltv}",
        severity="WARNING",
    ))

    # Rule 5: Delinquency days must be >= 0
    bad_dlq = loans_df.filter(F.col("delinquency_days") < 0).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="delinquency_days_non_negative",
        passed=bad_dlq == 0,
        detail=f"Loans with negative delinquency days: {bad_dlq}",
    ))

    # Rule 6: Loan status must be a known value
    valid_statuses = {"Active", "Closed", "Default", "Forbearance"}
    unknown_statuses = loans_df.filter(~F.col("status").isin(valid_statuses)).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="loan_status_valid",
        passed=unknown_statuses == 0,
        detail=f"Loans with unknown status: {unknown_statuses}",
    ))

    # Rule 7: Payment total_amount should equal sum of components (within tolerance)
    try:
        payments_df = spark.table(payments_table)
        component_sum = (
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0))
        )
        tolerance = 0.01
        mismatched = payments_df.filter(
            F.abs(F.col("total_amount") - component_sum) > tolerance
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            check_name="payment_component_sum",
            passed=mismatched == 0,
            detail=f"Payments where total != components (tolerance ${tolerance}): {mismatched}",
            severity="WARNING",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            check_name="payment_component_sum",
            passed=False,
            detail=f"Check failed: {e}",
        ))

    # Rule 8: Payment status must be a known value
    try:
        payments_df = spark.table(payments_table)
        valid_pmt_statuses = {"Posted", "Reversed", "NSF", "Pending"}
        unknown_pmt = payments_df.filter(~F.col("status").isin(valid_pmt_statuses)).count()
        report.add(CheckResult(
            category="Business Rule",
            check_name="payment_status_valid",
            passed=unknown_pmt == 0,
            detail=f"Payments with unknown status: {unknown_pmt}",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            check_name="payment_status_valid",
            passed=False,
            detail=f"Check failed: {e}",
        ))


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_report_markdown(report: QualityReport) -> str:
    """Generate a Markdown summary of all quality check results."""
    report.end_time = datetime.utcnow()
    elapsed = (report.end_time - report.start_time).total_seconds()

    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {report.end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"**Duration:** {elapsed:.1f}s",
        f"**Total Checks:** {report.total}",
        f"**Passed:** {report.passed}",
        f"**Failed:** {report.failed}",
        "",
        f"**Overall Status:** {'PASS' if report.failed == 0 else 'FAIL'}",
        "",
        "---",
        "",
    ]

    # Group by category
    categories: dict[str, list[CheckResult]] = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for category, checks in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Check | Status | Severity | Detail |")
        lines.append("|-------|--------|----------|--------|")
        for c in checks:
            status_icon = "PASS" if c.passed else "FAIL"
            lines.append(f"| {c.check_name} | {status_icon} | {c.severity} | {c.detail} |")
        lines.append("")

    # Summary of failures
    failures = [r for r in report.results if not r.passed]
    if failures:
        lines.append("## Failed Checks Summary")
        lines.append("")
        for f_check in failures:
            lines.append(f"- **[{f_check.severity}]** {f_check.category} / {f_check.check_name}: {f_check.detail}")
        lines.append("")
    else:
        lines.append("## All Checks Passed")
        lines.append("")
        lines.append("No data quality issues detected.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all_checks(spark: SparkSession, landing_path: str, fmt: str) -> QualityReport:
    """Execute all quality checks and return the report."""
    report = QualityReport()

    logger.info("Running row count reconciliation checks...")
    check_row_counts(spark, landing_path, fmt, report)

    logger.info("Running null checks on required fields...")
    check_nulls(spark, report)

    logger.info("Running referential integrity checks...")
    check_referential_integrity(spark, report)

    logger.info("Running business rule validation...")
    check_business_rules(spark, report)

    return report


def main():
    parser = argparse.ArgumentParser(description="Run data quality checks on migrated Delta tables")
    parser.add_argument("--landing-path", required=True, help="Base path to source landing zone files")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"], help="Source file format")
    parser.add_argument(
        "--report-path",
        default="/mnt/reports/DATA_QUALITY_REPORT.md",
        help="Output path for the Markdown report",
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_DataQuality").getOrCreate()

    try:
        report = run_all_checks(spark, args.landing_path, args.source_format)
        markdown = generate_report_markdown(report)

        # Write report to DBFS / cloud storage
        logger.info("Writing report to %s", args.report_path)
        dbutils_available = False
        try:
            dbutils.fs.put(args.report_path, markdown, overwrite=True)  # type: ignore[name-defined]
            dbutils_available = True
        except NameError:
            pass

        if not dbutils_available:
            with open(args.report_path, "w") as f:
                f.write(markdown)

        logger.info("Report written successfully.")

        # Print summary
        print("\n" + "=" * 60)
        print(f"DATA QUALITY REPORT: {'PASS' if report.failed == 0 else 'FAIL'}")
        print(f"  Total: {report.total}  Passed: {report.passed}  Failed: {report.failed}")
        print("=" * 60 + "\n")

        if report.failed > 0:
            logger.warning("Data quality checks FAILED. Review the report at %s", args.report_path)
            sys.exit(1)

    except Exception:
        logger.exception("Data quality check execution failed")
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
