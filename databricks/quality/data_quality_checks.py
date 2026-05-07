"""
Data Quality Framework for CDW-to-Delta-Lake Loan Migration.

Runs post-ingestion validation checks:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan and borrower tables
  4. Business rule validation (loan-specific invariants)

Results are collected into a structured report and written to
DATA_QUALITY_REPORT.md.

Usage:
    spark-submit data_quality_checks.py \\
        --landing-dir /mnt/landing \\
        --format csv \\
        --output-path /mnt/reports/DATA_QUALITY_REPORT.md
"""

import argparse
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import List

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("data_quality_checks")


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str
    check_name: str
    status: str  # PASS / FAIL / WARN
    detail: str


@dataclass
class QualityReport:
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    results: List[CheckResult] = field(default_factory=list)

    def add(self, category: str, name: str, status: str, detail: str) -> None:
        self.results.append(CheckResult(category, name, status, detail))
        level = logging.WARNING if status == "FAIL" else logging.INFO
        logger.log(level, "[%s] %s: %s — %s", category, name, status, detail)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")

    @property
    def total(self) -> int:
        return len(self.results)


# ---------------------------------------------------------------------------
# 1. Row count reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(
    spark: SparkSession,
    report: QualityReport,
    landing_dir: str,
    source_format: str,
) -> None:
    """Compare source file row counts against target Delta table row counts."""
    tables = [
        ("cdw_borr_mstr", "loan_warehouse.borrowers", "Borrowers"),
        ("cdw_ln_prod", "loan_warehouse.loan_products", "Loan Products"),
        ("cdw_ln_acct", "loan_warehouse.loan_accounts", "Loan Accounts"),
        ("cdw_pmt_hist", "loan_warehouse.payments", "Payments"),
    ]

    for source_name, target_table, label in tables:
        source_path = f"{landing_dir}/{source_name}"
        try:
            reader = spark.read.format(source_format)
            if source_format == "csv":
                reader = reader.option("header", "true")
            source_count = reader.load(source_path).count()
            target_count = spark.table(target_table).count()

            if source_count == target_count:
                report.add(
                    "Row Count",
                    f"{label} count match",
                    "PASS",
                    f"Source={source_count}, Target={target_count}",
                )
            else:
                report.add(
                    "Row Count",
                    f"{label} count match",
                    "FAIL",
                    f"Source={source_count}, Target={target_count} (delta={target_count - source_count})",
                )
        except Exception as e:
            report.add("Row Count", f"{label} count match", "FAIL", f"Error: {e}")


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": [
        "external_id", "first_name", "last_name", "status",
    ],
    "loan_warehouse.loan_products": [
        "code", "name", "type", "term_months", "rate_type", "is_active",
    ],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_external_id", "product_code",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "status",
    ],
    "loan_warehouse.payments": [
        "legacy_payment_id", "loan_account_number", "payment_date",
        "total_amount", "type", "status",
    ],
}


