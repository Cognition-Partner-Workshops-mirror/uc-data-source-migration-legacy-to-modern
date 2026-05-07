"""
Data Quality Validation Framework for Legacy CDW → Delta Lake Migration.

Runs post-ingestion checks and produces a structured report:
  - Row count reconciliation (source vs. target)
  - Null checks on required fields
  - Referential integrity between loan and borrower tables
  - Business rule validation (balance > 0 for active, closed date rules, etc.)

Usage:
    spark-submit data_quality_checks.py \
        --borrowers-source  /mnt/landing/cdw_borr_mstr/ \
        --products-source   /mnt/landing/cdw_ln_prod/ \
        --accounts-source   /mnt/landing/cdw_ln_acct/ \
        --payments-source   /mnt/landing/cdw_pmt_hist/ \
        --output            /mnt/reports/DATA_QUALITY_REPORT.md
"""

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("data_quality")


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str
    check_name: str
    passed: bool
    detail: str
    severity: str = "ERROR"


@dataclass
class QualityReport:
    results: List[CheckResult] = field(default_factory=list)
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def add(self, result: CheckResult) -> None:
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info("[%s] %s / %s: %s", status, result.category, result.check_name, result.detail)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def check_row_counts(
    report: QualityReport,
    spark: SparkSession,
    source_path: str,
    target_table: str,
    table_label: str,
) -> None:
    """Verify that source and target row counts match."""
    if source_path.endswith(".parquet") or source_path.endswith("/parquet"):
        source_df = spark.read.parquet(source_path)
    else:
        source_df = spark.read.option("header", "true").csv(source_path)

    source_count = source_df.count()
    target_count = spark.table(target_table).count()

    report.add(CheckResult(
        category="Row Count Reconciliation",
        check_name=f"{table_label}: source vs. target",
        passed=source_count == target_count,
        detail=f"Source={source_count}, Target={target_count}",
        severity="ERROR",
    ))


def check_null_required_fields(
    report: QualityReport,
    spark: SparkSession,
    table: str,
    required_columns: List[str],
) -> None:
    """Check that required columns contain no NULL values."""
    df = spark.table(table)
    for col_name in required_columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        report.add(CheckResult(
            category="Null Checks",
            check_name=f"{table}.{col_name} NOT NULL",
            passed=null_count == 0,
            detail=f"NULL count: {null_count}" if null_count > 0 else "No NULLs",
            severity="ERROR",
        ))


def check_referential_integrity(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """Verify FK relationships between modern tables."""
    # loan_accounts.borrower_key → borrowers.borrower_key
    loans = spark.table("loan_warehouse.loan_accounts")
    borrowers = spark.table("loan_warehouse.borrowers")

    orphan_borrower = loans.join(
        borrowers,
        loans["borrower_key"] == borrowers["borrower_key"],
        "left_anti",
    ).count()

    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.borrower_key → borrowers",
        passed=orphan_borrower == 0,
        detail=f"Orphan records: {orphan_borrower}" if orphan_borrower > 0 else "All FKs valid",
        severity="ERROR",
    ))

    # loan_accounts.product_key → loan_products.product_key
    products = spark.table("loan_warehouse.loan_products")

    orphan_product = loans.join(
        products,
        loans["product_key"] == products["product_key"],
        "left_anti",
    ).count()

    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.product_key → loan_products",
        passed=orphan_product == 0,
        detail=f"Orphan records: {orphan_product}" if orphan_product > 0 else "All FKs valid",
        severity="ERROR",
    ))

    # payments.loan_account_key → loan_accounts.loan_account_key
    payments = spark.table("loan_warehouse.payments")

    orphan_loan = payments.join(
        loans,
        payments["loan_account_key"] == loans["loan_account_key"],
        "left_anti",
    ).count()

    report.add(CheckResult(
        category="Referential Integrity",
        check_name="payments.loan_account_key → loan_accounts",
        passed=orphan_loan == 0,
        detail=f"Orphan records: {orphan_loan}" if orphan_loan > 0 else "All FKs valid",
        severity="ERROR",
    ))


