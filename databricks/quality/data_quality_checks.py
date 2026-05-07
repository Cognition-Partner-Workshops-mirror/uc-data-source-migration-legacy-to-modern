"""
PySpark data quality framework for the loan_warehouse.

Runs after ingestion to validate:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between tables
  4. Business rule validation

Generates a DATA_QUALITY_REPORT.md summarizing pass/fail results.

Usage (Databricks notebook or job):
    %run ./data_quality_checks
"""

from dataclasses import dataclass, field
from datetime import datetime
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


@dataclass
class CheckResult:
    category: str
    check_name: str
    passed: bool
    details: str
    severity: str = "HIGH"


@dataclass
class QualityReport:
    results: list[CheckResult] = field(default_factory=list)
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def add(self, result: CheckResult):
        self.results.append(result)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession, report: QualityReport,
                     source_counts: dict[str, int]):
    """Compare source record counts against target table counts."""
    target_tables = {
        "CDW_BORR_MSTR": "loan_warehouse.borrowers",
        "CDW_LN_PROD": "loan_warehouse.loan_products",
        "CDW_LN_ACCT": "loan_warehouse.loan_accounts",
        "CDW_PMT_HIST": "loan_warehouse.payments",
    }

    for source_name, target_table in target_tables.items():
        source_count = source_counts.get(source_name, 0)
        try:
            target_count = spark.table(target_table).count()
        except Exception as e:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"{source_name} -> {target_table}",
                passed=False,
                details=f"Target table not accessible: {e}",
                severity="CRITICAL"
            ))
            continue

        # Check quarantine tables for dropped records
        quarantine_table = f"loan_warehouse._quarantine_{target_table.split('.')[-1]}"
        quarantine_count = 0
        try:
            quarantine_count = spark.table(quarantine_table).count()
        except Exception:
            pass  # Quarantine table may not exist

        total_accounted = target_count + quarantine_count
        passed = total_accounted == source_count

        report.add(CheckResult(
            category="Row Count",
            check_name=f"{source_name} -> {target_table}",
            passed=passed,
            details=(
                f"Source: {source_count}, Target: {target_count}, "
                f"Quarantined: {quarantine_count}, "
                f"Accounted: {total_accounted}"
            ),
            severity="CRITICAL" if not passed else "INFO"
        ))


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": [
        "external_id", "first_name", "last_name", "ssn_hash", "status"
    ],
    "loan_warehouse.loan_products": [
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount"
    ],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "status"
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount",
        "principal_amount", "interest_amount", "type", "status"
    ],
}


