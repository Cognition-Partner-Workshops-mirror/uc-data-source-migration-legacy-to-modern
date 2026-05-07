"""
Data Quality Framework for legacy CDW → modern Delta Lake migration.

Runs post-ingestion validation checks:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts ↔ borrowers, loan_accounts ↔ loan_products,
     payments ↔ loan_accounts
  4. Business rule validation:
     - Loan balance > 0 for active loans
     - Closed date required for closed loans (maturity_date must be <= today)
     - Payment amounts must be positive
     - Delinquency days must be non-negative
     - Interest rate must be within reasonable range (0–30%)

Generates a DATA_QUALITY_REPORT.md summarizing pass/fail results.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_quality")


@dataclass
class CheckResult:
    """Result of a single data quality check."""
    category: str
    check_name: str
    passed: bool
    detail: str
    affected_rows: int = 0


@dataclass
class QualityReport:
    """Aggregates all check results."""
    results: list[CheckResult] = field(default_factory=list)
    run_timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"))

    def add(self, result: CheckResult):
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

    @property
    def all_passed(self) -> bool:
        return self.failed_checks == 0


# ==========================================================================
# 1. ROW COUNT RECONCILIATION
# ==========================================================================

def check_row_counts(
    spark: SparkSession,
    report: QualityReport,
    source_counts: dict[str, int],
) -> None:
    """Compare source record counts against target table counts."""
    table_map = {
        "borrowers": "loan_warehouse.borrowers",
        "loan_products": "loan_warehouse.loan_products",
        "loan_accounts": "loan_warehouse.loan_accounts",
        "payments": "loan_warehouse.payments",
    }

    for label, table_name in table_map.items():
        target_count = spark.read.table(table_name).count()
        source_count = source_counts.get(label, 0)
        matched = target_count == source_count

        report.add(CheckResult(
            category="Row Count",
            check_name=f"{label}: source ({source_count}) vs target ({target_count})",
            passed=matched,
            detail=f"Source={source_count}, Target={target_count}" + ("" if matched else " — MISMATCH"),
            affected_rows=abs(source_count - target_count),
        ))


# ==========================================================================
# 2. NULL CHECKS ON REQUIRED FIELDS
# ==========================================================================

_REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_warehouse.loan_products": ["code", "name", "type", "term_months", "rate_type"],
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
    """Ensure required fields contain no nulls."""
    for table_name, columns in _REQUIRED_FIELDS.items():
        df = spark.read.table(table_name)
        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            report.add(CheckResult(
                category="Null Check",
                check_name=f"{table_name}.{col_name} NOT NULL",
                passed=null_count == 0,
                detail=f"{null_count} null(s) found" if null_count > 0 else "No nulls",
                affected_rows=null_count,
            ))


# ==========================================================================
# 3. REFERENTIAL INTEGRITY
# ==========================================================================

def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Verify FK relationships between tables."""

    # loan_accounts.borrower_key → borrowers.borrower_key
    loans = spark.read.table("loan_warehouse.loan_accounts")
    borrowers = spark.read.table("loan_warehouse.borrowers")
    orphan_borrowers = loans.join(
        borrowers,
        loans["borrower_key"] == borrowers["borrower_key"],
        "left_anti",
    ).count()
    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.borrower_key → borrowers.borrower_key",
        passed=orphan_borrowers == 0,
        detail=f"{orphan_borrowers} orphan loan(s)" if orphan_borrowers > 0 else "All FKs resolve",
        affected_rows=orphan_borrowers,
    ))

    # loan_accounts.product_key → loan_products.product_key
    products = spark.read.table("loan_warehouse.loan_products")
    orphan_products = loans.join(
        products,
        loans["product_key"] == products["product_key"],
        "left_anti",
    ).count()
    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.product_key → loan_products.product_key",
        passed=orphan_products == 0,
        detail=f"{orphan_products} orphan loan(s)" if orphan_products > 0 else "All FKs resolve",
        affected_rows=orphan_products,
    ))

    # payments.loan_account_key → loan_accounts.loan_account_key
    payments = spark.read.table("loan_warehouse.payments")
    orphan_payments = payments.join(
        loans,
        payments["loan_account_key"] == loans["loan_account_key"],
        "left_anti",
    ).count()
    report.add(CheckResult(
        category="Referential Integrity",
        check_name="payments.loan_account_key → loan_accounts.loan_account_key",
        passed=orphan_payments == 0,
        detail=f"{orphan_payments} orphan payment(s)" if orphan_payments > 0 else "All FKs resolve",
        affected_rows=orphan_payments,
    ))


# ==========================================================================
# 4. BUSINESS RULE VALIDATION
# ==========================================================================

