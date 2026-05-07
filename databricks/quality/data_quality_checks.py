"""
Data Quality Framework for Legacy-to-Modern Loan Data Migration.

Runs post-ingestion validation checks across all four target tables and
generates a DATA_QUALITY_REPORT.md summarizing pass/fail results.

Check categories:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts <-> borrowers, loan_products, payments
  4. Business rule validation (domain-specific invariants)

Usage:
    spark-submit data_quality_checks.py
    or: %run ./data_quality_checks
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CATALOG = "loan_migration"
SCHEMA = "loan_warehouse"

BORROWER_TABLE = f"{CATALOG}.{SCHEMA}.borrowers"
PRODUCT_TABLE = f"{CATALOG}.{SCHEMA}.loan_products"
LOAN_TABLE = f"{CATALOG}.{SCHEMA}.loan_accounts"
PAYMENT_TABLE = f"{CATALOG}.{SCHEMA}.payments"

# Legacy source paths for row count reconciliation
LEGACY_SOURCES = {
    "borrowers": "dbfs:/mnt/legacy-exports/CDW_BORR_MSTR/",
    "loan_products": "dbfs:/mnt/legacy-exports/CDW_LN_PROD/",
    "loan_accounts": "dbfs:/mnt/legacy-exports/CDW_LN_ACCT/",
    "payments": "dbfs:/mnt/legacy-exports/CDW_PMT_HIST/",
}

QUARANTINE_PATHS = {
    "borrowers": "dbfs:/mnt/migration-quarantine/borrowers/",
    "loan_products": "dbfs:/mnt/migration-quarantine/loan_products/",
    "loan_accounts": "dbfs:/mnt/migration-quarantine/loan_accounts/",
    "payments": "dbfs:/mnt/migration-quarantine/payments/",
}

REPORT_OUTPUT_PATH = "databricks/quality/DATA_QUALITY_REPORT.md"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str
    check_name: str
    passed: bool
    detail: str
    severity: str = "ERROR"  # ERROR, WARNING, INFO


@dataclass
class QualityReport:
    timestamp: str = ""
    results: List[CheckResult] = field(default_factory=list)
    total_passed: int = 0
    total_failed: int = 0
    total_warnings: int = 0

    def add(self, result: CheckResult) -> None:
        self.results.append(result)
        if result.passed:
            self.total_passed += 1
        elif result.severity == "WARNING":
            self.total_warnings += 1
        else:
            self.total_failed += 1


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession, report: QualityReport) -> None:
    """Verify source row count == target row count + quarantined count."""

    tables = {
        "borrowers": BORROWER_TABLE,
        "loan_products": PRODUCT_TABLE,
        "loan_accounts": LOAN_TABLE,
        "payments": PAYMENT_TABLE,
    }

    for name, target_table in tables.items():
        source_path = LEGACY_SOURCES.get(name)
        quarantine_path = QUARANTINE_PATHS.get(name)

        try:
            target_count = spark.table(target_table).count()
        except Exception as e:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"{name}: target table readable",
                passed=False,
                detail=f"Cannot read target table {target_table}: {e}",
            ))
            continue

        # Try to read source for reconciliation
        source_count = None
        try:
            source_df = spark.read.format("csv").option("header", "true").load(source_path)
            source_count = source_df.count()
        except Exception:
            pass  # source may not be available in all environments

        quarantine_count = 0
        try:
            quarantine_df = spark.read.format("delta").load(quarantine_path)
            quarantine_count = quarantine_df.count()
        except Exception:
            pass  # no quarantine data is normal

        if source_count is not None:
            expected = source_count
            actual = target_count + quarantine_count
            passed = expected == actual
            report.add(CheckResult(
                category="Row Count",
                check_name=f"{name}: source vs. target+quarantine",
                passed=passed,
                detail=(
                    f"source={source_count}, target={target_count}, "
                    f"quarantined={quarantine_count}, "
                    f"{'MATCH' if passed else 'MISMATCH'}"
                ),
            ))
        else:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"{name}: target row count",
                passed=target_count > 0,
                detail=f"target={target_count} (source not available for reconciliation)",
                severity="WARNING",
            ))


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    BORROWER_TABLE: ["external_id", "first_name", "last_name", "status"],
    PRODUCT_TABLE: ["code", "name", "type", "term_months", "rate_type"],
    LOAN_TABLE: [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "status",
    ],
    PAYMENT_TABLE: [
        "loan_account_id", "payment_date", "total_amount", "type", "status",
    ],
}


def check_nulls(spark: SparkSession, report: QualityReport) -> None:
    """Verify required fields have no null values in target tables."""
    for table, columns in REQUIRED_FIELDS.items():
        table_short = table.split(".")[-1]
        try:
            df = spark.table(table)
        except Exception as e:
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table_short}: table readable",
                passed=False,
                detail=f"Cannot read {table}: {e}",
            ))
            continue

        total_rows = df.count()
        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            passed = null_count == 0
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table_short}.{col_name} NOT NULL",
                passed=passed,
                detail=(
                    f"{null_count}/{total_rows} nulls"
                    if not passed
                    else f"0 nulls in {total_rows} rows"
                ),
            ))


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Verify FK relationships between tables."""

    # loan_accounts.borrower_id -> borrowers.borrower_id
    try:
        loans = spark.table(LOAN_TABLE)
        borrowers = spark.table(BORROWER_TABLE)

        orphan_borrower = loans.join(
            borrowers,
            loans["borrower_id"] == borrowers["borrower_id"],
            "left_anti"
        ).count()

        report.add(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.borrower_id -> borrowers",
            passed=orphan_borrower == 0,
            detail=f"{orphan_borrower} orphaned loan records (missing borrower)",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.borrower_id -> borrowers",
            passed=False,
            detail=f"Check failed: {e}",
        ))

    # loan_accounts.product_id -> loan_products.product_id
    try:
        products = spark.table(PRODUCT_TABLE)

        orphan_product = loans.join(
            products,
            loans["product_id"] == products["product_id"],
            "left_anti"
        ).count()

        report.add(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.product_id -> loan_products",
            passed=orphan_product == 0,
            detail=f"{orphan_product} orphaned loan records (missing product)",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.product_id -> loan_products",
            passed=False,
            detail=f"Check failed: {e}",
        ))

    # payments.loan_account_id -> loan_accounts.loan_account_id
    try:
        payments = spark.table(PAYMENT_TABLE)

        orphan_payment = payments.join(
            loans,
            payments["loan_account_id"] == loans["loan_account_id"],
            "left_anti"
        ).count()

        report.add(CheckResult(
            category="Referential Integrity",
            check_name="payments.loan_account_id -> loan_accounts",
            passed=orphan_payment == 0,
            detail=f"{orphan_payment} orphaned payment records (missing loan account)",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name="payments.loan_account_id -> loan_accounts",
            passed=False,
            detail=f"Check failed: {e}",
        ))


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules."""

    try:
        loans = spark.table(LOAN_TABLE)
    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            check_name="loan_accounts readable",
            passed=False,
            detail=f"Cannot read loan_accounts: {e}",
        ))
        return

    # Rule 1: Active loans must have current_balance > 0
    active_zero_balance = loans.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans have balance > 0",
        passed=active_zero_balance == 0,
        detail=f"{active_zero_balance} active loans with balance <= 0",
    ))

    # Rule 2: Closed loans should have maturity_date <= today or explicit closure
    # (informational — some closed loans may be early payoffs)
    closed_future_maturity = loans.filter(
        (F.col("status") == "CLOSED")
        & (F.col("maturity_date") > F.current_date())
    ).count()
    closed_total = loans.filter(F.col("status") == "CLOSED").count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Closed loans maturity date check",
        passed=True,  # informational
        detail=(
            f"{closed_future_maturity}/{closed_total} closed loans have future "
            f"maturity dates (may be early payoffs)"
        ),
        severity="INFO",
    ))

    # Rule 3: Interest rate should be between 0 and 25 (reasonable range)
    bad_rate = loans.filter(
        (F.col("interest_rate") < 0) | (F.col("interest_rate") > 25)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Interest rate in valid range (0-25%)",
        passed=bad_rate == 0,
        detail=f"{bad_rate} loans with interest rate outside 0-25%",
    ))

    # Rule 4: LTV percent should be between 0 and 200
    bad_ltv = loans.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="LTV percent in valid range (0-200%)",
        passed=bad_ltv == 0,
        detail=f"{bad_ltv} loans with LTV outside 0-200%",
    ))

    # Rule 5: Origination date should be before maturity date
    bad_dates = loans.filter(
        F.col("origination_date") >= F.col("maturity_date")
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Origination date < maturity date",
        passed=bad_dates == 0,
        detail=f"{bad_dates} loans where origination >= maturity date",
    ))

    # Rule 6: Delinquency days >= 0
    bad_dlq = loans.filter(F.col("delinquency_days") < 0).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Delinquency days >= 0",
        passed=bad_dlq == 0,
        detail=f"{bad_dlq} loans with negative delinquency days",
    ))

    # Rule 7: Defaulted loans should have delinquency_days > 0
    default_no_dlq = loans.filter(
        (F.col("status") == "DEFAULT") & (F.col("delinquency_days") == 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Defaulted loans have delinquency > 0",
        passed=default_no_dlq == 0,
        detail=f"{default_no_dlq} defaulted loans with 0 delinquency days",
        severity="WARNING",
    ))

    # Rule 8: Status values are in expected set
    valid_statuses = ["ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE"]
    bad_status = loans.filter(~F.col("status").isin(valid_statuses)).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Loan status in valid set",
        passed=bad_status == 0,
        detail=(
            f"{bad_status} loans with unexpected status "
            f"(expected: {', '.join(valid_statuses)})"
        ),
    ))

    # Payment business rules
    try:
        payments = spark.table(PAYMENT_TABLE)
    except Exception:
        return

    # Rule 9: Payment total_amount > 0
    bad_pmt_amt = payments.filter(F.col("total_amount") <= 0).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Payment amounts > 0",
        passed=bad_pmt_amt == 0,
        detail=f"{bad_pmt_amt} payments with amount <= 0",
    ))

    # Rule 10: Payment type in valid set
    valid_pmt_types = ["REGULAR", "EXTRA", "PARTIAL", "PREPAYMENT"]
    bad_pmt_type = payments.filter(~F.col("type").isin(valid_pmt_types)).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Payment type in valid set",
        passed=bad_pmt_type == 0,
        detail=(
            f"{bad_pmt_type} payments with unexpected type "
            f"(expected: {', '.join(valid_pmt_types)})"
        ),
    ))

    # Rule 11: Payment status in valid set
    valid_pmt_statuses = ["POSTED", "REVERSED", "NSF", "PENDING"]
    bad_pmt_status = payments.filter(~F.col("status").isin(valid_pmt_statuses)).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Payment status in valid set",
        passed=bad_pmt_status == 0,
        detail=(
            f"{bad_pmt_status} payments with unexpected status "
            f"(expected: {', '.join(valid_pmt_statuses)})"
        ),
    ))

    # Borrower business rules
    try:
        borrowers = spark.table(BORROWER_TABLE)
    except Exception:
        return

    # Rule 12: Credit score in valid range (300-850)
    bad_credit = borrowers.filter(
        F.col("credit_score").isNotNull()
        & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Credit score in valid range (300-850)",
        passed=bad_credit == 0,
        detail=f"{bad_credit} borrowers with credit score outside 300-850",
    ))

    # Rule 13: Annual income >= 0
    bad_income = borrowers.filter(
        F.col("annual_income").isNotNull() & (F.col("annual_income") < 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Annual income >= 0",
        passed=bad_income == 0,
        detail=f"{bad_income} borrowers with negative annual income",
    ))


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_report_markdown(report: QualityReport) -> str:
    """Generate a Markdown report from check results."""
    lines = []
    lines.append("# Data Quality Report")
    lines.append("")
    lines.append(f"**Generated:** {report.timestamp}")
    lines.append(f"**Pipeline:** Legacy CDW → Modern Delta Lake Migration")
    lines.append("")

    # Summary
    total = report.total_passed + report.total_failed + report.total_warnings
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Checks | {total} |")
    lines.append(f"| Passed | {report.total_passed} |")
    lines.append(f"| Failed | {report.total_failed} |")
    lines.append(f"| Warnings | {report.total_warnings} |")
    lines.append("")

    if report.total_failed > 0:
        lines.append("> **STATUS: FAILED** — Review failed checks below before "
                      "promoting data to production.")
    elif report.total_warnings > 0:
        lines.append("> **STATUS: PASSED WITH WARNINGS** — Review warnings below.")
    else:
        lines.append("> **STATUS: PASSED** — All checks passed successfully.")
    lines.append("")

    # Results by category
    categories = sorted(set(r.category for r in report.results))
    for category in categories:
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Check | Result | Severity | Detail |")
        lines.append("|-------|--------|----------|--------|")
        for r in report.results:
            if r.category != category:
                continue
            status = "PASS" if r.passed else "FAIL"
            icon = "✅" if r.passed else ("⚠️" if r.severity == "WARNING" else "❌")
            lines.append(
                f"| {r.check_name} | {icon} {status} | {r.severity} | {r.detail} |"
            )
        lines.append("")

    # Failed checks summary
    failed = [r for r in report.results if not r.passed and r.severity == "ERROR"]
    if failed:
        lines.append("## Failed Checks — Action Required")
        lines.append("")
        for r in failed:
            lines.append(f"- **{r.check_name}**: {r.detail}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_data_quality_checks(spark: SparkSession,
                            output_path: Optional[str] = None) -> QualityReport:
    """Run all data quality checks and generate report."""
    report = QualityReport(timestamp=datetime.utcnow().isoformat() + "Z")

    print("=" * 60)
    print("DATA QUALITY CHECKS")
    print("=" * 60)

    print("\n--- Row Count Reconciliation ---")
    check_row_counts(spark, report)

    print("\n--- Null Checks ---")
    check_nulls(spark, report)

    print("\n--- Referential Integrity ---")
    check_referential_integrity(spark, report)

    print("\n--- Business Rules ---")
    check_business_rules(spark, report)

    # Generate report
    markdown = generate_report_markdown(report)

    path = output_path or REPORT_OUTPUT_PATH
    print(f"\nWriting report to {path}")

    # Write to local filesystem (works in Databricks notebooks and local)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(markdown)
    except Exception:
        # Fallback: write to DBFS
        dbfs_path = f"dbfs:/mnt/migration-reports/DATA_QUALITY_REPORT.md"
        spark.sparkContext.parallelize([markdown]).saveAsTextFile(dbfs_path)
        print(f"  (fallback) Report written to {dbfs_path}")

    print(f"\nResults: {report.total_passed} passed, "
          f"{report.total_failed} failed, {report.total_warnings} warnings")
    return report


if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_DataQuality").getOrCreate()
    report = run_data_quality_checks(spark)

    if report.total_failed > 0:
        print("\n*** DATA QUALITY CHECKS FAILED ***")
        exit(1)
    else:
        print("\n*** DATA QUALITY CHECKS PASSED ***")
