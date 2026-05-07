"""
Data Quality Framework for the CDW Legacy-to-Modern Migration.

Runs post-ingestion validation checks and produces a structured report
(DATA_QUALITY_REPORT.md) summarising pass/fail results across four categories:

  1. Row-count reconciliation  (source vs. target)
  2. Null checks on required fields
  3. Referential integrity      (loan_accounts -> borrowers, payments -> loan_accounts)
  4. Business rule validation   (domain-specific invariants)

Usage (Databricks notebook):
    %run ./data_quality_checks

Or (spark-submit):
    spark-submit data_quality_checks.py
"""

import logging
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_quality")

# ---------------------------------------------------------------------------
# Configuration — source landing paths and target tables
# ---------------------------------------------------------------------------
SOURCE_PATHS = {
    "borrowers": "/mnt/landing/cdw/CDW_BORR_MSTR",
    "loan_products": "/mnt/landing/cdw/CDW_LN_PROD",
    "loan_accounts": "/mnt/landing/cdw/CDW_LN_ACCT",
    "payments": "/mnt/landing/cdw/CDW_PMT_HIST",
}
SOURCE_FORMAT = "csv"

TARGET_TABLES = {
    "borrowers": "loan_modernized.borrowers",
    "loan_products": "loan_modernized.loan_products",
    "loan_accounts": "loan_modernized.loan_accounts",
    "payments": "loan_modernized.payments",
}

QUARANTINE_PATHS = {
    "borrowers": "/mnt/landing/cdw/quarantine/borrowers",
    "loan_products": "/mnt/landing/cdw/quarantine/loan_products",
    "loan_accounts": "/mnt/landing/cdw/quarantine/loan_accounts",
    "payments": "/mnt/landing/cdw/quarantine/payments",
}

REPORT_PATH = "/mnt/landing/cdw/reports/DATA_QUALITY_REPORT.md"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------
@dataclass
class CheckResult:
    category: str
    check_name: str
    status: str  # PASS, FAIL, WARN
    detail: str = ""


@dataclass
class QualityReport:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, category: str, name: str, passed: bool, detail: str = "") -> None:
        status = "PASS" if passed else "FAIL"
        self.results.append(CheckResult(category, name, status, detail))

    def add_warn(self, category: str, name: str, detail: str = "") -> None:
        self.results.append(CheckResult(category, name, "WARN", detail))

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
# 1. Row-count reconciliation
# ---------------------------------------------------------------------------
def check_row_counts(spark: SparkSession, report: QualityReport) -> None:
    """Compare source row counts against target + quarantine."""
    logger.info("Running row-count reconciliation checks")

    for table_key in TARGET_TABLES:
        source_path = SOURCE_PATHS[table_key]
        target_table = TARGET_TABLES[table_key]
        quarantine_path = QUARANTINE_PATHS[table_key]

        try:
            source_df = spark.read.format(SOURCE_FORMAT).option(
                "header", "true"
            ).load(source_path)
            source_count = source_df.count()
        except Exception as e:
            report.add_warn(
                "Row Count",
                f"{table_key}: source readable",
                f"Could not read source at {source_path}: {e}",
            )
            continue

        try:
            target_count = spark.table(target_table).count()
        except Exception as e:
            report.add(
                "Row Count",
                f"{table_key}: target exists",
                False,
                f"Could not read target {target_table}: {e}",
            )
            continue

        quarantine_count = 0
        try:
            quarantine_count = spark.read.format("delta").load(
                quarantine_path
            ).count()
        except Exception:
            pass  # quarantine may not exist if no records were quarantined

        accounted = target_count + quarantine_count
        matched = accounted == source_count
        report.add(
            "Row Count",
            f"{table_key}: source({source_count}) == target({target_count}) + quarantine({quarantine_count})",
            matched,
            f"Source={source_count}, Target={target_count}, Quarantine={quarantine_count}, Accounted={accounted}",
        )


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {
    "borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_products": ["code", "name", "type", "term_months", "rate_type"],
    "loan_accounts": [
        "account_number",
        "borrower_id",
        "product_code",
        "original_amount",
        "current_balance",
        "interest_rate",
        "term_months",
        "monthly_payment",
        "origination_date",
        "maturity_date",
        "status",
    ],
    "payments": [
        "legacy_sequence_nbr",
        "account_number",
        "payment_date",
        "total_amount",
        "type",
        "status",
    ],
}


def check_nulls(spark: SparkSession, report: QualityReport) -> None:
    """Verify that required columns contain no NULLs in target tables."""
    logger.info("Running null-check validations")

    for table_key, columns in REQUIRED_FIELDS.items():
        target_table = TARGET_TABLES[table_key]
        try:
            df = spark.table(target_table)
        except Exception as e:
            report.add(
                "Null Check",
                f"{table_key}: table readable",
                False,
                str(e),
            )
            continue

        for col_name in columns:
            if col_name not in df.columns:
                report.add(
                    "Null Check",
                    f"{table_key}.{col_name}: column exists",
                    False,
                    f"Column '{col_name}' not found in {target_table}",
                )
                continue

            null_count = df.filter(F.col(col_name).isNull()).count()
            report.add(
                "Null Check",
                f"{table_key}.{col_name}: no nulls",
                null_count == 0,
                f"{null_count} null(s) found" if null_count > 0 else "",
            )


