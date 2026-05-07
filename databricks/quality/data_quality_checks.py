"""
Data Quality Framework for Legacy CDW Migration.

Runs post-ingestion validation checks against the Delta Lake target tables:
- Row count reconciliation (source vs. target)
- Null checks on required fields
- Referential integrity between loan and borrower tables
- Business rule validation
- Generates a structured report of pass/fail results
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str
    check_name: str
    table: str
    passed: bool
    detail: str
    source_count: Optional[int] = None
    target_count: Optional[int] = None
    violation_count: Optional[int] = None


@dataclass
class QualityReport:
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    results: list = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def total_checks(self) -> int:
        return len(self.results)

    @property
    def passed_checks(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_checks(self) -> int:
        return sum(1 for r in self.results if not r.passed)


# ---------------------------------------------------------------------------
# Row count reconciliation
# ---------------------------------------------------------------------------

def check_row_count(
    spark: SparkSession,
    report: QualityReport,
    table_name: str,
    source_count: int,
) -> None:
    """Verify target table row count matches source (minus quarantined records)."""
    target_df = spark.table(f"loan_warehouse.{table_name}")
    target_count = target_df.count()

    quarantine_path = f"dbfs:/mnt/legacy-cdw/quarantine/{table_name}/"
    try:
        quarantine_df = spark.read.format("delta").load(quarantine_path)
        quarantine_count = quarantine_df.count()
    except Exception:
        quarantine_count = 0

    expected = source_count - quarantine_count
    passed = target_count == expected

    report.add(CheckResult(
        category="Row Count Reconciliation",
        check_name=f"{table_name}: source({source_count}) - quarantine({quarantine_count}) == target({target_count})",
        table=table_name,
        passed=passed,
        detail=f"Expected {expected} rows, found {target_count}",
        source_count=source_count,
        target_count=target_count,
    ))


# ---------------------------------------------------------------------------
# Null checks on required fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "borrowers": ["borrower_id", "first_name", "last_name", "status"],
    "loan_products": ["product_code", "name", "type", "term_months", "rate_type", "is_active"],
    "loan_accounts": [
        "account_number", "borrower_id", "product_code", "original_amount",
        "current_balance", "interest_rate", "term_months", "monthly_payment",
        "origination_date", "maturity_date", "status",
    ],
    "payments": [
        "payment_id", "loan_account_number", "payment_date",
        "total_amount", "type", "status",
    ],
}


def check_null_required_fields(
    spark: SparkSession,
    report: QualityReport,
    table_name: str,
) -> None:
    """Check that required fields have no nulls in the target table."""
    df = spark.table(f"loan_warehouse.{table_name}")
    fields = REQUIRED_FIELDS.get(table_name, [])

    for col_name in fields:
        null_count = df.filter(F.col(col_name).isNull()).count()
        passed = null_count == 0
        report.add(CheckResult(
            category="Null Check",
            check_name=f"{table_name}.{col_name} has no nulls",
            table=table_name,
            passed=passed,
            detail=f"{null_count} null values found" if not passed else "No nulls",
            violation_count=null_count,
        ))


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(
    spark: SparkSession,
    report: QualityReport,
) -> None:
    """Check foreign key relationships between tables."""
    # loan_accounts.borrower_id -> borrowers.borrower_id
    loans_df = spark.table("loan_warehouse.loan_accounts")
    borrowers_df = spark.table("loan_warehouse.borrowers")

    orphan_borrower_ids = (
        loans_df.select("borrower_id")
        .distinct()
        .join(borrowers_df.select("borrower_id"), "borrower_id", "left_anti")
    )
    orphan_count = orphan_borrower_ids.count()
    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.borrower_id references valid borrower",
        table="loan_accounts",
        passed=orphan_count == 0,
        detail=f"{orphan_count} orphaned borrower_id values" if orphan_count > 0 else "All references valid",
        violation_count=orphan_count,
    ))

    # loan_accounts.product_code -> loan_products.product_code
    products_df = spark.table("loan_warehouse.loan_products")
    orphan_product_codes = (
        loans_df.select("product_code")
        .distinct()
        .join(products_df.select("product_code"), "product_code", "left_anti")
    )
    orphan_count = orphan_product_codes.count()
    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.product_code references valid product",
        table="loan_accounts",
        passed=orphan_count == 0,
        detail=f"{orphan_count} orphaned product_code values" if orphan_count > 0 else "All references valid",
        violation_count=orphan_count,
    ))

    # payments.loan_account_number -> loan_accounts.account_number
    payments_df = spark.table("loan_warehouse.payments")
    orphan_loan_accounts = (
        payments_df.select("loan_account_number")
        .distinct()
        .join(loans_df.select(F.col("account_number").alias("loan_account_number")), "loan_account_number", "left_anti")
    )
    orphan_count = orphan_loan_accounts.count()
    report.add(CheckResult(
        category="Referential Integrity",
        check_name="payments.loan_account_number references valid loan account",
        table="payments",
        passed=orphan_count == 0,
        detail=f"{orphan_count} orphaned loan_account_number values" if orphan_count > 0 else "All references valid",
        violation_count=orphan_count,
    ))


# ---------------------------------------------------------------------------
# Business rule validation
# ---------------------------------------------------------------------------

def check_business_rules(
    spark: SparkSession,
    report: QualityReport,
) -> None:
    """Validate domain-specific business rules."""
    loans_df = spark.table("loan_warehouse.loan_accounts")
    payments_df = spark.table("loan_warehouse.payments")

    # Rule 1: Active loans must have positive current_balance
    active_zero_balance = (
        loans_df
        .filter(F.col("status") == "ACTIVE")
        .filter(F.col("current_balance") <= 0)
        .count()
    )
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans have positive current_balance",
        table="loan_accounts",
        passed=active_zero_balance == 0,
        detail=f"{active_zero_balance} active loans with balance <= 0",
        violation_count=active_zero_balance,
    ))

    # Rule 2: Closed loans must have a maturity_date
    closed_no_maturity = (
        loans_df
        .filter(F.col("status") == "CLOSED")
        .filter(F.col("maturity_date").isNull())
        .count()
    )
    report.add(CheckResult(
        category="Business Rule",
        check_name="Closed loans have a maturity_date",
        table="loan_accounts",
        passed=closed_no_maturity == 0,
        detail=f"{closed_no_maturity} closed loans with null maturity_date",
        violation_count=closed_no_maturity,
    ))

    # Rule 3: Loan original_amount must be positive
    negative_originals = (
        loans_df
        .filter(F.col("original_amount") <= 0)
        .count()
    )
    report.add(CheckResult(
        category="Business Rule",
        check_name="All loans have positive original_amount",
        table="loan_accounts",
        passed=negative_originals == 0,
        detail=f"{negative_originals} loans with original_amount <= 0",
        violation_count=negative_originals,
    ))

    # Rule 4: Payment total_amount must be positive
    negative_payments = (
        payments_df
        .filter(F.col("total_amount") <= 0)
        .count()
    )
    report.add(CheckResult(
        category="Business Rule",
        check_name="All payments have positive total_amount",
        table="payments",
        passed=negative_payments == 0,
        detail=f"{negative_payments} payments with total_amount <= 0",
        violation_count=negative_payments,
    ))

    # Rule 5: Payment component sums should match total
    component_mismatch = (
        payments_df
        .filter(F.col("component_sum_valid") == False)  # noqa: E712
        .count()
    )
    report.add(CheckResult(
        category="Business Rule",
        check_name="Payment component sums match total_amount (within $0.02)",
        table="payments",
        passed=component_mismatch == 0,
        detail=f"{component_mismatch} payments with component sum mismatch",
        violation_count=component_mismatch,
    ))

    # Rule 6: Interest rate should be between 0 and 100
    bad_rates = (
        loans_df
        .filter((F.col("interest_rate") < 0) | (F.col("interest_rate") > 100))
        .count()
    )
    report.add(CheckResult(
        category="Business Rule",
        check_name="Interest rates are between 0 and 100",
        table="loan_accounts",
        passed=bad_rates == 0,
        detail=f"{bad_rates} loans with out-of-range interest rate",
        violation_count=bad_rates,
    ))

    # Rule 7: Origination date should not be in the future
    future_originations = (
        loans_df
        .filter(F.col("origination_date") > F.current_date())
        .count()
    )
    report.add(CheckResult(
        category="Business Rule",
        check_name="No loans originated in the future",
        table="loan_accounts",
        passed=future_originations == 0,
        detail=f"{future_originations} loans with future origination_date",
        violation_count=future_originations,
    ))

    # Rule 8: Status codes are all expanded (no raw abbreviations)
    raw_status_loans = (
        loans_df
        .filter(F.col("status").isin("ACT", "CLO", "DFT", "FRB"))
        .count()
    )
    report.add(CheckResult(
        category="Business Rule",
        check_name="Loan status codes are expanded (not abbreviated)",
        table="loan_accounts",
        passed=raw_status_loans == 0,
        detail=f"{raw_status_loans} loans still have abbreviated status codes",
        violation_count=raw_status_loans,
    ))

    raw_status_payments = (
        payments_df
        .filter(F.col("status").isin("PST", "REV", "NSF", "PND"))
        .count()
    )
    report.add(CheckResult(
        category="Business Rule",
        check_name="Payment status codes are expanded (not abbreviated)",
        table="payments",
        passed=raw_status_payments == 0,
        detail=f"{raw_status_payments} payments still have abbreviated status codes",
        violation_count=raw_status_payments,
    ))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_markdown_report(report: QualityReport) -> str:
    """Generate a markdown DATA_QUALITY_REPORT.md from check results."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run Timestamp:** {report.run_timestamp}",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total Checks | {report.total_checks} |",
        f"| Passed | {report.passed_checks} |",
        f"| Failed | {report.failed_checks} |",
        f"| Pass Rate | {report.passed_checks / report.total_checks * 100:.1f}% |" if report.total_checks > 0 else "",
        "",
        "## Detailed Results",
        "",
    ]

    # Group by category
    categories = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for category, checks in categories.items():
        lines.append(f"### {category}")
        lines.append("")
        lines.append("| Check | Table | Result | Detail |")
        lines.append("|-------|-------|--------|--------|")
        for c in checks:
            status = "PASS" if c.passed else "**FAIL**"
            lines.append(f"| {c.check_name} | {c.table} | {status} | {c.detail} |")
        lines.append("")

    # Failed checks summary
    failed = [r for r in report.results if not r.passed]
    if failed:
        lines.append("## Failed Checks — Action Items")
        lines.append("")
        for i, f_check in enumerate(failed, 1):
            lines.append(f"{i}. **[{f_check.category}]** {f_check.check_name}")
            lines.append(f"   - Table: `{f_check.table}`")
            lines.append(f"   - Detail: {f_check.detail}")
            if f_check.violation_count is not None:
                lines.append(f"   - Violations: {f_check.violation_count}")
            lines.append("")
    else:
        lines.append("## All Checks Passed")
        lines.append("")
        lines.append("No data quality issues detected.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_all_checks(
    spark: SparkSession,
    source_counts: dict,
    output_path: str = "dbfs:/mnt/legacy-cdw/reports/DATA_QUALITY_REPORT.md",
) -> QualityReport:
    """
    Run all data quality checks and write the report.

    Args:
        spark: Active SparkSession
        source_counts: Dict of table_name -> source row count from ingestion
        output_path: DBFS path to write the markdown report

    Returns:
        QualityReport with all results
    """
    report = QualityReport()

    # Row count reconciliation
    for table_name, count in source_counts.items():
        check_row_count(spark, report, table_name, count)

    # Null checks
    for table_name in REQUIRED_FIELDS:
        check_null_required_fields(spark, report, table_name)

    # Referential integrity
    check_referential_integrity(spark, report)

    # Business rules
    check_business_rules(spark, report)

    # Generate and write report
    md_content = generate_markdown_report(report)

    # Write to DBFS
    dbutils = None
    try:
        dbutils = spark._jvm.com.databricks.dbutils_v1.DBUtilsHolder.dbutils()  # type: ignore
        dbutils.fs.put(output_path, md_content, overwrite=True)
        print(f"[DQ Report] Written to {output_path}")
    except Exception:
        # Fallback: write locally
        local_path = "/tmp/DATA_QUALITY_REPORT.md"
        with open(local_path, "w") as f:
            f.write(md_content)
        print(f"[DQ Report] Written locally to {local_path}")

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"DATA QUALITY REPORT — {report.run_timestamp}")
    print(f"{'=' * 60}")
    print(f"Total: {report.total_checks} | Passed: {report.passed_checks} | Failed: {report.failed_checks}")
    if report.failed_checks > 0:
        print(f"\nFailed checks:")
        for r in report.results:
            if not r.passed:
                print(f"  - [{r.category}] {r.check_name}: {r.detail}")
    print(f"{'=' * 60}\n")

    return report


if __name__ == "__main__":
    spark = SparkSession.builder.appName("DataQualityChecks").getOrCreate()
    # Example usage — source counts would come from the ingestion pipeline
    counts = {
        "borrowers": 5,
        "loan_products": 4,
        "loan_accounts": 5,
        "payments": 25,
    }
    run_all_checks(spark, counts)
