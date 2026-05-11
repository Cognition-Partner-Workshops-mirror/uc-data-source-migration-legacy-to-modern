"""
Data quality validation module for the CDW → Delta Lake migration.

Runs post-ingestion checks across all four target tables:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts ↔ borrowers/loan_products
     and payments ↔ loan_accounts
  4. Business rule validation:
     - Active loans must have balance > 0
     - Closed loans must have a maturity date
     - Payment amounts must be >= 0
     - Credit scores must be in valid range (300–850)

Each check returns a ValidationResult with pass/fail status, description,
and detail counts. Results are aggregated into a DATA_QUALITY_REPORT.md.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from pyspark.sql import SparkSession, functions as F

from config import TARGET_TABLES, SOURCE_PATHS

logger = logging.getLogger("cdw_migration.quality")


@dataclass
class ValidationResult:
    """Result of a single data quality check."""
    category: str          # e.g. "Row Count", "Null Check", "Referential Integrity"
    table: str             # Target table name
    check_name: str        # Human-readable check description
    status: str            # "PASS" or "FAIL"
    expected: str          # Expected value/condition
    actual: str            # Actual value/condition
    detail: str = ""       # Additional context for failures


@dataclass
class QualityReport:
    """Aggregated quality report across all checks."""
    results: List[ValidationResult] = field(default_factory=list)
    run_timestamp: str = ""
    total_checks: int = 0
    passed: int = 0
    failed: int = 0

    def add(self, result: ValidationResult) -> None:
        """Add a check result and update counters."""
        self.results.append(result)
        self.total_checks += 1
        if result.status == "PASS":
            self.passed += 1
        else:
            self.failed += 1


def run_row_count_checks(
    spark: SparkSession, source_counts: dict, report: QualityReport
) -> None:
    """
    Check 1: Row count reconciliation — source count must match
    target count + quarantine count for each table.
    """
    logger.info("Running row count reconciliation checks")

    for table_key, target_table in TARGET_TABLES.items():
        target_count = spark.table(target_table).count()
        expected = source_counts.get(table_key, {}).get("source_count", "N/A")
        quarantine = source_counts.get(table_key, {}).get("quarantine_count", 0)

        # Source count should equal target + quarantine (no records lost)
        if expected != "N/A":
            actual_total = target_count + quarantine
            status = "PASS" if actual_total == expected else "FAIL"
            detail = (
                f"target={target_count}, quarantine={quarantine}, "
                f"total={actual_total}"
            )
        else:
            status = "FAIL"
            detail = "Source count not available from ingestion results"

        report.add(ValidationResult(
            category="Row Count",
            table=table_key,
            check_name=f"Row count reconciliation: {table_key}",
            status=status,
            expected=str(expected),
            actual=str(target_count) + f" (+{quarantine} quarantined)",
            detail=detail,
        ))


def run_null_checks(spark: SparkSession, report: QualityReport) -> None:
    """
    Check 2: Required fields must not contain NULLs in the target tables.

    Required fields per table are defined by the modern schema constraints.
    """
    logger.info("Running null checks on required fields")

    # Required fields per table (NOT NULL in modern schema)
    required_fields = {
        "borrowers": ["external_id", "first_name", "last_name"],
        "loan_products": ["code", "name", "type", "term_months", "rate_type"],
        "loan_accounts": [
            "account_number", "borrower_id", "product_id",
            "original_amount", "current_balance", "interest_rate",
            "term_months", "monthly_payment", "origination_date", "maturity_date",
        ],
        "payments": [
            "loan_account_id", "payment_date", "total_amount", "type", "status",
        ],
    }

    for table_key, fields in required_fields.items():
        df = spark.table(TARGET_TABLES[table_key])
        total_rows = df.count()

        for col_name in fields:
            null_count = df.filter(F.col(col_name).isNull()).count()
            status = "PASS" if null_count == 0 else "FAIL"

            report.add(ValidationResult(
                category="Null Check",
                table=table_key,
                check_name=f"NOT NULL: {table_key}.{col_name}",
                status=status,
                expected="0 nulls",
                actual=f"{null_count} nulls out of {total_rows} rows",
                detail=f"{null_count / total_rows * 100:.1f}% null" if total_rows > 0 else "No rows",
            ))


def run_referential_integrity_checks(
    spark: SparkSession, report: QualityReport
) -> None:
    """
    Check 3: FK references must resolve — no orphan records.

    Checks:
      - loan_accounts.borrower_id → borrowers.borrower_id
      - loan_accounts.product_id → loan_products.product_id
      - payments.loan_account_id → loan_accounts.loan_account_id
    """
    logger.info("Running referential integrity checks")

    # loan_accounts.borrower_id → borrowers.borrower_id
    loans_df = spark.table(TARGET_TABLES["loan_accounts"])
    borrowers_df = spark.table(TARGET_TABLES["borrowers"])

    orphan_borrower = loans_df.join(
        borrowers_df,
        loans_df["borrower_id"] == borrowers_df["borrower_id"],
        "left_anti",
    ).count()

    report.add(ValidationResult(
        category="Referential Integrity",
        table="loan_accounts",
        check_name="FK: loan_accounts.borrower_id → borrowers",
        status="PASS" if orphan_borrower == 0 else "FAIL",
        expected="0 orphan records",
        actual=f"{orphan_borrower} orphan records",
        detail="Loan accounts referencing non-existent borrowers",
    ))

    # loan_accounts.product_id → loan_products.product_id
    products_df = spark.table(TARGET_TABLES["loan_products"])

    orphan_product = loans_df.join(
        products_df,
        loans_df["product_id"] == products_df["product_id"],
        "left_anti",
    ).count()

    report.add(ValidationResult(
        category="Referential Integrity",
        table="loan_accounts",
        check_name="FK: loan_accounts.product_id → loan_products",
        status="PASS" if orphan_product == 0 else "FAIL",
        expected="0 orphan records",
        actual=f"{orphan_product} orphan records",
        detail="Loan accounts referencing non-existent products",
    ))

    # payments.loan_account_id → loan_accounts.loan_account_id
    payments_df = spark.table(TARGET_TABLES["payments"])

    orphan_loan = payments_df.join(
        loans_df,
        payments_df["loan_account_id"] == loans_df["loan_account_id"],
        "left_anti",
    ).count()

    report.add(ValidationResult(
        category="Referential Integrity",
        table="payments",
        check_name="FK: payments.loan_account_id → loan_accounts",
        status="PASS" if orphan_loan == 0 else "FAIL",
        expected="0 orphan records",
        actual=f"{orphan_loan} orphan records",
        detail="Payments referencing non-existent loan accounts",
    ))


def run_business_rule_checks(spark: SparkSession, report: QualityReport) -> None:
    """
    Check 4: Business rule validation for financial correctness.

    Rules:
      - Active loans must have current_balance > 0
      - Closed loans must have maturity_date populated
      - Payment total_amount must be >= 0
      - Borrower credit_score must be in range [300, 850] (when not null)
      - Loan interest_rate must be > 0
      - Loan original_amount must be > 0
    """
    logger.info("Running business rule validation checks")

    loans_df = spark.table(TARGET_TABLES["loan_accounts"])
    payments_df = spark.table(TARGET_TABLES["payments"])
    borrowers_df = spark.table(TARGET_TABLES["borrowers"])

    # Rule: Active loans must have balance > 0
    active_zero_bal = loans_df.filter(
        (F.col("status") == "Active") & (F.col("current_balance") <= 0)
    ).count()
    active_total = loans_df.filter(F.col("status") == "Active").count()

    report.add(ValidationResult(
        category="Business Rule",
        table="loan_accounts",
        check_name="Active loans must have current_balance > 0",
        status="PASS" if active_zero_bal == 0 else "FAIL",
        expected="0 active loans with balance <= 0",
        actual=f"{active_zero_bal} violations out of {active_total} active loans",
    ))

    # Rule: Closed loans must have maturity_date
    closed_no_maturity = loans_df.filter(
        (F.col("status") == "Closed") & (F.col("maturity_date").isNull())
    ).count()
    closed_total = loans_df.filter(F.col("status") == "Closed").count()

    report.add(ValidationResult(
        category="Business Rule",
        table="loan_accounts",
        check_name="Closed loans must have maturity_date populated",
        status="PASS" if closed_no_maturity == 0 else "FAIL",
        expected="0 closed loans without maturity_date",
        actual=f"{closed_no_maturity} violations out of {closed_total} closed loans",
    ))

    # Rule: Payment amounts must be >= 0
    negative_payments = payments_df.filter(F.col("total_amount") < 0).count()
    total_payments = payments_df.count()

    report.add(ValidationResult(
        category="Business Rule",
        table="payments",
        check_name="Payment total_amount must be >= 0",
        status="PASS" if negative_payments == 0 else "FAIL",
        expected="0 negative payment amounts",
        actual=f"{negative_payments} violations out of {total_payments} payments",
    ))

    # Rule: Credit scores in valid range [300, 850] (when populated)
    invalid_scores = borrowers_df.filter(
        F.col("credit_score").isNotNull()
        & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()
    scored_borrowers = borrowers_df.filter(F.col("credit_score").isNotNull()).count()

    report.add(ValidationResult(
        category="Business Rule",
        table="borrowers",
        check_name="Credit scores must be in range [300, 850]",
        status="PASS" if invalid_scores == 0 else "FAIL",
        expected="0 out-of-range scores",
        actual=f"{invalid_scores} violations out of {scored_borrowers} scored borrowers",
    ))

    # Rule: Loan interest rate must be > 0
    zero_rate = loans_df.filter(F.col("interest_rate") <= 0).count()
    total_loans = loans_df.count()

    report.add(ValidationResult(
        category="Business Rule",
        table="loan_accounts",
        check_name="Loan interest_rate must be > 0",
        status="PASS" if zero_rate == 0 else "FAIL",
        expected="0 loans with interest_rate <= 0",
        actual=f"{zero_rate} violations out of {total_loans} loans",
    ))

    # Rule: Loan original_amount must be > 0
    zero_orig = loans_df.filter(F.col("original_amount") <= 0).count()

    report.add(ValidationResult(
        category="Business Rule",
        table="loan_accounts",
        check_name="Loan original_amount must be > 0",
        status="PASS" if zero_orig == 0 else "FAIL",
        expected="0 loans with original_amount <= 0",
        actual=f"{zero_orig} violations out of {total_loans} loans",
    ))


def generate_report_markdown(report: QualityReport) -> str:
    """
    Generate a Markdown-formatted DATA_QUALITY_REPORT from the validation results.
    """
    lines = [
        "# Data Quality Report",
        "",
        f"**Run Timestamp:** {report.run_timestamp}",
        f"**Total Checks:** {report.total_checks}",
        f"**Passed:** {report.passed}",
        f"**Failed:** {report.failed}",
        f"**Overall Status:** {'PASS ✓' if report.failed == 0 else 'FAIL ✗'}",
        "",
        "---",
        "",
    ]

    # Group results by category
    categories = {}
    for r in report.results:
        categories.setdefault(r.category, []).append(r)

    for category, results in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Status | Table | Check | Expected | Actual | Detail |")
        lines.append("|--------|-------|-------|----------|--------|--------|")
        for r in results:
            status_icon = "PASS" if r.status == "PASS" else "**FAIL**"
            lines.append(
                f"| {status_icon} | {r.table} | {r.check_name} | "
                f"{r.expected} | {r.actual} | {r.detail} |"
            )
        lines.append("")

    # Summary of failures (if any)
    failures = [r for r in report.results if r.status == "FAIL"]
    if failures:
        lines.append("## Failure Summary")
        lines.append("")
        for i, f_result in enumerate(failures, 1):
            lines.append(
                f"{i}. **{f_result.table}** — {f_result.check_name}: "
                f"{f_result.actual} ({f_result.detail})"
            )
        lines.append("")

    return "\n".join(lines)


def run_all_checks(
    spark: SparkSession,
    source_counts: dict = None,
    output_path: str = None,
) -> QualityReport:
    """
    Run all data quality checks and generate the report.

    Args:
        spark: Active SparkSession
        source_counts: Dict from run_ingestion with per-table counts.
                       If None, row count reconciliation is skipped.
        output_path: Path to write DATA_QUALITY_REPORT.md. If None,
                     writes to DBFS default location.

    Returns:
        QualityReport with all results
    """
    report = QualityReport(run_timestamp=datetime.now().isoformat())

    # Run all check categories
    if source_counts:
        run_row_count_checks(spark, source_counts, report)
    else:
        logger.warning(
            "Source counts not provided; skipping row count reconciliation"
        )

    run_null_checks(spark, report)
    run_referential_integrity_checks(spark, report)
    run_business_rule_checks(spark, report)

    # Generate and write the Markdown report
    md_content = generate_report_markdown(report)

    if output_path:
        # Write to the specified path (DBFS or local)
        with open(output_path, "w") as f:
            f.write(md_content)
        logger.info(f"Quality report written to {output_path}")
    else:
        # Write to DBFS default location
        dbfs_path = "/dbfs/tmp/DATA_QUALITY_REPORT.md"
        with open(dbfs_path, "w") as f:
            f.write(md_content)
        logger.info(f"Quality report written to {dbfs_path}")

    # Log summary
    logger.info(
        f"Quality check complete: {report.passed}/{report.total_checks} passed, "
        f"{report.failed} failed"
    )

    return report