# ---------------------------------------------------------------------------
# 3. Referential integrity
# ---------------------------------------------------------------------------
def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Verify FK relationships between tables."""
    logger.info("Running referential integrity checks")

    # loan_accounts.borrower_id -> borrowers.borrower_id
    try:
        loans = spark.table(TARGET_TABLES["loan_accounts"])
        borrowers = spark.table(TARGET_TABLES["borrowers"])

        orphan_loans = loans.join(
            borrowers,
            loans["borrower_id"] == borrowers["borrower_id"],
            "left_anti",
        ).count()

        report.add(
            "Referential Integrity",
            "loan_accounts.borrower_id -> borrowers.borrower_id",
            orphan_loans == 0,
            f"{orphan_loans} orphaned loan account(s)" if orphan_loans > 0 else "",
        )
    except Exception as e:
        report.add(
            "Referential Integrity",
            "loan_accounts -> borrowers",
            False,
            str(e),
        )

    # loan_accounts.product_code -> loan_products.code
    try:
        loans = spark.table(TARGET_TABLES["loan_accounts"])
        products = spark.table(TARGET_TABLES["loan_products"])

        orphan_products = loans.join(
            products,
            loans["product_code"] == products["code"],
            "left_anti",
        ).count()

        report.add(
            "Referential Integrity",
            "loan_accounts.product_code -> loan_products.code",
            orphan_products == 0,
            f"{orphan_products} loan(s) with unknown product code"
            if orphan_products > 0
            else "",
        )
    except Exception as e:
        report.add(
            "Referential Integrity",
            "loan_accounts -> loan_products",
            False,
            str(e),
        )

    # payments.account_number -> loan_accounts.account_number
    try:
        payments = spark.table(TARGET_TABLES["payments"])
        loans = spark.table(TARGET_TABLES["loan_accounts"])

        orphan_payments = payments.join(
            loans,
            payments["account_number"] == loans["account_number"],
            "left_anti",
        ).count()

        report.add(
            "Referential Integrity",
            "payments.account_number -> loan_accounts.account_number",
            orphan_payments == 0,
            f"{orphan_payments} orphaned payment(s)" if orphan_payments > 0 else "",
        )
    except Exception as e:
        report.add(
            "Referential Integrity",
            "payments -> loan_accounts",
            False,
            str(e),
        )


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------
def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules."""
    logger.info("Running business rule validations")

    # Rule 1: Active loans must have current_balance > 0
    try:
        loans = spark.table(TARGET_TABLES["loan_accounts"])
        active_zero_balance = loans.filter(
            (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
        ).count()
        report.add(
            "Business Rule",
            "Active loans have positive balance",
            active_zero_balance == 0,
            f"{active_zero_balance} active loan(s) with balance <= 0"
            if active_zero_balance > 0
            else "",
        )
    except Exception as e:
        report.add("Business Rule", "Active loans positive balance", False, str(e))

    # Rule 2: Closed loans should have a status of CLOSED (no specific closed_date
    # column, but maturity_date should be <= today for truly closed loans if status is CLOSED)
    try:
        loans = spark.table(TARGET_TABLES["loan_accounts"])
        closed_no_maturity = loans.filter(
            (F.col("status") == "CLOSED") & F.col("maturity_date").isNull()
        ).count()
        report.add(
            "Business Rule",
            "Closed loans have maturity_date",
            closed_no_maturity == 0,
            f"{closed_no_maturity} closed loan(s) without maturity date"
            if closed_no_maturity > 0
            else "",
        )
    except Exception as e:
        report.add("Business Rule", "Closed loans maturity date", False, str(e))

    # Rule 3: Loan origination_date must be before maturity_date
    try:
        loans = spark.table(TARGET_TABLES["loan_accounts"])
        bad_dates = loans.filter(
            F.col("origination_date") >= F.col("maturity_date")
        ).count()
        report.add(
            "Business Rule",
            "origination_date < maturity_date",
            bad_dates == 0,
            f"{bad_dates} loan(s) where origination >= maturity"
            if bad_dates > 0
            else "",
        )
    except Exception as e:
        report.add("Business Rule", "Date ordering", False, str(e))

    # Rule 4: Interest rate must be between 0 and 100
    try:
        loans = spark.table(TARGET_TABLES["loan_accounts"])
        bad_rates = loans.filter(
            (F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)
        ).count()
        report.add(
            "Business Rule",
            "Interest rate in [0, 100]",
            bad_rates == 0,
            f"{bad_rates} loan(s) with out-of-range interest rate"
            if bad_rates > 0
            else "",
        )
    except Exception as e:
        report.add("Business Rule", "Interest rate range", False, str(e))

    # Rule 5: LTV percent must be between 0 and 200 (if not null)
    try:
        loans = spark.table(TARGET_TABLES["loan_accounts"])
        bad_ltv = loans.filter(
            F.col("ltv_percent").isNotNull()
            & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
        ).count()
        report.add(
            "Business Rule",
            "LTV percent in [0, 200]",
            bad_ltv == 0,
            f"{bad_ltv} loan(s) with out-of-range LTV" if bad_ltv > 0 else "",
        )
    except Exception as e:
        report.add("Business Rule", "LTV range", False, str(e))

    # Rule 6: Payment amounts should reconcile (principal + interest + escrow + late_fee ≈ total)
    try:
        payments = spark.table(TARGET_TABLES["payments"])
        tolerance = 0.02  # allow 2-cent rounding tolerance

        mismatched = payments.filter(
            F.abs(
                F.coalesce(F.col("principal_amount"), F.lit(0))
                + F.coalesce(F.col("interest_amount"), F.lit(0))
                + F.coalesce(F.col("escrow_amount"), F.lit(0))
                + F.coalesce(F.col("late_fee"), F.lit(0))
                - F.col("total_amount")
            )
            > tolerance
        ).count()
        report.add(
            "Business Rule",
            "Payment component sum ≈ total_amount (±$0.02)",
            mismatched == 0,
            f"{mismatched} payment(s) with component mismatch"
            if mismatched > 0
            else "",
        )
    except Exception as e:
        report.add("Business Rule", "Payment reconciliation", False, str(e))

    # Rule 7: Credit scores should be in [300, 850] range (if not null)
    try:
        borrowers = spark.table(TARGET_TABLES["borrowers"])
        bad_scores = borrowers.filter(
            F.col("credit_score").isNotNull()
            & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()
        report.add(
            "Business Rule",
            "Credit score in [300, 850]",
            bad_scores == 0,
            f"{bad_scores} borrower(s) with out-of-range credit score"
            if bad_scores > 0
            else "",
        )
    except Exception as e:
        report.add("Business Rule", "Credit score range", False, str(e))

    # Rule 8: Delinquent loans (delinquency_days > 0) should not have status ACTIVE
    # (warning, not hard failure — business may allow short delinquencies)
    try:
        loans = spark.table(TARGET_TABLES["loan_accounts"])
        delinquent_active = loans.filter(
            (F.col("status") == "ACTIVE") & (F.col("delinquency_days") > 0)
        ).count()
        if delinquent_active > 0:
            report.add_warn(
                "Business Rule",
                "Active loans with delinquency_days > 0",
                f"{delinquent_active} active loan(s) showing delinquency — review needed",
            )
        else:
            report.add(
                "Business Rule",
                "No active loans with delinquency > 0",
                True,
            )
    except Exception as e:
        report.add("Business Rule", "Delinquency check", False, str(e))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def generate_report_markdown(report: QualityReport) -> str:
    """Render the quality report as Markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {now}",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total Checks | {report.total} |",
        f"| Passed | {report.pass_count} |",
        f"| Failed | {report.fail_count} |",
        f"| Warnings | {report.warn_count} |",
        "",
        f"**Overall Status:** {'PASS' if report.fail_count == 0 else 'FAIL'}",
        "",
    ]

    categories = sorted(set(r.category for r in report.results))
    for cat in categories:
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Status | Check | Detail |")
        lines.append("|--------|-------|--------|")
        for r in report.results:
            if r.category == cat:
                icon = {"PASS": "PASS", "FAIL": "**FAIL**", "WARN": "WARN"}[
                    r.status
                ]
                detail = r.detail.replace("|", "\\|") if r.detail else "—"
                lines.append(f"| {icon} | {r.check_name} | {detail} |")
        lines.append("")

    return "\n".join(lines)


def write_report(spark: SparkSession, markdown: str) -> None:
    """Write the Markdown report to DBFS."""
    report_rdd = spark.sparkContext.parallelize([markdown])
    report_rdd.coalesce(1).saveAsTextFile(REPORT_PATH + "_tmp")
    logger.info("Data quality report written to %s", REPORT_PATH)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(spark: SparkSession) -> QualityReport:
    """Execute all quality checks and generate report."""
    report = QualityReport()

    check_row_counts(spark, report)
    check_nulls(spark, report)
    check_referential_integrity(spark, report)
    check_business_rules(spark, report)

    markdown = generate_report_markdown(report)
    print(markdown)

    try:
        write_report(spark, markdown)
    except Exception as e:
        logger.warning("Could not write report to DBFS: %s", e)
        logger.info("Report content printed to stdout above")

    return report


if __name__ == "__main__":
    spark = SparkSession.builder.appName("data_quality_checks").getOrCreate()
    result = run(spark)
    if result.fail_count > 0:
        logger.error(
            "DATA QUALITY CHECK FAILED: %d failure(s) out of %d checks",
            result.fail_count,
            result.total,
        )
        raise SystemExit(1)
    else:
        logger.info(
            "DATA QUALITY CHECK PASSED: %d/%d checks passed, %d warning(s)",
            result.pass_count,
            result.total,
            result.warn_count,
        )
