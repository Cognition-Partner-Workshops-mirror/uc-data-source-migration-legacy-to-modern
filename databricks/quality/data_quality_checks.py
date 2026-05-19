"""
Data Quality Framework for the CDW-to-Delta-Lake loan management migration.

This module provides a comprehensive suite of post-ingestion validation checks
that verify data integrity, completeness, and business rule compliance across
the migrated Delta Lake tables. It is designed to run after all four ingestion
scripts have completed.

Validation categories:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts -> borrowers and
     loan_accounts -> loan_products, and payments -> loan_accounts
  4. Business rule validation (e.g., balance > 0 for active loans)
  5. Data type / range validations

Output:
  - Console logging with pass/fail for each check
  - Generates DATA_QUALITY_REPORT.md summarizing all results

Usage:
    spark-submit data_quality_checks.py \\
        --borrowers-source /mnt/landing/cdw_borr_mstr.csv \\
        --products-source /mnt/landing/cdw_ln_prod.csv \\
        --accounts-source /mnt/landing/cdw_ln_acct.csv \\
        --payments-source /mnt/landing/cdw_pmt_hist.csv \\
        --output-dir /mnt/reports
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from pyspark.sql import SparkSession, functions as F

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("data_quality")


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Stores the outcome of a single data quality check."""
    category: str        # e.g., "Row Count", "Null Check", "Referential Integrity"
    table: str           # Target table name
    check_name: str      # Human-readable check description
    status: str          # "PASSED" or "FAILED"
    details: str = ""    # Additional context (counts, percentages, etc.)


@dataclass
class QualityReport:
    """Aggregates all check results and generates the final report."""
    results: List[CheckResult] = field(default_factory=list)
    run_timestamp: str = field(
        default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    )

    def add(self, result: CheckResult):
        """Add a check result and log it immediately."""
        self.results.append(result)
        icon = "PASS" if result.status == "PASSED" else "FAIL"
        logger.info(
            f"[{icon}] {result.category} | {result.table} | "
            f"{result.check_name} | {result.details}"
        )

    @property
    def total_checks(self) -> int:
        return len(self.results)

    @property
    def passed_checks(self) -> int:
        return sum(1 for r in self.results if r.status == "PASSED")

    @property
    def failed_checks(self) -> int:
        return sum(1 for r in self.results if r.status == "FAILED")

    @property
    def overall_status(self) -> str:
        return "PASSED" if self.failed_checks == 0 else "FAILED"


# ---------------------------------------------------------------------------
# Row count reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession, report: QualityReport,
                     source_paths: dict, file_format: str = "csv"):
    """
    Verify that row counts match between source files and target Delta tables.

    Compares the number of rows in each source CSV/Parquet file against the
    corresponding Delta Lake table to ensure no records were silently dropped
    during ingestion.

    Args:
        spark: Active SparkSession.
        report: QualityReport to append results to.
        source_paths: Dict mapping table names to source file paths.
        file_format: Source file format ('csv' or 'parquet').
    """
    logger.info("Running row count reconciliation checks...")

    # Mapping of source path keys to Delta table names
    table_map = {
        "borrowers": "loan_management.borrowers",
        "products": "loan_management.loan_products",
        "accounts": "loan_management.loan_accounts",
        "payments": "loan_management.payments",
    }

    for key, target_table in table_map.items():
        source_path = source_paths.get(key)
        if not source_path:
            continue

        try:
            # Read source row count
            if file_format == "csv":
                source_df = spark.read.option("header", "true").csv(source_path)
            else:
                source_df = spark.read.parquet(source_path)
            source_count = source_df.count()

            # Read target row count
            target_count = spark.table(target_table).count()

            # Compare counts
            status = "PASSED" if source_count == target_count else "FAILED"
            details = f"Source: {source_count}, Target: {target_count}"
            if source_count != target_count:
                diff = source_count - target_count
                details += f", Difference: {diff} rows"

            report.add(CheckResult(
                category="Row Count",
                table=target_table,
                check_name=f"Row count reconciliation ({key})",
                status=status,
                details=details,
            ))
        except Exception as e:
            report.add(CheckResult(
                category="Row Count",
                table=target_table,
                check_name=f"Row count reconciliation ({key})",
                status="FAILED",
                details=f"Error: {str(e)}",
            ))


# ---------------------------------------------------------------------------
# Null checks on required fields
# ---------------------------------------------------------------------------