def check_required_nulls(spark: SparkSession, report: QualityReport):
    """Check that required fields have no null values."""
    for table_name, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table_name)
        except Exception as e:
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table_name} accessibility",
                passed=False,
                details=f"Table not accessible: {e}",
                severity="CRITICAL"
            ))
            continue

        total_rows = df.count()
        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            passed = null_count == 0
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table_name}.{col_name}",
                passed=passed,
                details=f"{null_count}/{total_rows} null values",
                severity="HIGH" if not passed else "INFO"
            ))


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport):
    """Verify FK relationships between tables."""
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

            orphans = (
                child_df
                .join(parent_df,
                      child_df[check["child_col"]] == parent_df[check["parent_col"]],
                      "left_anti")
                .count()
            )

            passed = orphans == 0
            report.add(CheckResult(
                category="Referential Integrity",
                check_name=check["name"],
                passed=passed,
                details=f"{orphans} orphaned records found",
                severity="CRITICAL" if not passed else "INFO"
            ))
        except Exception as e:
            report.add(CheckResult(
                category="Referential Integrity",
                check_name=check["name"],
                passed=False,
                details=f"Check failed: {e}",
                severity="CRITICAL"
            ))


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport):
    """Validate domain-specific business rules."""
    try:
        loans = spark.table("loan_warehouse.loan_accounts")
    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            check_name="loan_accounts accessibility",
            passed=False,
            details=str(e),
            severity="CRITICAL"
        ))
        return

    # Rule 1: Active loans must have positive balance
    active_zero_balance = loans.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans must have balance > 0",
        passed=active_zero_balance == 0,
        details=f"{active_zero_balance} active loans with zero/negative balance",
        severity="HIGH"
    ))

    # Rule 2: Interest rate must be in range 0-30%
    bad_rates = loans.filter(
        (F.col("interest_rate") < 0) | (F.col("interest_rate") > 30)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Interest rate in range [0, 30]",
        passed=bad_rates == 0,
        details=f"{bad_rates} loans with out-of-range interest rates",
        severity="HIGH"
    ))

    # Rule 3: Maturity date must be after origination date
    bad_dates = loans.filter(
        F.col("maturity_date") <= F.col("origination_date")
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Maturity date > origination date",
        passed=bad_dates == 0,
        details=f"{bad_dates} loans with maturity <= origination",
        severity="CRITICAL"
    ))

    # Rule 4: LTV percent should be between 0 and 200
    bad_ltv = loans.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="LTV percent in range [0, 200]",
        passed=bad_ltv == 0,
        details=f"{bad_ltv} loans with out-of-range LTV",
        severity="MEDIUM"
    ))

    # Rule 5: Delinquency days must be non-negative
    bad_dlq = loans.filter(F.col("delinquency_days") < 0).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Delinquency days >= 0",
        passed=bad_dlq == 0,
        details=f"{bad_dlq} loans with negative delinquency days",
        severity="MEDIUM"
    ))

    # Rule 6: Payment reconciliation
    try:
        payments = spark.table("loan_warehouse.payments")
        unreconciled = payments.filter(F.col("reconciled") == False).count()  # noqa: E712
        total_payments = payments.count()
        report.add(CheckResult(
            category="Business Rule",
            check_name="Payment amounts reconcile (components = total)",
            passed=unreconciled == 0,
            details=f"{unreconciled}/{total_payments} payments failed reconciliation",
            severity="HIGH"
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            check_name="Payment reconciliation",
            passed=False,
            details=str(e),
            severity="HIGH"
        ))

    # Rule 7: Credit score range
    try:
        borrowers = spark.table("loan_warehouse.borrowers")
        bad_scores = borrowers.filter(
            F.col("credit_score").isNotNull()
            & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            check_name="Credit score in range [300, 850]",
            passed=bad_scores == 0,
            details=f"{bad_scores} borrowers with out-of-range credit scores",
            severity="MEDIUM"
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            check_name="Credit score validation",
            passed=False,
            details=str(e),
            severity="MEDIUM"
        ))


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_report_markdown(report: QualityReport) -> str:
    """Generate a markdown report from check results."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run timestamp:** {report.run_timestamp}",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total checks | {report.total} |",
        f"| Passed | {report.pass_count} |",
        f"| Failed | {report.fail_count} |",
        f"| Pass rate | {report.pass_count / max(report.total, 1) * 100:.1f}% |",
        "",
        "---",
        "",
        "## Results by Category",
        "",
    ]

    categories = sorted(set(r.category for r in report.results))
    for category in categories:
        lines.append(f"### {category}")
        lines.append("")
        lines.append("| Check | Status | Severity | Details |")
        lines.append("|---|---|---|---|")

        cat_results = [r for r in report.results if r.category == category]
        for r in cat_results:
            status = "PASS" if r.passed else "**FAIL**"
            lines.append(f"| {r.check_name} | {status} | {r.severity} | {r.details} |")

        lines.append("")

    # Failed checks summary
    failures = [r for r in report.results if not r.passed]
    if failures:
        lines.append("---")
        lines.append("")
        lines.append("## Failed Checks Summary")
        lines.append("")
        for r in failures:
            lines.append(f"- **[{r.severity}] {r.category} / {r.check_name}**: {r.details}")
        lines.append("")

    return "\n".join(lines)


def run(spark: SparkSession,
        source_counts: dict[str, int] | None = None,
        output_path: str = "/dbfs/mnt/reports/DATA_QUALITY_REPORT.md"):
    """
    Run all data quality checks and generate the report.

    Args:
        spark: SparkSession
        source_counts: Dict mapping legacy table names to their row counts
                       (returned by each ingestion script's run()).
                       If None, row count reconciliation is skipped.
        output_path: Where to write the markdown report.
    """
    print("=== Data Quality Checks: START ===")
    report = QualityReport()

    # 1. Row count reconciliation
    if source_counts:
        print("Running row count reconciliation...")
        check_row_counts(spark, report, source_counts)

    # 2. Null checks
    print("Running null checks on required fields...")
    check_required_nulls(spark, report)

    # 3. Referential integrity
    print("Running referential integrity checks...")
    check_referential_integrity(spark, report)

    # 4. Business rules
    print("Running business rule validation...")
    check_business_rules(spark, report)

    # Generate report
    md_content = generate_report_markdown(report)
    print(md_content)

    # Write to DBFS
    try:
        with open(output_path, "w") as f:
            f.write(md_content)
        print(f"Report written to {output_path}")
    except Exception as e:
        print(f"Could not write report to {output_path}: {e}")
        print("Report content printed above.")

    print(f"=== Data Quality Checks: COMPLETE ({report.pass_count}/{report.total} passed) ===")
    return report


if __name__ == "__main__":
    spark = SparkSession.builder.getOrCreate()
    run(spark)