def check_business_rules(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """Validate domain-specific business rules."""
    loans = spark.table("loan_warehouse.loan_accounts")
    payments = spark.table("loan_warehouse.payments")
    borrowers = spark.table("loan_warehouse.borrowers")

    # Rule 1: Active loans must have positive current balance
    active_zero_bal = loans.filter(
        (F.col("status") == "Active") & (F.col("current_balance") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Active loans have positive balance",
        passed=active_zero_bal == 0,
        detail=f"Active loans with balance <= 0: {active_zero_bal}",
        severity="ERROR",
    ))

    # Rule 2: Active loans must have a future or present maturity date
    active_past_mat = loans.filter(
        (F.col("status") == "Active") & (F.col("maturity_date") < F.current_date())
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Active loans have future maturity date",
        passed=active_past_mat == 0,
        detail=f"Active loans with past maturity: {active_past_mat}",
        severity="WARNING",
    ))

    # Rule 3: Origination date must be before maturity date
    bad_dates = loans.filter(
        F.col("origination_date") >= F.col("maturity_date")
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Origination date < maturity date",
        passed=bad_dates == 0,
        detail=f"Loans with origination >= maturity: {bad_dates}",
        severity="ERROR",
    ))

    # Rule 4: Monthly payment must be positive for all loans
    zero_payment = loans.filter(F.col("monthly_payment") <= 0).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="All loans have positive monthly payment",
        passed=zero_payment == 0,
        detail=f"Loans with payment <= 0: {zero_payment}",
        severity="ERROR",
    ))

    # Rule 5: Credit score must be in valid range (300-850) when present
    bad_credit = borrowers.filter(
        F.col("credit_score").isNotNull()
        & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Credit scores in valid range (300-850)",
        passed=bad_credit == 0,
        detail=f"Borrowers with out-of-range credit score: {bad_credit}",
        severity="WARNING",
    ))

    # Rule 6: LTV percent should be between 0 and 200
    bad_ltv = loans.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="LTV percent in valid range (0-200%)",
        passed=bad_ltv == 0,
        detail=f"Loans with out-of-range LTV: {bad_ltv}",
        severity="WARNING",
    ))

    # Rule 7: Interest rate should be between 0 and 25
    bad_rate = loans.filter(
        (F.col("interest_rate") < 0) | (F.col("interest_rate") > 25)
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Interest rate in valid range (0-25%)",
        passed=bad_rate == 0,
        detail=f"Loans with out-of-range interest rate: {bad_rate}",
        severity="WARNING",
    ))

    # Rule 8: Payment total_amount must be positive
    neg_payments = payments.filter(F.col("total_amount") <= 0).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="All payments have positive total amount",
        passed=neg_payments == 0,
        detail=f"Payments with amount <= 0: {neg_payments}",
        severity="ERROR",
    ))

    # Rule 9: Payment received_date should be on or before processed_date
    bad_recv_proc = payments.filter(
        F.col("received_date").isNotNull()
        & F.col("processed_date").isNotNull()
        & (F.col("received_date") > F.col("processed_date"))
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Payment received_date <= processed_date",
        passed=bad_recv_proc == 0,
        detail=f"Payments with received > processed: {bad_recv_proc}",
        severity="WARNING",
    ))

    # Rule 10: Delinquent loans (delinquency_days > 0) should not have status Active with 0 days
    delinq_mismatch = loans.filter(
        (F.col("delinquency_days") > 0) & (F.col("status") == "Active")
    ).count()
    report.add(CheckResult(
        category="Business Rules",
        check_name="Delinquent active loans flagged (informational)",
        passed=True,
        detail=f"Active loans with delinquency_days > 0: {delinq_mismatch} (review recommended)",
        severity="INFO",
    ))