def check_null_constraints(spark: SparkSession, report: QualityReport):
    """
    Verify that required (NOT NULL) fields contain no null values.

    Checks all columns marked as NOT NULL in the modern schema DDL.
    This ensures the ingestion transformations correctly handled all
    source data without introducing unexpected nulls.

    Args:
        spark: Active SparkSession.
        report: QualityReport to append results to.
    """
    logger.info("Running null constraint checks...")

    # Required fields per table (from modern schema DDL)
    required_fields = {
        "loan_management.borrowers": [
            "external_id", "first_name", "last_name",
        ],
        "loan_management.loan_products": [
            "code", "name", "type", "term_months", "rate_type",
        ],
        "loan_management.loan_accounts": [
            "account_number", "borrower_id", "product_id",
            "original_amount", "current_balance", "interest_rate",
            "term_months", "monthly_payment", "origination_date", "maturity_date",
        ],
        "loan_management.payments": [
            "loan_account_id", "payment_date", "total_amount", "type", "status",
        ],
    }

    for table_name, columns in required_fields.items():
        try:
            df = spark.table(table_name)
            for col_name in columns:
                null_count = df.filter(F.col(col_name).isNull()).count()
                total_count = df.count()
                status = "PASSED" if null_count == 0 else "FAILED"
                details = f"Nulls: {null_count}/{total_count}"
                if null_count > 0:
                    pct = (null_count / total_count * 100) if total_count > 0 else 0
                    details += f" ({pct:.1f}%)"

                report.add(CheckResult(
                    category="Null Check",
                    table=table_name,
                    check_name=f"NOT NULL: {col_name}",
                    status=status,
                    details=details,
                ))
        except Exception as e:
            report.add(CheckResult(
                category="Null Check",
                table=table_name,
                check_name="Null constraint validation",
                status="FAILED",
                details=f"Error: {str(e)}",
            ))


# ---------------------------------------------------------------------------
# Referential integrity checks
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession, report: QualityReport):
    """
    Verify FK relationships between tables are valid (no orphan records).

    Checks:
      - loan_accounts.borrower_id references valid borrowers.id
      - loan_accounts.product_id references valid loan_products.id
      - payments.loan_account_id references valid loan_accounts.id

    Args:
        spark: Active SparkSession.
        report: QualityReport to append results to.
    """
    logger.info("Running referential integrity checks...")

    fk_checks = [
        {
            "child_table": "loan_management.loan_accounts",
            "child_col": "borrower_id",
            "parent_table": "loan_management.borrowers",
            "parent_col": "id",
            "description": "loan_accounts.borrower_id -> borrowers.id",
        },
        {
            "child_table": "loan_management.loan_accounts",
            "child_col": "product_id",
            "parent_table": "loan_management.loan_products",
            "parent_col": "id",
            "description": "loan_accounts.product_id -> loan_products.id",
        },
        {
            "child_table": "loan_management.payments",
            "child_col": "loan_account_id",
            "parent_table": "loan_management.loan_accounts",
            "parent_col": "id",
            "description": "payments.loan_account_id -> loan_accounts.id",
        },
    ]

    for check in fk_checks:
        try:
            child_df = spark.table(check["child_table"])
            parent_df = spark.table(check["parent_table"])

            # Find orphaned child records (FK value not in parent table)
            orphans = child_df.join(
                parent_df,
                child_df[check["child_col"]] == parent_df[check["parent_col"]],
                "left_anti",
            )
            orphan_count = orphans.count()
            total_count = child_df.count()

            status = "PASSED" if orphan_count == 0 else "FAILED"
            details = f"Orphans: {orphan_count}/{total_count}"
            if orphan_count > 0:
                # Log sample orphan values for debugging
                sample_values = [
                    str(row[0]) for row in
                    orphans.select(check["child_col"]).limit(5).collect()
                ]
                details += f", Sample orphan IDs: {sample_values}"

            report.add(CheckResult(
                category="Referential Integrity",
                table=check["child_table"],
                check_name=check["description"],
                status=status,
                details=details,
            ))
        except Exception as e:
            report.add(CheckResult(
                category="Referential Integrity",
                table=check["child_table"],
                check_name=check["description"],
                status="FAILED",
                details=f"Error: {str(e)}",
            ))


