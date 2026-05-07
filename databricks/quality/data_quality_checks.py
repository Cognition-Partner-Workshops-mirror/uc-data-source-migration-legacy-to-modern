"""
Data Quality Framework for the CDW-to-Delta-Lake migration.

Runs post-ingestion validation checks against the Delta Lake target tables:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts and borrowers / loan_products
  4. Referential integrity between payments and loan_accounts
  5. Business rule validation (balance > 0 for active loans, etc.)

Produces a structured results list that can be rendered into a Markdown report.

Usage:
    spark-submit data_quality_checks.py \
        --source-borrowers  /mnt/legacy/CDW_BORR_MSTR.csv \
        --source-products   /mnt/legacy/CDW_LN_PROD.csv \
        --source-accounts   /mnt/legacy/CDW_LN_ACCT.csv \
        --source-payments   /mnt/legacy/CDW_PMT_HIST.csv \
        --output-report     /mnt/reports/DATA_QUALITY_REPORT.md
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dq_checks")


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    category: str
    check_name: str
    table: str
    passed: bool
    details: str
    violation_count: int = 0


@dataclass
class QualityReport:
    results: list[CheckResult] = field(default_factory=list)
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def add(self, result: CheckResult) -> None:
        status = "PASS" if result.passed else "FAIL"
        logger.info("[%s] %s / %s -- %s", status, result.category, result.check_name, result.details)
        self.results.append(result)

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
# 1. Row count reconciliation
# ---------------------------------------------------------------------------


def check_row_counts(
    report: QualityReport,
    spark: SparkSession,
    source_path: str,
    target_table: str,
    table_label: str,
) -> None:
    """Compare row counts between a legacy CSV source and the Delta target table."""
    source_df = spark.read.option("header", "true").csv(source_path)
    target_df = spark.table(target_table)

    source_count = source_df.count()
    target_count = target_df.count()
    match = source_count == target_count

    report.add(CheckResult(
        category="Row Count",
        check_name=f"{table_label} count reconciliation",
        table=target_table,
        passed=match,
        details=f"Source: {source_count}, Target: {target_count}",
        violation_count=abs(source_count - target_count),
    ))


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------


def check_nulls(
    report: QualityReport,
    spark: SparkSession,
    target_table: str,
    required_columns: list[str],
) -> None:
    """Check that required columns contain no NULL values."""
    df = spark.table(target_table)
    for col_name in required_columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        report.add(CheckResult(
            category="Null Check",
            check_name=f"{col_name} NOT NULL",
            table=target_table,
            passed=null_count == 0,
            details=f"{null_count} null(s) found in '{col_name}'",
            violation_count=null_count,
        ))


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------


def check_referential_integrity(
    report: QualityReport,
    spark: SparkSession,
    child_table: str,
    child_col: str,
    parent_table: str,
    parent_col: str,
    check_label: str,
) -> None:
    """Verify every child FK value has a matching parent record."""
    child_df = spark.table(child_table).select(F.col(child_col).alias("fk_val")).distinct()
    parent_df = spark.table(parent_table).select(F.col(parent_col).alias("pk_val")).distinct()

    orphans = child_df.join(parent_df, child_df["fk_val"] == parent_df["pk_val"], "left_anti")
    orphan_count = orphans.count()

    report.add(CheckResult(
        category="Referential Integrity",
        check_name=check_label,
        table=child_table,
        passed=orphan_count == 0,
        details=f"{orphan_count} orphan(s) in {child_table}.{child_col} with no match in {parent_table}.{parent_col}",
        violation_count=orphan_count,
    ))


# ---------------------------------------------------------------------------
# 4. Business rule validations
# ---------------------------------------------------------------------------


def check_active_loan_positive_balance(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """Active loans must have a current balance > 0."""
    df = spark.table("loan_warehouse.loan_accounts")
    violations = df.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    )
    count = violations.count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans have positive balance",
        table="loan_warehouse.loan_accounts",
        passed=count == 0,
        details=f"{count} active loan(s) with balance <= 0",
        violation_count=count,
    ))


def check_closed_loan_has_status(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """Closed loans should exist (basic check that status expansion worked)."""
    df = spark.table("loan_warehouse.loan_accounts")
    valid_statuses = {"ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE"}
    invalid = df.filter(~F.col("status").isin(list(valid_statuses)))
    count = invalid.count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Loan status values are valid",
        table="loan_warehouse.loan_accounts",
        passed=count == 0,
        details=f"{count} loan(s) with unrecognized status values",
        violation_count=count,
    ))


def check_payment_amounts_positive(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """Posted payments must have total_amount > 0."""
    df = spark.table("loan_warehouse.payments")
    violations = df.filter(
        (F.col("status") == "POSTED") & (F.col("total_amount") <= 0)
    )
    count = violations.count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Posted payments have positive total amount",
        table="loan_warehouse.payments",
        passed=count == 0,
        details=f"{count} posted payment(s) with total_amount <= 0",
        violation_count=count,
    ))


def check_payment_component_sum(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """
    For each payment, principal + interest + escrow + late_fee should
    approximately equal total_amount (within $0.02 tolerance for rounding).
    """
    df = spark.table("loan_warehouse.payments")
    df_with_sum = df.withColumn(
        "component_sum",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0)),
    )
    violations = df_with_sum.filter(
        F.abs(F.col("total_amount") - F.col("component_sum")) > 0.02
    )
    count = violations.count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Payment component sum matches total",
        table="loan_warehouse.payments",
        passed=count == 0,
        details=f"{count} payment(s) where principal+interest+escrow+late_fee differs from total_amount by >$0.02",
        violation_count=count,
    ))


def check_origination_before_maturity(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """Loan origination_date must be before maturity_date."""
    df = spark.table("loan_warehouse.loan_accounts")
    violations = df.filter(F.col("origination_date") >= F.col("maturity_date"))
    count = violations.count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Origination date precedes maturity date",
        table="loan_warehouse.loan_accounts",
        passed=count == 0,
        details=f"{count} loan(s) where origination_date >= maturity_date",
        violation_count=count,
    ))


def check_credit_score_range(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """Credit scores should be in valid range 300-850."""
    df = spark.table("loan_warehouse.borrowers")
    violations = df.filter(
        F.col("credit_score").isNotNull()
        & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    )
    count = violations.count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="Credit score in valid range (300-850)",
        table="loan_warehouse.borrowers",
        passed=count == 0,
        details=f"{count} borrower(s) with credit_score outside 300-850",
        violation_count=count,
    ))


def check_ltv_range(
    report: QualityReport,
    spark: SparkSession,
) -> None:
    """LTV percent should be between 0 and 200 (reasonable upper bound)."""
    df = spark.table("loan_warehouse.loan_accounts")
    violations = df.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    )
    count = violations.count()
    report.add(CheckResult(
        category="Business Rule",
        check_name="LTV percent in valid range (0-200)",
        table="loan_warehouse.loan_accounts",
        passed=count == 0,
        details=f"{count} loan(s) with ltv_percent outside 0-200",
        violation_count=count,
    ))


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------


def generate_markdown_report(report: QualityReport) -> str:
    """Render the QualityReport as a Markdown document."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run timestamp:** {report.run_timestamp}",
        "",
        f"**Total checks:** {report.total}  |  "
        f"**Passed:** {report.passed}  |  "
        f"**Failed:** {report.failed}",
        "",
    ]

    # Group by category
    categories: dict[str, list[CheckResult]] = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for category, checks in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Check | Table | Result | Details | Violations |")
        lines.append("|-------|-------|--------|---------|------------|")
        for c in checks:
            result_str = "PASS" if c.passed else "**FAIL**"
            lines.append(f"| {c.check_name} | `{c.table}` | {result_str} | {c.details} | {c.violation_count} |")
        lines.append("")

    # Summary
    if report.failed == 0:
        lines.append("## Summary")
        lines.append("")
        lines.append("All data quality checks passed. The migration data is ready for downstream consumption.")
    else:
        lines.append("## Summary")
        lines.append("")
        lines.append(f"**{report.failed} check(s) failed.** Review the failures above and remediate before promoting data to production.")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_all_checks(
    spark: SparkSession,
    source_borrowers: str,
    source_products: str,
    source_accounts: str,
    source_payments: str,
) -> QualityReport:
    """Execute the complete data quality check suite."""
    report = QualityReport()

    # 1. Row count reconciliation
    logger.info("=" * 60)
    logger.info("PHASE 1: Row Count Reconciliation")
    logger.info("=" * 60)
    check_row_counts(report, spark, source_borrowers, "loan_warehouse.borrowers", "borrowers")
    check_row_counts(report, spark, source_products, "loan_warehouse.loan_products", "loan_products")
    check_row_counts(report, spark, source_accounts, "loan_warehouse.loan_accounts", "loan_accounts")
    check_row_counts(report, spark, source_payments, "loan_warehouse.payments", "payments")

    # 2. Null checks on required fields
    logger.info("=" * 60)
    logger.info("PHASE 2: Null Checks on Required Fields")
    logger.info("=" * 60)
    check_nulls(report, spark, "loan_warehouse.borrowers", ["external_id", "first_name", "last_name", "status"])
    check_nulls(report, spark, "loan_warehouse.loan_products", ["code", "name", "type", "term_months", "rate_type"])
    check_nulls(report, spark, "loan_warehouse.loan_accounts", [
        "account_number", "borrower_external_id", "product_code",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date", "status",
    ])
    check_nulls(report, spark, "loan_warehouse.payments", [
        "loan_account_number", "payment_date", "total_amount", "type", "status",
    ])

    # 3. Referential integrity
    logger.info("=" * 60)
    logger.info("PHASE 3: Referential Integrity")
    logger.info("=" * 60)
    check_referential_integrity(
        report, spark,
        "loan_warehouse.loan_accounts", "borrower_external_id",
        "loan_warehouse.borrowers", "external_id",
        "loan_accounts.borrower_external_id -> borrowers.external_id",
    )
    check_referential_integrity(
        report, spark,
        "loan_warehouse.loan_accounts", "product_code",
        "loan_warehouse.loan_products", "code",
        "loan_accounts.product_code -> loan_products.code",
    )
    check_referential_integrity(
        report, spark,
        "loan_warehouse.payments", "loan_account_number",
        "loan_warehouse.loan_accounts", "account_number",
        "payments.loan_account_number -> loan_accounts.account_number",
    )

    # 4. Business rules
    logger.info("=" * 60)
    logger.info("PHASE 4: Business Rule Validation")
    logger.info("=" * 60)
    check_active_loan_positive_balance(report, spark)
    check_closed_loan_has_status(report, spark)
    check_payment_amounts_positive(report, spark)
    check_payment_component_sum(report, spark)
    check_origination_before_maturity(report, spark)
    check_credit_score_range(report, spark)
    check_ltv_range(report, spark)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run post-ingestion data quality checks")
    parser.add_argument("--source-borrowers", required=True, help="Path to legacy CDW_BORR_MSTR CSV")
    parser.add_argument("--source-products", required=True, help="Path to legacy CDW_LN_PROD CSV")
    parser.add_argument("--source-accounts", required=True, help="Path to legacy CDW_LN_ACCT CSV")
    parser.add_argument("--source-payments", required=True, help="Path to legacy CDW_PMT_HIST CSV")
    parser.add_argument("--output-report", default="/mnt/reports/DATA_QUALITY_REPORT.md", help="Path to write the Markdown report")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_DataQuality").getOrCreate()

    try:
        report = run_all_checks(
            spark,
            args.source_borrowers,
            args.source_products,
            args.source_accounts,
            args.source_payments,
        )

        md_content = generate_markdown_report(report)

        # Write report using Spark's Hadoop filesystem (works on DBFS/S3/ADLS)
        # For local paths, write directly
        logger.info("Writing report to: %s", args.output_report)
        spark.sparkContext.parallelize([md_content]).coalesce(1).saveAsTextFile(args.output_report + "_tmp")

        # Also print to stdout for notebook display
        print(md_content)

        if report.failed > 0:
            logger.error("Data quality checks completed with %d failure(s).", report.failed)
            sys.exit(1)
        else:
            logger.info("All %d data quality checks passed.", report.total)

    except Exception:
        logger.exception("Data quality check execution failed")
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