def check_status_code_expansion(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """Verify no unexpanded legacy codes remain in status fields."""
    legacy_codes = {"ACT", "CLO", "DFT", "FRB", "INA", "REG", "EXT", "PRT", "PRE",
                    "PST", "REV", "NSF", "PND", "SFR", "CND", "MFR", "TWN"}

    checks = [
        ("loan_warehouse.loan_accounts", "status"),
        ("loan_warehouse.loan_accounts", "property_type"),
        ("loan_warehouse.payments", "type"),
        ("loan_warehouse.payments", "status"),
        ("loan_warehouse.borrowers", "status"),
    ]

    for table, col_name in checks:
        df = spark.table(table)
        unexpanded = df.filter(F.upper(F.col(col_name)).isin(list(legacy_codes))).count()
        report.add(CheckResult(
            category="Status Code Expansion",
            check_name=f"{table}.{col_name} — no legacy codes remain",
            passed=unexpanded == 0,
            detail=f"Unexpanded legacy codes: {unexpanded}" if unexpanded > 0 else "All codes expanded",
            severity="ERROR",
        ))


def check_uniqueness(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """Verify unique constraints on key columns."""
    checks = [
        ("loan_warehouse.borrowers", "external_id"),
        ("loan_warehouse.loan_products", "code"),
        ("loan_warehouse.loan_accounts", "account_number"),
    ]

    for table, col_name in checks:
        df = spark.table(table)
        total = df.count()
        distinct = df.select(col_name).distinct().count()
        report.add(CheckResult(
            category="Uniqueness",
            check_name=f"{table}.{col_name} is unique",
            passed=total == distinct,
            detail=f"Total={total}, Distinct={distinct}" if total != distinct else "All unique",
            severity="ERROR",
        ))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_markdown_report(report: QualityReport) -> str:
    """Render the quality report as a Markdown document."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run timestamp:** {report.run_timestamp}",
        "",
        f"**Total checks:** {report.total}  ",
        f"**Passed:** {report.passed_count}  ",
        f"**Failed:** {report.failed_count}  ",
        "",
        "---",
        "",
    ]

    # Group by category
    categories = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for category, checks in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Check | Result | Severity | Detail |")
        lines.append("|-------|--------|----------|--------|")
        for c in checks:
            icon = "PASS" if c.passed else "FAIL"
            lines.append(f"| {c.check_name} | {icon} | {c.severity} | {c.detail} |")
        lines.append("")

    # Summary
    lines.append("---")
    lines.append("")
    if report.failed_count == 0:
        lines.append("**Overall result: ALL CHECKS PASSED**")
    else:
        lines.append(
            f"**Overall result: {report.failed_count} CHECK(S) FAILED — review required before production cutover**"
        )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all_checks(
    spark: SparkSession,
    borrowers_source: str,
    products_source: str,
    accounts_source: str,
    payments_source: str,
) -> QualityReport:
    """Execute the full quality check suite and return the report."""
    report = QualityReport()

    logger.info("Running row count reconciliation checks...")
    check_row_counts(report, spark, borrowers_source, "loan_warehouse.borrowers", "Borrowers")
    check_row_counts(report, spark, products_source, "loan_warehouse.loan_products", "Loan Products")
    check_row_counts(report, spark, accounts_source, "loan_warehouse.loan_accounts", "Loan Accounts")
    check_row_counts(report, spark, payments_source, "loan_warehouse.payments", "Payments")

    logger.info("Running null checks on required fields...")
    check_null_required_fields(report, spark, "loan_warehouse.borrowers",
                               ["external_id", "first_name", "last_name"])
    check_null_required_fields(report, spark, "loan_warehouse.loan_products",
                               ["code", "name", "type", "term_months", "rate_type"])
    check_null_required_fields(report, spark, "loan_warehouse.loan_accounts",
                               ["account_number", "borrower_key", "product_key",
                                "original_amount", "current_balance", "interest_rate",
                                "term_months", "monthly_payment", "origination_date",
                                "maturity_date"])
    check_null_required_fields(report, spark, "loan_warehouse.payments",
                               ["loan_account_key", "payment_date", "total_amount",
                                "type", "status"])

    logger.info("Running referential integrity checks...")
    check_referential_integrity(report, spark)

    logger.info("Running business rule validation...")
    check_business_rules(report, spark)

    logger.info("Running status code expansion checks...")
    check_status_code_expansion(report, spark)

    logger.info("Running uniqueness checks...")
    check_uniqueness(report, spark)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run data quality checks after migration")
    parser.add_argument("--borrowers-source", required=True, help="Path to CDW_BORR_MSTR source")
    parser.add_argument("--products-source", required=True, help="Path to CDW_LN_PROD source")
    parser.add_argument("--accounts-source", required=True, help="Path to CDW_LN_ACCT source")
    parser.add_argument("--payments-source", required=True, help="Path to CDW_PMT_HIST source")
    parser.add_argument("--output", default="DATA_QUALITY_REPORT.md", help="Output report path")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Data_Quality_Checks").getOrCreate()

    try:
        report = run_all_checks(
            spark,
            args.borrowers_source,
            args.products_source,
            args.accounts_source,
            args.payments_source,
        )

        md = generate_markdown_report(report)

        # Write to DBFS or local path
        dbutils = None
        try:
            dbutils = spark._jvm.com.databricks.dbutils_v1.DBUtilsHolder.dbutils()
        except Exception:
            pass

        if dbutils and args.output.startswith("dbfs:"):
            dbutils.fs.put(args.output, md, overwrite=True)
        else:
            with open(args.output, "w") as f:
                f.write(md)

        logger.info("Report written to %s", args.output)
        logger.info("Passed: %d / %d", report.passed_count, report.total)

        if report.failed_count > 0:
            logger.error("%d check(s) FAILED — review the report", report.failed_count)

    except Exception:
        logger.exception("Data quality checks failed")
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
