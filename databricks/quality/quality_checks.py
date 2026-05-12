"""
Data Quality Validation Framework for the CDW legacy-to-modern migration.

Runs post-ingestion checks across all four migrated tables and produces a
structured report. Check categories:

  1. Row Count Reconciliation  — source row count must equal target row count
  2. Null Checks               — required columns must not contain nulls
  3. Referential Integrity     — FK columns must resolve to valid parent records
  4. Business Rule Validation  — domain-specific invariants for loan data

Each check returns a CheckResult dataclass that is collected into a summary
report written to DATA_QUALITY_REPORT.md.

Usage (Databricks notebook):
    %run ./quality_checks

Or standalone:
    spark-submit quality_checks.py \
        --source-base-path /mnt/landing/cdw/ \
        --source-format csv \
        --report-path /dbfs/reports/DATA_QUALITY_REPORT.md
"""

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

logger = logging.getLogger("cdw_migration.quality")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Check result model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Represents the outcome of a single data quality check."""
    category: str          # e.g., "Row Count", "Null Check", "Referential Integrity", "Business Rule"
    table: str             # target table name
    check_name: str        # human-readable check description
    passed: bool
    details: str = ""      # additional context on failure
    severity: str = "ERROR"  # ERROR or WARNING


@dataclass
class QualityReport:
    """Aggregates all check results and renders the final markdown report."""
    results: List[CheckResult] = field(default_factory=list)
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))

    def add(self, result: CheckResult) -> None:
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info("[%s] %s / %s: %s — %s",
                     status, result.table, result.category, result.check_name, result.details)

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
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession, source_path: str, source_format: str,
                     target_table: str, source_label: str, report: QualityReport) -> None:
    """
    Compare source extract row count against the target Delta table row count.
    They must match exactly — any discrepancy means records were dropped or duplicated.
    """
    # Read source
    if source_format == "csv":
        source_df = spark.read.option("header", "true").csv(source_path)
    else:
        source_df = spark.read.parquet(source_path)
    source_count = source_df.count()

    # Read target
    target_count = spark.table(target_table).count()

    passed = source_count == target_count
    report.add(CheckResult(
        category="Row Count",
        table=target_table,
        check_name=f"Source ({source_label}) vs Target row count",
        passed=passed,
        details=f"Source: {source_count}, Target: {target_count}"
                + ("" if passed else f" — DELTA: {target_count - source_count}"),
    ))


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------

# Required (NOT NULL) columns per target table, derived from the modern schema DDL
REQUIRED_COLUMNS = {
    "loan_warehouse.borrowers": ["external_id", "first_name", "last_name"],
    "loan_warehouse.loan_products": ["code", "name", "type", "term_months", "rate_type"],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment",
        "origination_date", "maturity_date",
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount", "type", "status",
    ],
}


def check_nulls(spark: SparkSession, target_table: str, report: QualityReport) -> None:
    """
    For each required column in the target table, count nulls.
    Any null in a required column is a FAIL.
    """
    columns = REQUIRED_COLUMNS.get(target_table, [])
    df = spark.table(target_table)

    for col_name in columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        passed = null_count == 0
        report.add(CheckResult(
            category="Null Check",
            table=target_table,
            check_name=f"Column '{col_name}' must not be NULL",
            passed=passed,
            details=f"Null count: {null_count}" if not passed else "No nulls found",
        ))


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """
    Verify FK relationships between migrated tables:
      - loan_accounts.borrower_id → borrowers.id
      - loan_accounts.product_id  → loan_products.id
      - payments.loan_account_id  → loan_accounts.id
    """
    fk_checks = [
        {
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "borrower_id",
            "parent_table": "loan_warehouse.borrowers",
            "parent_col": "id",
            "label": "loan_accounts.borrower_id → borrowers.id",
        },
        {
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "product_id",
            "parent_table": "loan_warehouse.loan_products",
            "parent_col": "id",
            "label": "loan_accounts.product_id → loan_products.id",
        },
        {
            "child_table": "loan_warehouse.payments",
            "child_col": "loan_account_id",
            "parent_table": "loan_warehouse.loan_accounts",
            "parent_col": "id",
            "label": "payments.loan_account_id → loan_accounts.id",
        },
    ]

    for fk in fk_checks:
        child_df = spark.table(fk["child_table"]).select(F.col(fk["child_col"]).alias("fk_val"))
        parent_df = spark.table(fk["parent_table"]).select(F.col(fk["parent_col"]).alias("pk_val"))

        # Find orphans: child FK values not in parent PK set
        orphans = child_df.join(parent_df, child_df["fk_val"] == parent_df["pk_val"], "left_anti")
        orphan_count = orphans.count()

        passed = orphan_count == 0
        report.add(CheckResult(
            category="Referential Integrity",
            table=fk["child_table"],
            check_name=fk["label"],
            passed=passed,
            details=f"Orphan rows: {orphan_count}" if not passed else "All FKs resolve",
        ))


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """
    Validate domain-specific business rules on the migrated data:
      - Active loans must have current_balance > 0
      - Closed loans should have a meaningful status (no active-balance contradiction)
      - Payment amounts must be positive
      - Loan interest rate must be between 0 and 100
      - Credit scores must be in a valid range (300–850)
      - Loan term must be positive
    """
    loans = spark.table("loan_warehouse.loan_accounts")
    payments = spark.table("loan_warehouse.payments")
    borrowers = spark.table("loan_warehouse.borrowers")

    # Rule 1: Active loans must have current_balance > 0
    active_zero_balance = loans.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        table="loan_warehouse.loan_accounts",
        check_name="Active loans must have current_balance > 0",
        passed=active_zero_balance == 0,
        details=f"Violations: {active_zero_balance}",
    ))

    # Rule 2: Payment total_amount must be > 0
    negative_payments = payments.filter(F.col("total_amount") <= 0).count()
    report.add(CheckResult(
        category="Business Rule",
        table="loan_warehouse.payments",
        check_name="Payment total_amount must be > 0",
        passed=negative_payments == 0,
        details=f"Violations: {negative_payments}",
    ))

    # Rule 3: Interest rate must be between 0 and 100 (exclusive)
    bad_rates = loans.filter(
        (F.col("interest_rate") <= 0) | (F.col("interest_rate") >= 100)
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        table="loan_warehouse.loan_accounts",
        check_name="Interest rate must be between 0 and 100",
        passed=bad_rates == 0,
        details=f"Violations: {bad_rates}",
    ))

    # Rule 4: Credit score in valid range (300–850) where not null
    bad_scores = borrowers.filter(
        F.col("credit_score").isNotNull()
        & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()
    report.add(CheckResult(
        category="Business Rule",
        table="loan_warehouse.borrowers",
        check_name="Credit score must be between 300 and 850 (where not null)",
        passed=bad_scores == 0,
        details=f"Violations: {bad_scores}",
    ))

    # Rule 5: Loan term must be positive
    bad_terms = loans.filter(F.col("term_months") <= 0).count()
    report.add(CheckResult(
        category="Business Rule",
        table="loan_warehouse.loan_accounts",
        check_name="Loan term_months must be > 0",
        passed=bad_terms == 0,
        details=f"Violations: {bad_terms}",
    ))

    # Rule 6: Loan status must be one of the known expanded values
    valid_statuses = ["ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE"]
    unknown_status = loans.filter(~F.col("status").isin(valid_statuses)).count()
    report.add(CheckResult(
        category="Business Rule",
        table="loan_warehouse.loan_accounts",
        check_name="Loan status must be a known value (ACTIVE/CLOSED/DEFAULT/FORBEARANCE)",
        passed=unknown_status == 0,
        details=f"Violations: {unknown_status}",
        severity="WARNING",
    ))

    # Rule 7: Payment type must be one of the known expanded values
    valid_types = ["REGULAR", "EXTRA", "PARTIAL", "PREPAYMENT"]
    unknown_type = payments.filter(~F.col("type").isin(valid_types)).count()
    report.add(CheckResult(
        category="Business Rule",
        table="loan_warehouse.payments",
        check_name="Payment type must be a known value (REGULAR/EXTRA/PARTIAL/PREPAYMENT)",
        passed=unknown_type == 0,
        details=f"Violations: {unknown_type}",
        severity="WARNING",
    ))

    # Rule 8: Maturity date must be after origination date
    bad_dates = loans.filter(F.col("maturity_date") <= F.col("origination_date")).count()
    report.add(CheckResult(
        category="Business Rule",
        table="loan_warehouse.loan_accounts",
        check_name="Maturity date must be after origination date",
        passed=bad_dates == 0,
        details=f"Violations: {bad_dates}",
    ))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report_markdown(report: QualityReport) -> str:
    """Render the quality report as a markdown document."""
    lines = [
        "# Data Quality Report",
        "",
        f"**Run timestamp:** {report.run_timestamp}",
        "",
        f"**Total checks:** {report.total}  |  "
        f"**Passed:** {report.passed}  |  "
        f"**Failed:** {report.failed}",
        "",
        "---",
        "",
    ]

    # Group results by category for readability
    categories = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for category, results in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Table | Check | Result | Details | Severity |")
        lines.append("|-------|-------|--------|---------|----------|")
        for r in results:
            status = "PASS" if r.passed else "**FAIL**"
            lines.append(f"| `{r.table}` | {r.check_name} | {status} | {r.details} | {r.severity} |")
        lines.append("")

    # Summary section
    lines.append("---")
    lines.append("")
    if report.failed == 0:
        lines.append("**All data quality checks passed.** The migration data is ready for validation.")
    else:
        lines.append(f"**{report.failed} check(s) failed.** Review the failures above and "
                      "re-run the ingestion pipeline after fixing the source data or transformation logic.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_all_checks(spark: SparkSession, source_base_path: str,
                   source_format: str = "csv",
                   report_path: str = "DATA_QUALITY_REPORT.md") -> QualityReport:
    """
    Execute all data quality checks and write the report to the specified path.
    """
    report = QualityReport()

    # Source-to-target mapping for row count checks
    source_target_map = [
        (f"{source_base_path}/cdw_borr_mstr", "loan_warehouse.borrowers", "CDW_BORR_MSTR"),
        (f"{source_base_path}/cdw_ln_prod", "loan_warehouse.loan_products", "CDW_LN_PROD"),
        (f"{source_base_path}/cdw_ln_acct", "loan_warehouse.loan_accounts", "CDW_LN_ACCT"),
        (f"{source_base_path}/cdw_pmt_hist", "loan_warehouse.payments", "CDW_PMT_HIST"),
    ]

    # 1. Row count reconciliation
    logger.info("Running row count reconciliation checks...")
    for src_path, tgt_table, src_label in source_target_map:
        check_row_counts(spark, src_path, source_format, tgt_table, src_label, report)

    # 2. Null checks on required fields
    logger.info("Running null checks on required fields...")
    for _, tgt_table, _ in source_target_map:
        check_nulls(spark, tgt_table, report)

    # 3. Referential integrity
    logger.info("Running referential integrity checks...")
    check_referential_integrity(spark, report)

    # 4. Business rule validation
    logger.info("Running business rule validation...")
    check_business_rules(spark, report)

    # Generate and write report
    md_content = generate_report_markdown(report)

    # Write report using dbutils if available (Databricks), otherwise standard file I/O
    try:
        # Databricks environment — write via dbutils
        dbutils.fs.put(report_path, md_content, overwrite=True)  # type: ignore[name-defined]
        logger.info("Report written to %s (via dbutils)", report_path)
    except NameError:
        # Local/standalone — write via standard I/O
        with open(report_path, "w") as f:
            f.write(md_content)
        logger.info("Report written to %s (via local file I/O)", report_path)

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run data quality checks on migrated loan data")
    parser.add_argument("--source-base-path", required=True,
                        help="Base path containing source extract sub-directories")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--report-path", default="DATA_QUALITY_REPORT.md",
                        help="Output path for the quality report markdown file")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_DataQuality_Checks").getOrCreate()

    report = run_all_checks(spark, args.source_base_path, args.source_format, args.report_path)

    # Exit with non-zero code if any checks failed (useful in CI/job orchestration)
    if report.failed > 0:
        logger.error("%d quality check(s) FAILED", report.failed)
        exit(1)
    else:
        logger.info("All %d quality checks PASSED", report.total)

    spark.stop()
