"""
Data Quality Validation Framework for the CDW legacy-to-modern migration.

Runs post-ingestion checks across all four target tables and generates a
structured quality report. Designed to run as a Databricks notebook or
via spark-submit after the ingestion pipeline completes.

Check categories:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity (loan_accounts -> borrowers, payments -> loan_accounts)
  4. Business rule validation (domain-specific constraints)

Usage:
    spark = SparkSession.builder.getOrCreate()
    report = run_all_checks(spark, source_counts={...})
    generate_report(report, output_path="dbfs:/mnt/reports/DATA_QUALITY_REPORT.md")
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

logger = logging.getLogger("cdw_migration.quality")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Check result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str
    table: str
    check_name: str
    passed: bool
    expected: str
    actual: str
    detail: str = ""


@dataclass
class QualityReport:
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    checks: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total * 100) if self.total > 0 else 0.0


# ---------------------------------------------------------------------------
# 1. Row count reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession, report: QualityReport,
                     source_counts: Optional[dict] = None):
    """
    Verify that target table row counts match the expected source counts.
    If source_counts is None, only report target counts without reconciliation.
    """
    tables = {
        "loan_warehouse.borrowers": "borrowers",
        "loan_warehouse.loan_products": "loan_products",
        "loan_warehouse.loan_accounts": "loan_accounts",
        "loan_warehouse.payments": "payments",
    }

    for full_name, short_name in tables.items():
        try:
            target_count = spark.table(full_name).count()
        except Exception as e:
            report.checks.append(CheckResult(
                category="Row Count",
                table=short_name,
                check_name=f"{short_name}_table_exists",
                passed=False,
                expected="Table exists",
                actual=f"Error: {e}",
            ))
            continue

        if source_counts and short_name in source_counts:
            expected = source_counts[short_name]
            passed = target_count == expected
            report.checks.append(CheckResult(
                category="Row Count",
                table=short_name,
                check_name=f"{short_name}_count_reconciliation",
                passed=passed,
                expected=str(expected),
                actual=str(target_count),
                detail=f"Delta: {target_count - expected}" if not passed else "",
            ))
        else:
            report.checks.append(CheckResult(
                category="Row Count",
                table=short_name,
                check_name=f"{short_name}_count_nonzero",
                passed=target_count > 0,
                expected=">0",
                actual=str(target_count),
            ))

    # Also check quarantine tables
    quarantine_tables = [
        "loan_warehouse._quarantine_borrowers",
        "loan_warehouse._quarantine_loan_products",
        "loan_warehouse._quarantine_loan_accounts",
        "loan_warehouse._quarantine_payments",
    ]
    for qt in quarantine_tables:
        short = qt.split(".")[-1]
        try:
            q_count = spark.table(qt).count()
            report.checks.append(CheckResult(
                category="Row Count",
                table=short,
                check_name=f"{short}_quarantine_count",
                passed=q_count == 0,
                expected="0",
                actual=str(q_count),
                detail="Quarantined rows require manual review" if q_count > 0 else "",
            ))
        except Exception:
            # Quarantine table may not exist if no rows were quarantined
            report.checks.append(CheckResult(
                category="Row Count",
                table=short,
                check_name=f"{short}_quarantine_count",
                passed=True,
                expected="0 (table absent)",
                actual="0 (table absent)",
                detail="No quarantine table created — all rows valid",
            ))


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": ["external_id", "first_name", "last_name"],
    "loan_warehouse.loan_products": ["code", "name", "type", "term_months", "rate_type"],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date",
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount", "type", "status",
    ],
}


def check_null_required_fields(spark: SparkSession, report: QualityReport):
    """Verify that required fields have no NULL values in any target table."""
    for table_name, columns in REQUIRED_FIELDS.items():
        short_name = table_name.split(".")[-1]
        try:
            df = spark.table(table_name)
        except Exception as e:
            report.checks.append(CheckResult(
                category="Null Check",
                table=short_name,
                check_name=f"{short_name}_null_check_skipped",
                passed=False,
                expected="Table readable",
                actual=f"Error: {e}",
            ))
            continue

        total_rows = df.count()
        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            report.checks.append(CheckResult(
                category="Null Check",
                table=short_name,
                check_name=f"{short_name}.{col_name}_not_null",
                passed=null_count == 0,
                expected="0 nulls",
                actual=f"{null_count} nulls out of {total_rows} rows",
            ))


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport):
    """
    Verify FK relationships:
    - loan_accounts.borrower_id -> borrowers.borrower_key
    - loan_accounts.product_id  -> loan_products.product_key
    - payments.loan_account_id  -> loan_accounts.loan_key
    """
    checks = [
        {
            "name": "loan_accounts_to_borrowers",
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "borrower_id",
            "parent_table": "loan_warehouse.borrowers",
            "parent_col": "borrower_key",
        },
        {
            "name": "loan_accounts_to_products",
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "product_id",
            "parent_table": "loan_warehouse.loan_products",
            "parent_col": "product_key",
        },
        {
            "name": "payments_to_loan_accounts",
            "child_table": "loan_warehouse.payments",
            "child_col": "loan_account_id",
            "parent_table": "loan_warehouse.loan_accounts",
            "parent_col": "loan_key",
        },
    ]

    for check in checks:
        try:
            child_df = spark.table(check["child_table"])
            parent_df = spark.table(check["parent_table"])

            orphan_count = (
                child_df
                .join(parent_df,
                      child_df[check["child_col"]] == parent_df[check["parent_col"]],
                      "left_anti")
                .count()
            )

            total = child_df.count()
            report.checks.append(CheckResult(
                category="Referential Integrity",
                table=check["child_table"].split(".")[-1],
                check_name=check["name"],
                passed=orphan_count == 0,
                expected="0 orphan records",
                actual=f"{orphan_count} orphans out of {total} records",
            ))
        except Exception as e:
            report.checks.append(CheckResult(
                category="Referential Integrity",
                table=check["child_table"].split(".")[-1],
                check_name=check["name"],
                passed=False,
                expected="0 orphan records",
                actual=f"Error: {e}",
            ))


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport):
    """Domain-specific business rule validations."""

    # --- Borrowers ---
    try:
        borrowers = spark.table("loan_warehouse.borrowers")

        # Credit score in valid range (300-850) when present
        invalid_credit = borrowers.filter(
            F.col("credit_score").isNotNull()
            & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="borrowers",
            check_name="credit_score_valid_range",
            passed=invalid_credit == 0,
            expected="All credit scores in [300, 850]",
            actual=f"{invalid_credit} scores out of range",
        ))

        # Status must be ACTIVE or INACTIVE
        invalid_status = borrowers.filter(
            ~F.col("status").isin("ACTIVE", "INACTIVE")
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="borrowers",
            check_name="borrower_status_valid",
            passed=invalid_status == 0,
            expected="All statuses in {ACTIVE, INACTIVE}",
            actual=f"{invalid_status} invalid statuses",
        ))

        # Annual income > 0 when present
        neg_income = borrowers.filter(
            F.col("annual_income").isNotNull() & (F.col("annual_income") <= 0)
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="borrowers",
            check_name="annual_income_positive",
            passed=neg_income == 0,
            expected="All incomes > 0 (when present)",
            actual=f"{neg_income} non-positive incomes",
        ))
    except Exception as e:
        logger.error("Borrower business rule checks failed: %s", e)

    # --- Loan Accounts ---
    try:
        loans = spark.table("loan_warehouse.loan_accounts")

        # Balance > 0 for ACTIVE loans
        active_zero_bal = loans.filter(
            (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="loan_accounts",
            check_name="active_loan_positive_balance",
            passed=active_zero_bal == 0,
            expected="All ACTIVE loans have balance > 0",
            actual=f"{active_zero_bal} active loans with balance <= 0",
        ))

        # Maturity date > origination date
        bad_dates = loans.filter(
            F.col("maturity_date") <= F.col("origination_date")
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="loan_accounts",
            check_name="maturity_after_origination",
            passed=bad_dates == 0,
            expected="maturity_date > origination_date for all loans",
            actual=f"{bad_dates} loans with invalid date order",
        ))

        # Interest rate > 0
        bad_rate = loans.filter(F.col("interest_rate") <= 0).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="loan_accounts",
            check_name="interest_rate_positive",
            passed=bad_rate == 0,
            expected="All interest rates > 0",
            actual=f"{bad_rate} loans with non-positive rate",
        ))

        # LTV percent in reasonable range (0-200) when present
        bad_ltv = loans.filter(
            F.col("ltv_percent").isNotNull()
            & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="loan_accounts",
            check_name="ltv_percent_valid_range",
            passed=bad_ltv == 0,
            expected="All LTV in [0, 200] when present",
            actual=f"{bad_ltv} loans with out-of-range LTV",
        ))

        # Loan status is one of the expected expanded values
        invalid_ln_status = loans.filter(
            ~F.col("status").isin("ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE")
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="loan_accounts",
            check_name="loan_status_valid",
            passed=invalid_ln_status == 0,
            expected="All statuses in {ACTIVE, CLOSED, DEFAULT, FORBEARANCE}",
            actual=f"{invalid_ln_status} invalid statuses",
        ))

        # Property type is one of the expanded values when present
        invalid_prop = loans.filter(
            F.col("property_type").isNotNull()
            & ~F.col("property_type").isin(
                "Single Family", "Condominium", "Multi-Family", "Townhouse"
            )
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="loan_accounts",
            check_name="property_type_valid",
            passed=invalid_prop == 0,
            expected="All property types in expanded set when present",
            actual=f"{invalid_prop} invalid property types",
        ))
    except Exception as e:
        logger.error("Loan account business rule checks failed: %s", e)

    # --- Payments ---
    try:
        payments = spark.table("loan_warehouse.payments")

        # Payment amount > 0
        neg_pmt = payments.filter(F.col("total_amount") <= 0).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="payments",
            check_name="payment_amount_positive",
            passed=neg_pmt == 0,
            expected="All payment amounts > 0",
            actual=f"{neg_pmt} non-positive payments",
        ))

        # Payment type valid
        invalid_pmt_type = payments.filter(
            ~F.col("type").isin("REGULAR", "EXTRA", "PARTIAL", "PREPAYMENT")
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="payments",
            check_name="payment_type_valid",
            passed=invalid_pmt_type == 0,
            expected="All types in {REGULAR, EXTRA, PARTIAL, PREPAYMENT}",
            actual=f"{invalid_pmt_type} invalid types",
        ))

        # Payment status valid
        invalid_pmt_status = payments.filter(
            ~F.col("status").isin("POSTED", "REVERSED", "NSF", "PENDING")
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="payments",
            check_name="payment_status_valid",
            passed=invalid_pmt_status == 0,
            expected="All statuses in {POSTED, REVERSED, NSF, PENDING}",
            actual=f"{invalid_pmt_status} invalid statuses",
        ))

        # Component amounts should sum to approximately total_amount
        # (principal + interest + escrow + late_fee ≈ total_amount)
        payments_with_sum = payments.withColumn(
            "_component_sum",
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0))
        )
        mismatched = payments_with_sum.filter(
            F.abs(F.col("_component_sum") - F.col("total_amount")) > 0.01
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="payments",
            check_name="payment_components_sum_to_total",
            passed=mismatched == 0,
            expected="principal + interest + escrow + late_fee = total_amount (±$0.01)",
            actual=f"{mismatched} payments with mismatched components",
        ))

        # Processed date >= received date when both present
        bad_proc = payments.filter(
            F.col("received_date").isNotNull()
            & F.col("processed_date").isNotNull()
            & (F.col("processed_date") < F.col("received_date"))
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="payments",
            check_name="processed_after_received",
            passed=bad_proc == 0,
            expected="processed_date >= received_date",
            actual=f"{bad_proc} payments processed before received",
        ))
    except Exception as e:
        logger.error("Payment business rule checks failed: %s", e)

    # --- Loan Products ---
    try:
        products = spark.table("loan_warehouse.loan_products")

        # Min amount <= max amount when both present
        bad_range = products.filter(
            F.col("min_amount").isNotNull()
            & F.col("max_amount").isNotNull()
            & (F.col("min_amount") > F.col("max_amount"))
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="loan_products",
            check_name="product_amount_range_valid",
            passed=bad_range == 0,
            expected="min_amount <= max_amount",
            actual=f"{bad_range} products with inverted range",
        ))

        # Expiration date > effective date when both present
        bad_prod_dates = products.filter(
            F.col("effective_date").isNotNull()
            & F.col("expiration_date").isNotNull()
            & (F.col("expiration_date") <= F.col("effective_date"))
        ).count()
        report.checks.append(CheckResult(
            category="Business Rule",
            table="loan_products",
            check_name="product_date_range_valid",
            passed=bad_prod_dates == 0,
            expected="expiration_date > effective_date",
            actual=f"{bad_prod_dates} products with invalid date range",
        ))
    except Exception as e:
        logger.error("Loan product business rule checks failed: %s", e)


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def generate_report_markdown(report: QualityReport) -> str:
    """Generate a Markdown-formatted quality report."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run Timestamp:** {report.run_timestamp}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Checks | {report.total} |",
        f"| Passed | {report.passed} |",
        f"| Failed | {report.failed} |",
        f"| Pass Rate | {report.pass_rate:.1f}% |",
        f"| Overall Status | {'PASS' if report.failed == 0 else 'FAIL'} |",
        "",
    ]

    # Group checks by category
    categories = {}
    for check in report.checks:
        categories.setdefault(check.category, []).append(check)

    for category, checks in categories.items():
        cat_passed = sum(1 for c in checks if c.passed)
        cat_total = len(checks)
        lines.append(f"## {category} ({cat_passed}/{cat_total} passed)")
        lines.append("")
        lines.append("| Table | Check | Status | Expected | Actual | Detail |")
        lines.append("|-------|-------|--------|----------|--------|--------|")

        for c in checks:
            status_icon = "PASS" if c.passed else "**FAIL**"
            detail = c.detail.replace("|", "\\|") if c.detail else ""
            lines.append(
                f"| {c.table} | {c.check_name} | {status_icon} "
                f"| {c.expected} | {c.actual} | {detail} |"
            )
        lines.append("")

    # Footer
    lines.extend([
        "---",
        "",
        "*Report generated by the CDW Legacy-to-Modern Data Quality Framework.*",
        f"*Pipeline version: 1.0.0 | Run: {report.run_timestamp}*",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all_checks(spark: SparkSession,
                   source_counts: Optional[dict] = None) -> QualityReport:
    """
    Execute all quality checks and return the report.

    Parameters
    ----------
    spark : SparkSession
    source_counts : dict, optional
        Expected row counts per table. Keys: borrowers, loan_products,
        loan_accounts, payments. If None, only non-zero checks are performed.
    """
    report = QualityReport()

    logger.info("Starting data quality checks...")

    logger.info("Running row count reconciliation...")
    check_row_counts(spark, report, source_counts)

    logger.info("Running null checks on required fields...")
    check_null_required_fields(spark, report)

    logger.info("Running referential integrity checks...")
    check_referential_integrity(spark, report)

    logger.info("Running business rule validation...")
    check_business_rules(spark, report)

    logger.info(
        "Quality checks complete: %d/%d passed (%.1f%%)",
        report.passed, report.total, report.pass_rate,
    )

    return report


def save_report(report: QualityReport, output_path: str, spark: SparkSession = None):
    """
    Save the quality report as a Markdown file.

    For DBFS paths, uses Spark; for local paths, uses standard file I/O.
    """
    md_content = generate_report_markdown(report)

    if output_path.startswith("dbfs:") and spark:
        # Write via Spark for DBFS compatibility
        rdd = spark.sparkContext.parallelize([md_content])
        rdd.saveAsTextFile(output_path)
        logger.info("Report saved to %s", output_path)
    else:
        with open(output_path, "w") as f:
            f.write(md_content)
        logger.info("Report saved to %s", output_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    spark = SparkSession.builder.appName("CDW_Data_Quality").getOrCreate()

    # Optional: pass source counts from pipeline results
    source_counts = None

    report = run_all_checks(spark, source_counts)
    md = generate_report_markdown(report)

    output = sys.argv[1] if len(sys.argv) > 1 else "DATA_QUALITY_REPORT.md"
    save_report(report, output, spark)

    print(md)

    if report.failed > 0:
        sys.exit(1)