# ---------------------------------------------------------------------------
# Business rule validation
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession, report: QualityReport):
    """
    Validate domain-specific business rules on the migrated data.

    Rules checked:
      - Active loans must have current_balance > 0
      - Closed loans should have a maturity_date (not null)
      - Loan origination_date must be before maturity_date
      - Payment total_amount must be >= 0
      - Credit scores must be within valid range (300-850)
      - Interest rates must be positive and reasonable (0-30%)
      - Escrow amounts must be non-negative
      - Monthly payment must be positive for active loans

    Args:
        spark: Active SparkSession.
        report: QualityReport to append results to.
    """
    logger.info("Running business rule validation checks...")

    try:
        loans = spark.table("loan_management.loan_accounts")
        payments = spark.table("loan_management.payments")
        borrowers = spark.table("loan_management.borrowers")

        # Rule 1: Active loans must have current_balance > 0
        active_loans = loans.filter(F.col("status") == "ACTIVE")
        active_zero_balance = active_loans.filter(
            F.col("current_balance") <= 0
        ).count()
        active_total = active_loans.count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_management.loan_accounts",
            check_name="Active loans have balance > 0",
            status="PASSED" if active_zero_balance == 0 else "FAILED",
            details=f"Violations: {active_zero_balance}/{active_total} active loans",
        ))

        # Rule 2: Closed loans must have non-null maturity_date
        closed_loans = loans.filter(F.col("status") == "CLOSED")
        closed_no_maturity = closed_loans.filter(
            F.col("maturity_date").isNull()
        ).count()
        closed_total = closed_loans.count()
        if closed_total > 0:
            report.add(CheckResult(
                category="Business Rule",
                table="loan_management.loan_accounts",
                check_name="Closed loans have maturity_date",
                status="PASSED" if closed_no_maturity == 0 else "FAILED",
                details=f"Violations: {closed_no_maturity}/{closed_total} closed loans",
            ))
        else:
            report.add(CheckResult(
                category="Business Rule",
                table="loan_management.loan_accounts",
                check_name="Closed loans have maturity_date",
                status="PASSED",
                details="No closed loans in dataset (check not applicable)",
            ))

        # Rule 3: origination_date must be before maturity_date
        date_violations = loans.filter(
            (F.col("origination_date").isNotNull()) &
            (F.col("maturity_date").isNotNull()) &
            (F.col("origination_date") >= F.col("maturity_date"))
        ).count()
        loans_total = loans.count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_management.loan_accounts",
            check_name="Origination date < maturity date",
            status="PASSED" if date_violations == 0 else "FAILED",
            details=f"Violations: {date_violations}/{loans_total} loans",
        ))

        # Rule 4: Payment total_amount must be >= 0
        negative_payments = payments.filter(F.col("total_amount") < 0).count()
        payments_total = payments.count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_management.payments",
            check_name="Payment amounts are non-negative",
            status="PASSED" if negative_payments == 0 else "FAILED",
            details=f"Violations: {negative_payments}/{payments_total} payments",
        ))

        # Rule 5: Credit scores within valid FICO range (300-850)
        invalid_credit = borrowers.filter(
            (F.col("credit_score").isNotNull()) &
            ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()
        borrowers_total = borrowers.count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_management.borrowers",
            check_name="Credit scores in valid range (300-850)",
            status="PASSED" if invalid_credit == 0 else "FAILED",
            details=f"Violations: {invalid_credit}/{borrowers_total} borrowers",
        ))

        # Rule 6: Interest rates positive and reasonable (0-30%)
        invalid_rates = loans.filter(
            (F.col("interest_rate").isNotNull()) &
            ((F.col("interest_rate") <= 0) | (F.col("interest_rate") > 30))
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_management.loan_accounts",
            check_name="Interest rates in valid range (0-30%)",
            status="PASSED" if invalid_rates == 0 else "FAILED",
            details=f"Violations: {invalid_rates}/{loans_total} loans",
        ))

        # Rule 7: Escrow amounts non-negative
        negative_escrow = loans.filter(
            (F.col("escrow_balance").isNotNull()) &
            (F.col("escrow_balance") < 0)
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_management.loan_accounts",
            check_name="Escrow balances are non-negative",
            status="PASSED" if negative_escrow == 0 else "FAILED",
            details=f"Violations: {negative_escrow}/{loans_total} loans",
        ))

        # Rule 8: Monthly payment > 0 for active loans
        active_zero_payment = active_loans.filter(
            F.col("monthly_payment") <= 0
        ).count()
        report.add(CheckResult(
            category="Business Rule",
            table="loan_management.loan_accounts",
            check_name="Active loans have positive monthly payment",
            status="PASSED" if active_zero_payment == 0 else "FAILED",
            details=f"Violations: {active_zero_payment}/{active_total} active loans",
        ))

    except Exception as e:
        report.add(CheckResult(
            category="Business Rule",
            table="(multiple)",
            check_name="Business rule validation suite",
            status="FAILED",
            details=f"Error: {str(e)}",
        ))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report_markdown(report: QualityReport, output_path: str):
    """
    Generate a DATA_QUALITY_REPORT.md summarizing all check results.

    The report includes:
      - Executive summary with pass/fail counts
      - Detailed results grouped by validation category
      - Recommendations for failed checks

    Args:
        report: Completed QualityReport with all check results.
        output_path: File path to write the markdown report.
    """
    lines = [
        "# Data Quality Report",
        "",
        f"**Run Timestamp:** {report.run_timestamp}",
        f"**Overall Status:** {report.overall_status}",
        "",
        "## Executive Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total Checks | {report.total_checks} |",
        f"| Passed | {report.passed_checks} |",
        f"| Failed | {report.failed_checks} |",
        f"| Pass Rate | {report.passed_checks / report.total_checks * 100:.1f}% |"
        if report.total_checks > 0 else "",
        "",
        "## Detailed Results",
        "",
    ]

    # Group results by category
    categories = {}
    for result in report.results:
        if result.category not in categories:
            categories[result.category] = []
        categories[result.category].append(result)

    for category, results in categories.items():
        lines.append(f"### {category}")
        lines.append("")
        lines.append("| Table | Check | Status | Details |")
        lines.append("|-------|-------|--------|---------|")
        for r in results:
            status_badge = "PASS" if r.status == "PASSED" else "**FAIL**"
            # Escape pipe characters in details
            safe_details = r.details.replace("|", "\\|")
            lines.append(
                f"| `{r.table}` | {r.check_name} | {status_badge} | {safe_details} |"
            )
        lines.append("")

    # Add recommendations for failures
    failed_results = [r for r in report.results if r.status == "FAILED"]
    if failed_results:
        lines.append("## Recommendations")
        lines.append("")
        lines.append(
            "The following checks failed and require investigation before "
            "the migrated data can be considered production-ready:"
        )
        lines.append("")
        for r in failed_results:
            lines.append(f"- **{r.category} - {r.check_name}** (`{r.table}`)")
            lines.append(f"  - {r.details}")
            lines.append("")
    else:
        lines.append("## Recommendations")
        lines.append("")
        lines.append(
            "All data quality checks passed. The migrated data is consistent "
            "with the source and meets all business rule validations."
        )
        lines.append("")

    lines.append("---")
    lines.append(f"*Report generated by the CDW-to-Delta-Lake migration quality framework.*")

    report_content = "\n".join(lines)

    # Write to local file
    with open(output_path, "w") as f:
        f.write(report_content)
    logger.info(f"Data quality report written to: {output_path}")

    return report_content


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_all_checks(spark: SparkSession, source_paths: dict,
                   file_format: str = "csv",
                   output_path: str = "DATA_QUALITY_REPORT.md") -> QualityReport:
    """
    Execute the complete data quality validation suite.

    Runs all check categories in order and generates the final report.

    Args:
        spark: Active SparkSession.
        source_paths: Dict mapping table keys to source file paths.
        file_format: Source file format for row count checks.
        output_path: Path to write the markdown report.

    Returns:
        QualityReport with all check results.
    """
    report = QualityReport()

    logger.info("=" * 60)
    logger.info("STARTING DATA QUALITY VALIDATION SUITE")
    logger.info("=" * 60)

    # Run all check categories
    check_row_counts(spark, report, source_paths, file_format)
    check_null_constraints(spark, report)
    check_referential_integrity(spark, report)
    check_business_rules(spark, report)

    # Generate the markdown report
    generate_report_markdown(report, output_path)

    logger.info("=" * 60)
    logger.info(
        f"DATA QUALITY VALIDATION COMPLETE: {report.overall_status} "
        f"({report.passed_checks}/{report.total_checks} passed)"
    )
    logger.info("=" * 60)

    return report