def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules."""

    loans = spark.read.table("loan_warehouse.loan_accounts")
    payments = spark.read.table("loan_warehouse.payments")

    # 4a. Active loans must have current_balance > 0
    active_zero_bal = loans.filter(
        (F.col("status") == "Active") & (F.col("current_balance") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans must have balance > 0",
        passed=active_zero_bal == 0,
        detail=f"{active_zero_bal} active loan(s) with balance <= 0" if active_zero_bal > 0 else "OK",
        affected_rows=active_zero_bal,
    ))

    # 4b. Closed loans must have maturity_date in the past or today
    today = datetime.now().date()
    closed_future_maturity = loans.filter(
        (F.col("status") == "Closed") & (F.col("maturity_date") > F.lit(str(today)))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Closed loans must have maturity_date <= today",
        passed=closed_future_maturity == 0,
        detail=f"{closed_future_maturity} closed loan(s) with future maturity" if closed_future_maturity > 0 else "OK",
        affected_rows=closed_future_maturity,
    ))

    # 4c. Payment total_amount must be positive
    neg_payments = payments.filter(F.col("total_amount") <= 0).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Payment amounts must be > 0",
        passed=neg_payments == 0,
        detail=f"{neg_payments} payment(s) with amount <= 0" if neg_payments > 0 else "OK",
        affected_rows=neg_payments,
    ))

    # 4d. Delinquency days must be >= 0
    neg_dlq = loans.filter(F.col("delinquency_days") < 0).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Delinquency days must be >= 0",
        passed=neg_dlq == 0,
        detail=f"{neg_dlq} loan(s) with negative delinquency" if neg_dlq > 0 else "OK",
        affected_rows=neg_dlq,
    ))

    # 4e. Interest rate must be in range [0, 30]
    bad_rate = loans.filter(
        (F.col("interest_rate") < 0) | (F.col("interest_rate") > 30)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Interest rate in range [0, 30]%",
        passed=bad_rate == 0,
        detail=f"{bad_rate} loan(s) with out-of-range rate" if bad_rate > 0 else "OK",
        affected_rows=bad_rate,
    ))

    # 4f. Origination date must be before maturity date
    bad_dates = loans.filter(
        F.col("origination_date") >= F.col("maturity_date")
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Origination date must be before maturity date",
        passed=bad_dates == 0,
        detail=f"{bad_dates} loan(s) with origination >= maturity" if bad_dates > 0 else "OK",
        affected_rows=bad_dates,
    ))

    # 4g. Monthly payment must be positive for active loans
    zero_pmt = loans.filter(
        (F.col("status") == "Active") & (F.col("monthly_payment") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans must have monthly_payment > 0",
        passed=zero_pmt == 0,
        detail=f"{zero_pmt} active loan(s) with payment <= 0" if zero_pmt > 0 else "OK",
        affected_rows=zero_pmt,
    ))


# ==========================================================================
# REPORT GENERATION
# ==========================================================================

def generate_report_markdown(report: QualityReport) -> str:
    """Generate a Markdown-formatted data quality report."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run Timestamp:** {report.run_timestamp}",
        "",
        f"**Total Checks:** {report.total_checks}  ",
        f"**Passed:** {report.passed_checks}  ",
        f"**Failed:** {report.failed_checks}  ",
        f"**Overall:** {'PASS' if report.all_passed else 'FAIL'}",
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
        lines.append("| Status | Check | Detail | Affected Rows |")
        lines.append("|--------|-------|--------|---------------|")
        for c in checks:
            status_icon = "PASS" if c.passed else "**FAIL**"
            lines.append(f"| {status_icon} | {c.check_name} | {c.detail} | {c.affected_rows} |")
        lines.append("")

    # Summary
    if not report.all_passed:
        lines.append("---")
        lines.append("")
        lines.append("## Failed Checks Summary")
        lines.append("")
        for r in report.results:
            if not r.passed:
                lines.append(f"- **[{r.category}]** {r.check_name}: {r.detail}")
        lines.append("")

    return "\n".join(lines)


# ==========================================================================
# ENTRY POINT
# ==========================================================================

def run_all_checks(
    spark: SparkSession,
    source_counts: dict[str, int],
    output_path: str = "dbfs:/mnt/reports/DATA_QUALITY_REPORT.md",
) -> QualityReport:
    """
    Run the full data quality suite and write the report.

    Args:
        spark: Active SparkSession
        source_counts: Dict of {table_label: source_row_count} from ingestion results
        output_path: DBFS path to write the markdown report
    """
    report = QualityReport()

    logger.info("Running row count reconciliation...")
    check_row_counts(spark, report, source_counts)

    logger.info("Running null checks on required fields...")
    check_required_nulls(spark, report)

    logger.info("Running referential integrity checks...")
    check_referential_integrity(spark, report)

    logger.info("Running business rule validation...")
    check_business_rules(spark, report)

    # Generate and write report
    md_content = generate_report_markdown(report)

    logger.info("Writing quality report to %s", output_path)
    # Write using Spark's DBFS access via dbutils or direct file write
    spark.sparkContext.parallelize([md_content]).coalesce(1).saveAsTextFile(
        output_path.replace(".md", "_raw")
    )

    # Also log to stdout for notebook visibility
    logger.info("\n%s", md_content)

    if report.all_passed:
        logger.info("DATA QUALITY: ALL %d CHECKS PASSED", report.total_checks)
    else:
        logger.warning(
            "DATA QUALITY: %d of %d CHECKS FAILED",
            report.failed_checks,
            report.total_checks,
        )

    return report


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Data_Quality_Checks").getOrCreate()

    # When run standalone, provide expected source counts from pipeline output
    # These should match the counts from the ingestion run
    sample_source_counts = {
        "borrowers": 5,
        "loan_products": 5,
        "loan_accounts": 5,
        "payments": 10,
    }

    report = run_all_checks(spark, sample_source_counts)

    if not report.all_passed:
        raise SystemExit(1)
