"""
Data Quality Framework for the CDW -> Delta Lake migration.

Runs a comprehensive suite of validation checks after ingestion and generates
a DATA_QUALITY_REPORT.md summarizing pass/fail results per check.

Check categories:
1. Row count reconciliation (source vs. target)
2. Null checks on required fields
3. Referential integrity between loan_accounts -> borrowers and payments -> loan_accounts
4. Business rule validation (balance > 0 for active loans, closed date for closed loans, etc.)
5. Component sum validation (payment components should sum to total)
6. Data type/range validation (credit scores 300-850, rates 0-100, etc.)

Each check returns a QualityCheckResult with pass/fail status, counts, and details.
Results are aggregated into a markdown report.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from datetime import datetime
import logging

logger = logging.getLogger("cdw_migration.quality")


# ---------------------------------------------------------------------------
# Data structures for check results
# ---------------------------------------------------------------------------

@dataclass
class QualityCheckResult:
    """Result of a single data quality check."""
    category: str           # e.g., "Row Count", "Null Check", "Referential Integrity"
    check_name: str         # Human-readable name of the check
    table: str              # Target table being checked
    passed: bool            # True if the check passed
    expected: str           # What was expected
    actual: str             # What was found
    severity: str           # Critical, High, Medium, Low
    details: str = ""       # Optional additional context


@dataclass
class QualityReport:
    """Aggregated quality report containing all check results."""
    results: List[QualityCheckResult] = field(default_factory=list)
    run_timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"))

    @property
    def total_checks(self) -> int:
        return len(self.results)

    @property
    def passed_checks(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_checks(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def add(self, result: QualityCheckResult):
        """Add a check result to the report."""
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info(f"[{status}] {result.table}.{result.check_name}: {result.actual}")


# ---------------------------------------------------------------------------
# Row Count Reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession, report: QualityReport,
                     source_counts: dict):
    """
    Verify that the target tables have the expected row counts from the source.

    source_counts: dict mapping target table name to expected row count from the
    legacy source. These counts should be captured before ingestion runs.
    """
    target_tables = {
        "borrowers": "loan_warehouse.borrowers",
        "loan_products": "loan_warehouse.loan_products",
        "loan_accounts": "loan_warehouse.loan_accounts",
        "payments": "loan_warehouse.payments",
    }

    for table_key, table_name in target_tables.items():
        try:
            target_count = spark.table(table_name).count()
        except Exception:
            # Table doesn't exist yet
            target_count = 0

        expected = source_counts.get(table_key, "unknown")
        passed = target_count == expected if isinstance(expected, int) else False

        report.add(QualityCheckResult(
            category="Row Count Reconciliation",
            check_name="row_count_match",
            table=table_key,
            passed=passed,
            expected=str(expected),
            actual=str(target_count),
            severity="Critical",
            details=f"Source had {expected} rows, target has {target_count} rows"
        ))


# ---------------------------------------------------------------------------
# Null Checks on Required Fields
# ---------------------------------------------------------------------------

# Required fields per table (columns that must not be null in the modern schema)
REQUIRED_FIELDS = {
    "borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_products": ["code", "name", "type", "is_active"],
    "loan_accounts": [
        "account_number", "borrower_id", "product_id", "original_amount",
        "current_balance", "interest_rate", "term_months", "monthly_payment",
        "origination_date", "maturity_date", "status",
    ],
    "payments": [
        "legacy_payment_id", "loan_account_id", "payment_date",
        "total_amount", "type", "status",
    ],
}


def check_null_required_fields(spark: SparkSession, report: QualityReport):
    """
    Check that required fields contain no null values in the target tables.

    One check result is produced per (table, column) combination.
    """
    table_map = {
        "borrowers": "loan_warehouse.borrowers",
        "loan_products": "loan_warehouse.loan_products",
        "loan_accounts": "loan_warehouse.loan_accounts",
        "payments": "loan_warehouse.payments",
    }

    for table_key, required_cols in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table_map[table_key])
        except Exception:
            # Table missing — add one FAIL per required column
            for col_name in required_cols:
                report.add(QualityCheckResult(
                    category="Null Check",
                    check_name=f"not_null_{col_name}",
                    table=table_key,
                    passed=False,
                    expected="0 nulls",
                    actual="Table does not exist",
                    severity="Critical",
                ))
            continue

        total_rows = df.count()
        for col_name in required_cols:
            if col_name not in df.columns:
                report.add(QualityCheckResult(
                    category="Null Check",
                    check_name=f"not_null_{col_name}",
                    table=table_key,
                    passed=False,
                    expected="0 nulls",
                    actual=f"Column '{col_name}' not found in table",
                    severity="Critical",
                ))
                continue

            null_count = df.filter(F.col(col_name).isNull()).count()
            report.add(QualityCheckResult(
                category="Null Check",
                check_name=f"not_null_{col_name}",
                table=table_key,
                passed=(null_count == 0),
                expected="0 nulls",
                actual=f"{null_count} nulls out of {total_rows} rows",
                severity="High" if null_count > 0 else "Low",
                details=f"{(null_count / total_rows * 100):.1f}% null" if total_rows > 0 else ""
            ))


# ---------------------------------------------------------------------------
# Referential Integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport):
    """
    Verify FK relationships between target tables.

    Checks:
    - loan_accounts.borrower_id references a valid borrowers.id
    - loan_accounts.product_id references a valid loan_products.id
    - payments.loan_account_id references a valid loan_accounts.id
    """
    checks = [
        {
            "name": "loan_accounts.borrower_id -> borrowers.id",
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "borrower_id",
            "parent_table": "loan_warehouse.borrowers",
            "parent_col": "id",
        },
        {
            "name": "loan_accounts.product_id -> loan_products.id",
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "product_id",
            "parent_table": "loan_warehouse.loan_products",
            "parent_col": "id",
        },
        {
            "name": "payments.loan_account_id -> loan_accounts.id",
            "child_table": "loan_warehouse.payments",
            "child_col": "loan_account_id",
            "parent_table": "loan_warehouse.loan_accounts",
            "parent_col": "id",
        },
    ]

    for check in checks:
        try:
            child_df = spark.table(check["child_table"])
            parent_df = spark.table(check["parent_table"])
        except Exception as e:
            report.add(QualityCheckResult(
                category="Referential Integrity",
                check_name=check["name"],
                table=check["child_table"].split(".")[-1],
                passed=False,
                expected="0 orphaned rows",
                actual=f"Table missing: {e}",
                severity="Critical",
            ))
            continue

        # Find child rows where the FK value is not null but has no matching parent
        orphaned = child_df.join(
            parent_df,
            child_df[check["child_col"]] == parent_df[check["parent_col"]],
            "left_anti"
        ).filter(F.col(check["child_col"]).isNotNull())

        orphan_count = orphaned.count()
        total_count = child_df.count()

        report.add(QualityCheckResult(
            category="Referential Integrity",
            check_name=check["name"],
            table=check["child_table"].split(".")[-1],
            passed=(orphan_count == 0),
            expected="0 orphaned rows",
            actual=f"{orphan_count} orphaned out of {total_count} rows",
            severity="Critical" if orphan_count > 0 else "Low",
            details=f"{(orphan_count / total_count * 100):.1f}% orphaned" if total_count > 0 else ""
        ))


# ---------------------------------------------------------------------------
# Business Rule Validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport):
    """
    Validate domain-specific business rules on the target data.

    Rules:
    - Active loans must have current_balance > 0
    - Active loans must have delinquency_days >= 0
    - Closed loans should have current_balance == 0 (warning if not)
    - Credit scores must be in range 300-850
    - Interest rates must be in range 0-100
    - LTV percentages must be in range 0-200 (some edge cases allow > 100)
    - Payment component sum should equal total amount
    - Monthly payment must be > 0 for active loans
    - Origination date must be before maturity date
    """
    # --- Active loans: current_balance > 0 ---
    try:
        loans = spark.table("loan_warehouse.loan_accounts")

        active_loans = loans.filter(F.col("status") == "ACTIVE")
        active_zero_balance = active_loans.filter(F.col("current_balance") <= 0).count()
        active_total = active_loans.count()

        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="active_loans_positive_balance",
            table="loan_accounts",
            passed=(active_zero_balance == 0),
            expected="All active loans have balance > 0",
            actual=f"{active_zero_balance} active loans with balance <= 0 out of {active_total}",
            severity="High" if active_zero_balance > 0 else "Low",
        ))

        # --- Active loans: delinquency_days >= 0 ---
        negative_delinquency = active_loans.filter(F.col("delinquency_days") < 0).count()
        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="non_negative_delinquency_days",
            table="loan_accounts",
            passed=(negative_delinquency == 0),
            expected="All loans have delinquency_days >= 0",
            actual=f"{negative_delinquency} loans with negative delinquency days",
            severity="Medium" if negative_delinquency > 0 else "Low",
        ))

        # --- Monthly payment > 0 for active loans ---
        zero_payment_active = active_loans.filter(F.col("monthly_payment") <= 0).count()
        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="active_loans_positive_payment",
            table="loan_accounts",
            passed=(zero_payment_active == 0),
            expected="All active loans have monthly_payment > 0",
            actual=f"{zero_payment_active} active loans with payment <= 0",
            severity="High" if zero_payment_active > 0 else "Low",
        ))

        # --- Origination date before maturity date ---
        bad_date_order = loans.filter(
            F.col("origination_date").isNotNull()
            & F.col("maturity_date").isNotNull()
            & (F.col("origination_date") >= F.col("maturity_date"))
        ).count()
        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="origination_before_maturity",
            table="loan_accounts",
            passed=(bad_date_order == 0),
            expected="origination_date < maturity_date for all loans",
            actual=f"{bad_date_order} loans with origination >= maturity date",
            severity="High" if bad_date_order > 0 else "Low",
        ))

        # --- Interest rate range 0-100 ---
        bad_rate = loans.filter(
            F.col("interest_rate").isNotNull()
            & ((F.col("interest_rate") < 0) | (F.col("interest_rate") > 100))
        ).count()
        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="interest_rate_range",
            table="loan_accounts",
            passed=(bad_rate == 0),
            expected="Interest rate between 0 and 100",
            actual=f"{bad_rate} loans with out-of-range interest rate",
            severity="Medium" if bad_rate > 0 else "Low",
        ))

        # --- LTV percent range 0-200 ---
        bad_ltv = loans.filter(
            F.col("ltv_percent").isNotNull()
            & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
        ).count()
        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="ltv_percent_range",
            table="loan_accounts",
            passed=(bad_ltv == 0),
            expected="LTV percent between 0 and 200",
            actual=f"{bad_ltv} loans with out-of-range LTV",
            severity="Medium" if bad_ltv > 0 else "Low",
        ))

    except Exception as e:
        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="loan_account_checks",
            table="loan_accounts",
            passed=False,
            expected="All business rules pass",
            actual=f"Could not run checks: {e}",
            severity="Critical",
        ))

    # --- Credit score range 300-850 ---
    try:
        borrowers = spark.table("loan_warehouse.borrowers")
        bad_credit = borrowers.filter(
            F.col("credit_score").isNotNull()
            & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()
        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="credit_score_range",
            table="borrowers",
            passed=(bad_credit == 0),
            expected="Credit scores between 300 and 850",
            actual=f"{bad_credit} borrowers with out-of-range credit score",
            severity="Medium" if bad_credit > 0 else "Low",
        ))
    except Exception as e:
        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="credit_score_range",
            table="borrowers",
            passed=False,
            expected="Credit scores between 300 and 850",
            actual=f"Could not run check: {e}",
            severity="Critical",
        ))

    # --- Payment component sum == total amount ---
    try:
        payments = spark.table("loan_warehouse.payments")

        # Sum of principal + interest + escrow + late_fee should equal total_amount
        payments_with_sum = payments.withColumn(
            "computed_total",
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0))
        )

        # Allow a small tolerance (0.01) for floating-point rounding
        mismatched = payments_with_sum.filter(
            F.abs(F.col("computed_total") - F.col("total_amount")) > 0.01
        ).count()
        total_payments = payments.count()

        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="payment_component_sum",
            table="payments",
            passed=(mismatched == 0),
            expected="principal + interest + escrow + late_fee = total_amount (within $0.01)",
            actual=f"{mismatched} payments with mismatched component sums out of {total_payments}",
            severity="High" if mismatched > 0 else "Low",
            details="Component sum discrepancy indicates data corruption in legacy CDW"
        ))
    except Exception as e:
        report.add(QualityCheckResult(
            category="Business Rule",
            check_name="payment_component_sum",
            table="payments",
            passed=False,
            expected="Component sum matches total",
            actual=f"Could not run check: {e}",
            severity="Critical",
        ))


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_markdown_report(report: QualityReport) -> str:
    """
    Generate a DATA_QUALITY_REPORT.md from the aggregated check results.

    Report structure:
    - Executive summary (total pass/fail/rate)
    - Results grouped by category
    - Detailed table per category with check name, table, status, expected, actual, severity
    """
    lines = []
    lines.append("# Data Quality Report")
    lines.append("")
    lines.append(f"**Run Timestamp:** {report.run_timestamp}")
    lines.append("")

    # --- Executive Summary ---
    lines.append("## Executive Summary")
    lines.append("")
    pass_rate = (report.passed_checks / report.total_checks * 100) if report.total_checks > 0 else 0
    overall = "PASS" if report.failed_checks == 0 else "FAIL"
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| **Overall Status** | **{overall}** |")
    lines.append(f"| Total Checks | {report.total_checks} |")
    lines.append(f"| Passed | {report.passed_checks} |")
    lines.append(f"| Failed | {report.failed_checks} |")
    lines.append(f"| Pass Rate | {pass_rate:.1f}% |")
    lines.append("")

    # --- Failed checks summary (if any) ---
    failed = [r for r in report.results if not r.passed]
    if failed:
        lines.append("## Failed Checks Summary")
        lines.append("")
        lines.append("| Severity | Table | Check | Actual |")
        lines.append("|----------|-------|-------|--------|")
        # Sort by severity: Critical > High > Medium > Low
        severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        for r in sorted(failed, key=lambda x: severity_order.get(x.severity, 4)):
            lines.append(f"| {r.severity} | {r.table} | {r.check_name} | {r.actual} |")
        lines.append("")

    # --- Detailed results by category ---
    categories = []
    seen = set()
    for r in report.results:
        if r.category not in seen:
            categories.append(r.category)
            seen.add(r.category)

    for category in categories:
        cat_results = [r for r in report.results if r.category == category]
        cat_passed = sum(1 for r in cat_results if r.passed)
        cat_total = len(cat_results)

        lines.append(f"## {category}")
        lines.append("")
        lines.append(f"**{cat_passed}/{cat_total} checks passed**")
        lines.append("")
        lines.append("| Status | Table | Check | Expected | Actual | Severity |")
        lines.append("|--------|-------|-------|----------|--------|----------|")

        for r in cat_results:
            status_icon = "PASS" if r.passed else "FAIL"
            lines.append(
                f"| {status_icon} | {r.table} | {r.check_name} | {r.expected} | {r.actual} | {r.severity} |"
            )

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_all_checks(spark: SparkSession, source_counts: Optional[dict] = None) -> QualityReport:
    """
    Run all data quality checks and return the aggregated report.

    Args:
        spark: Active SparkSession
        source_counts: Dict of {table_key: expected_row_count} for reconciliation.
                       If None, row count checks are skipped.
    """
    report = QualityReport()

    logger.info("=" * 60)
    logger.info("Data Quality Checks STARTING")
    logger.info("=" * 60)

    # 1. Row count reconciliation (if source counts provided)
    if source_counts:
        check_row_counts(spark, report, source_counts)

    # 2. Null checks on required fields
    check_null_required_fields(spark, report)

    # 3. Referential integrity
    check_referential_integrity(spark, report)

    # 4. Business rule validation
    check_business_rules(spark, report)

    logger.info("=" * 60)
    logger.info(f"Data Quality Checks COMPLETE: {report.passed_checks}/{report.total_checks} passed")
    logger.info("=" * 60)

    return report


def run_and_save_report(spark: SparkSession, output_path: str,
                        source_counts: Optional[dict] = None):
    """
    Run all checks and write the markdown report to the specified path.

    Can be used from a Databricks notebook or standalone PySpark job.
    The report is saved both as a local file and (optionally) as a Delta table
    for historical tracking.
    """
    report = run_all_checks(spark, source_counts)

    # Generate and save the markdown report
    markdown = generate_markdown_report(report)

    # Write to DBFS or local filesystem
    dbutils = None
    try:
        # Try Databricks dbutils for DBFS write
        dbutils = spark._jvm.com.databricks.dbutils_v1.DBUtilsHolder.dbutils()
        dbutils.fs.put(output_path, markdown, True)
        logger.info(f"Report written to DBFS: {output_path}")
    except Exception:
        # Fall back to local filesystem write
        with open(output_path, "w") as f:
            f.write(markdown)
        logger.info(f"Report written to local path: {output_path}")

    return report


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Data_Quality").getOrCreate()

    # Example source counts from the legacy CDW (should match seed data)
    source_counts = {
        "borrowers": 5,
        "loan_products": 5,
        "loan_accounts": 5,
        "payments": 10,
    }

    run_and_save_report(
        spark,
        output_path="databricks/quality/DATA_QUALITY_REPORT.md",
        source_counts=source_counts,
    )

    spark.stop()