def check_required_nulls(spark: SparkSession, report: QualityReport) -> None:
    """Verify that required columns contain no NULL values."""
    for table_name, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table_name)
            for col_name in columns:
                null_count = df.filter(F.col(col_name).isNull()).count()
                short_table = table_name.split(".")[-1]
                if null_count == 0:
                    report.add(
                        "Null Check",
                        f"{short_table}.{col_name} NOT NULL",
                        "PASS",
                        "No nulls found",
                    )
                else:
                    report.add(
                        "Null Check",
                        f"{short_table}.{col_name} NOT NULL",
                        "FAIL",
                        f"{null_count} null(s) found",
                    )
        except Exception as e:
            report.add("Null Check", f"{table_name} null checks", "FAIL", f"Error: {e}")


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Check FK relationships between loan accounts, borrowers, products, and payments."""

    # loan_accounts.borrower_external_id -> borrowers.external_id
    try:
        loans = spark.table("loan_warehouse.loan_accounts")
        borrowers = spark.table("loan_warehouse.borrowers")

        orphan_borrower_refs = (
            loans.select("borrower_external_id")
            .distinct()
            .join(
                borrowers.select(F.col("external_id").alias("borrower_external_id")),
                on="borrower_external_id",
                how="left_anti",
            )
        )
        orphan_count = orphan_borrower_refs.count()
        if orphan_count == 0:
            report.add(
                "Referential Integrity",
                "loan_accounts.borrower_external_id -> borrowers.external_id",
                "PASS",
                "All borrower references valid",
            )
        else:
            orphan_ids = [row.borrower_external_id for row in orphan_borrower_refs.collect()]
            report.add(
                "Referential Integrity",
                "loan_accounts.borrower_external_id -> borrowers.external_id",
                "FAIL",
                f"{orphan_count} orphan(s): {orphan_ids[:10]}",
            )
    except Exception as e:
        report.add("Referential Integrity", "loan -> borrower FK", "FAIL", f"Error: {e}")

    # loan_accounts.product_code -> loan_products.code
    try:
        products = spark.table("loan_warehouse.loan_products")

        orphan_product_refs = (
            loans.select("product_code")
            .distinct()
            .join(
                products.select(F.col("code").alias("product_code")),
                on="product_code",
                how="left_anti",
            )
        )
        orphan_count = orphan_product_refs.count()
        if orphan_count == 0:
            report.add(
                "Referential Integrity",
                "loan_accounts.product_code -> loan_products.code",
                "PASS",
                "All product references valid",
            )
        else:
            orphan_codes = [row.product_code for row in orphan_product_refs.collect()]
            report.add(
                "Referential Integrity",
                "loan_accounts.product_code -> loan_products.code",
                "FAIL",
                f"{orphan_count} orphan(s): {orphan_codes[:10]}",
            )
    except Exception as e:
        report.add("Referential Integrity", "loan -> product FK", "FAIL", f"Error: {e}")

    # payments.loan_account_number -> loan_accounts.account_number
    try:
        payments = spark.table("loan_warehouse.payments")

        orphan_loan_refs = (
            payments.select("loan_account_number")
            .distinct()
            .join(
                loans.select(F.col("account_number").alias("loan_account_number")),
                on="loan_account_number",
                how="left_anti",
            )
        )
        orphan_count = orphan_loan_refs.count()
        if orphan_count == 0:
            report.add(
                "Referential Integrity",
                "payments.loan_account_number -> loan_accounts.account_number",
                "PASS",
                "All loan references valid",
            )
        else:
            orphan_nums = [row.loan_account_number for row in orphan_loan_refs.collect()]
            report.add(
                "Referential Integrity",
                "payments.loan_account_number -> loan_accounts.account_number",
                "FAIL",
                f"{orphan_count} orphan(s): {orphan_nums[:10]}",
            )
    except Exception as e:
        report.add("Referential Integrity", "payment -> loan FK", "FAIL", f"Error: {e}")


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules for loan data."""

    try:
        loans = spark.table("loan_warehouse.loan_accounts")
    except Exception as e:
        report.add("Business Rules", "Load loan_accounts", "FAIL", f"Error: {e}")
        return

    # Rule 1: Active loans must have positive current balance
    try:
        active_non_positive = loans.filter(
            (F.col("status") == "Active") & (F.col("current_balance") <= 0)
        ).count()
        if active_non_positive == 0:
            report.add(
                "Business Rules",
                "Active loans have positive balance",
                "PASS",
                "All active loans have current_balance > 0",
            )
        else:
            report.add(
                "Business Rules",
                "Active loans have positive balance",
                "FAIL",
                f"{active_non_positive} active loan(s) with balance <= 0",
            )
    except Exception as e:
        report.add("Business Rules", "Active loan balance check", "FAIL", f"Error: {e}")

    # Rule 2: Closed loans should have a maturity_date on or before today
    #         (or origination_date in the past)
    try:
        closed_no_maturity = loans.filter(
            (F.col("status") == "Closed") & F.col("maturity_date").isNull()
        ).count()
        if closed_no_maturity == 0:
            report.add(
                "Business Rules",
                "Closed loans have maturity_date",
                "PASS",
                "All closed loans have maturity_date set",
            )
        else:
            report.add(
                "Business Rules",
                "Closed loans have maturity_date",
                "FAIL",
                f"{closed_no_maturity} closed loan(s) missing maturity_date",
            )
    except Exception as e:
        report.add("Business Rules", "Closed loan maturity check", "FAIL", f"Error: {e}")

    # Rule 3: Loan origination_date must be before maturity_date
    try:
        bad_dates = loans.filter(
            F.col("origination_date") >= F.col("maturity_date")
        ).count()
        if bad_dates == 0:
            report.add(
                "Business Rules",
                "origination_date < maturity_date",
                "PASS",
                "All loans have valid date ordering",
            )
        else:
            report.add(
                "Business Rules",
                "origination_date < maturity_date",
                "FAIL",
                f"{bad_dates} loan(s) with origination_date >= maturity_date",
            )
    except Exception as e:
        report.add("Business Rules", "Date ordering check", "FAIL", f"Error: {e}")

    # Rule 4: Interest rate must be between 0 and 100
    try:
        bad_rates = loans.filter(
            (F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)
        ).count()
        if bad_rates == 0:
            report.add(
                "Business Rules",
                "Interest rate in valid range (0-100)",
                "PASS",
                "All interest rates within bounds",
            )
        else:
            report.add(
                "Business Rules",
                "Interest rate in valid range (0-100)",
                "FAIL",
                f"{bad_rates} loan(s) with out-of-range interest rate",
            )
    except Exception as e:
        report.add("Business Rules", "Interest rate range check", "FAIL", f"Error: {e}")

    # Rule 5: LTV percent should be between 0 and 200 (if present)
    try:
        bad_ltv = loans.filter(
            F.col("ltv_percent").isNotNull()
            & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
        ).count()
        if bad_ltv == 0:
            report.add(
                "Business Rules",
                "LTV percent in valid range (0-200)",
                "PASS",
                "All LTV values within bounds",
            )
        else:
            report.add(
                "Business Rules",
                "LTV percent in valid range (0-200)",
                "FAIL",
                f"{bad_ltv} loan(s) with out-of-range LTV",
            )
    except Exception as e:
        report.add("Business Rules", "LTV range check", "FAIL", f"Error: {e}")

    # Rule 6: Payment total = principal + interest + escrow + late_fee (tolerance check)
    try:
        payments = spark.table("loan_warehouse.payments")
        tolerance = 0.02  # allow 2-cent rounding tolerance
        payments_with_check = payments.withColumn(
            "computed_total",
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0)),
        ).withColumn(
            "diff", F.abs(F.col("total_amount") - F.col("computed_total"))
        )
        mismatches = payments_with_check.filter(F.col("diff") > tolerance).count()
        if mismatches == 0:
            report.add(
                "Business Rules",
                "Payment amount components sum correctly",
                "PASS",
                f"All payments balance within {tolerance} tolerance",
            )
        else:
            report.add(
                "Business Rules",
                "Payment amount components sum correctly",
                "WARN",
                f"{mismatches} payment(s) with component sum mismatch > {tolerance}",
            )
    except Exception as e:
        report.add("Business Rules", "Payment sum check", "FAIL", f"Error: {e}")

    # Rule 7: Delinquency days must be non-negative
    try:
        negative_dlq = loans.filter(F.col("delinquency_days") < 0).count()
        if negative_dlq == 0:
            report.add(
                "Business Rules",
                "Delinquency days >= 0",
                "PASS",
                "All delinquency values non-negative",
            )
        else:
            report.add(
                "Business Rules",
                "Delinquency days >= 0",
                "FAIL",
                f"{negative_dlq} loan(s) with negative delinquency days",
            )
    except Exception as e:
        report.add("Business Rules", "Delinquency days check", "FAIL", f"Error: {e}")

    # Rule 8: Status values must be in expected set
    try:
        valid_statuses = {"Active", "Closed", "Default", "Forbearance"}
        actual_statuses = {row.status for row in loans.select("status").distinct().collect()}
        unexpected = actual_statuses - valid_statuses
        if not unexpected:
            report.add(
                "Business Rules",
                "Loan status values in expected set",
                "PASS",
                f"All statuses valid: {actual_statuses}",
            )
        else:
            report.add(
                "Business Rules",
                "Loan status values in expected set",
                "FAIL",
                f"Unexpected statuses: {unexpected}",
            )
    except Exception as e:
        report.add("Business Rules", "Status enum check", "FAIL", f"Error: {e}")


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report_markdown(report: QualityReport) -> str:
    """Render the quality report as a Markdown document."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run Timestamp:** {report.run_timestamp}",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Total Checks | {report.total} |",
        f"| Passed | {report.pass_count} |",
        f"| Failed | {report.fail_count} |",
        f"| Warnings | {report.warn_count} |",
        "",
        f"**Overall Status:** {'PASS' if report.fail_count == 0 else 'FAIL'}",
        "",
        "## Detailed Results",
        "",
        "| Category | Check | Status | Detail |",
        "|----------|-------|--------|--------|",
    ]

    for r in report.results:
        status_icon = {"PASS": "PASS", "FAIL": "**FAIL**", "WARN": "WARN"}[r.status]
        detail_escaped = r.detail.replace("|", "\\|")
        lines.append(f"| {r.category} | {r.check_name} | {status_icon} | {detail_escaped} |")

    lines.extend([
        "",
        "## Check Categories",
        "",
        "### Row Count Reconciliation",
        "Compares the number of rows in each legacy source file against the "
        "corresponding Delta Lake target table. A mismatch indicates records "
        "were dropped or duplicated during ingestion.",
        "",
        "### Null Checks",
        "Verifies that columns marked as NOT NULL in the target schema contain "
        "no null values after migration. Nulls in required fields indicate "
        "parse failures or missing source data.",
        "",
        "### Referential Integrity",
        "Validates foreign key relationships between tables:",
        "- `loan_accounts.borrower_external_id` references `borrowers.external_id`",
        "- `loan_accounts.product_code` references `loan_products.code`",
        "- `payments.loan_account_number` references `loan_accounts.account_number`",
        "",
        "### Business Rules",
        "Domain-specific validations for loan data:",
        "- Active loans must have a positive current balance",
        "- Closed loans must have a maturity date",
        "- Origination date must precede maturity date",
        "- Interest rate must be between 0% and 100%",
        "- LTV percent must be between 0% and 200%",
        "- Payment component amounts must sum to total (within rounding tolerance)",
        "- Delinquency days must be non-negative",
        "- Loan status values must be in the expected set",
        "",
        "---",
        f"*Generated by CDW Migration Data Quality Framework — {report.run_timestamp}*",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all_checks(
    landing_dir: str = "/mnt/landing",
    source_format: str = "csv",
    output_path: str = "/dbfs/mnt/reports/DATA_QUALITY_REPORT.md",
) -> QualityReport:
    """Execute all quality checks and generate the report."""
    spark = SparkSession.builder.appName("CDW_DataQuality").getOrCreate()

    report = QualityReport()

    logger.info("=" * 60)
    logger.info("Starting Data Quality Checks")
    logger.info("=" * 60)

    logger.info("--- Row Count Reconciliation ---")
    check_row_counts(spark, report, landing_dir, source_format)

    logger.info("--- Null Checks on Required Fields ---")
    check_required_nulls(spark, report)

    logger.info("--- Referential Integrity ---")
    check_referential_integrity(spark, report)

    logger.info("--- Business Rule Validation ---")
    check_business_rules(spark, report)

    # Generate markdown report
    md_content = generate_report_markdown(report)

    # Write to DBFS / local path
    try:
        with open(output_path.replace("/dbfs", ""), "w") as f:
            f.write(md_content)
        logger.info("Report written to %s", output_path)
    except Exception:
        logger.info("Could not write to %s, writing via Spark", output_path)
        spark.sparkContext.parallelize([md_content]).saveAsTextFile(output_path + "_tmp")

    logger.info("=" * 60)
    logger.info(
        "Quality Checks Complete: %d PASS, %d FAIL, %d WARN out of %d total",
        report.pass_count, report.fail_count, report.warn_count, report.total,
    )
    logger.info("=" * 60)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run data quality checks")
    parser.add_argument("--landing-dir", default="/mnt/landing")
    parser.add_argument("--format", default="csv")
    parser.add_argument(
        "--output-path",
        default="/dbfs/mnt/reports/DATA_QUALITY_REPORT.md",
    )
    args = parser.parse_args()
    run_all_checks(
        landing_dir=args.landing_dir,
        source_format=args.format,
        output_path=args.output_path,
    )