def main():
    """CLI entry point for running data quality checks."""
    parser = argparse.ArgumentParser(
        description="Run data quality checks on migrated Delta Lake tables"
    )
    parser.add_argument(
        "--borrowers-source", default="/mnt/landing/cdw_borr_mstr",
        help="Path to CDW_BORR_MSTR source file (for row count reconciliation)",
    )
    parser.add_argument(
        "--products-source", default="/mnt/landing/cdw_ln_prod",
        help="Path to CDW_LN_PROD source file",
    )
    parser.add_argument(
        "--accounts-source", default="/mnt/landing/cdw_ln_acct",
        help="Path to CDW_LN_ACCT source file",
    )
    parser.add_argument(
        "--payments-source", default="/mnt/landing/cdw_pmt_hist",
        help="Path to CDW_PMT_HIST source file",
    )
    parser.add_argument(
        "--format", default="csv", choices=["csv", "parquet"],
        help="Source file format (default: csv)",
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory to write the quality report",
    )
    args = parser.parse_args()

    source_paths = {
        "borrowers": args.borrowers_source,
        "products": args.products_source,
        "accounts": args.accounts_source,
        "payments": args.payments_source,
    }

    output_path = f"{args.output_dir}/DATA_QUALITY_REPORT.md"

    spark = (
        SparkSession.builder
        .appName("LoanMigration_DataQuality")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .getOrCreate()
    )

    try:
        report = run_all_checks(spark, source_paths, args.format, output_path)
        if report.failed_checks > 0:
            logger.error(
                f"{report.failed_checks} data quality check(s) FAILED. "
                f"See {output_path} for details."
            )
            sys.exit(1)
        else:
            logger.info("All data quality checks PASSED.")
    except Exception as e:
        logger.error(f"Data quality validation FAILED: {str(e)}", exc_info=True)
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
