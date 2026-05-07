"""
Data quality validation framework for CDW-to-Delta Lake migration.

Runs post-ingestion checks across all migrated tables and generates
a DATA_QUALITY_REPORT.md summarizing results. Checks include:
  - Row count reconciliation (source vs. target)
  - Null checks on NOT NULL columns
  - Referential integrity (FK relationships)
  - Business rule validations (balances, dates, amounts, ranges)

Usage:
    spark-submit data_quality_checks.py [--database loan_warehouse]
                                         [--source-path /mnt/landing/cdw]
                                         [--report-path /mnt/reports]
"""

import argparse
import os
from dataclasses import dataclass, field
from datetime import datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


# ============================================================================
# Data structures for check results
# ============================================================================


@dataclass
class CheckResult:
    """Stores the outcome of a single data quality check."""

    table: str
    check_name: str
    # PASS, FAIL, or WARN
    status: str
    message: str
    details: str = ""


@dataclass
class QualityReport:
    """Aggregates all check results for the full report."""

    results: list = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        """Append a check result to the report."""
        self.results.append(result)

    @property
    def pass_count(self) -> int:
        """Count of checks that passed."""
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def fail_count(self) -> int:
        """Count of checks that failed."""
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warn_count(self) -> int:
        """Count of checks with warnings."""
        return sum(1 for r in self.results if r.status == "WARN")


# ============================================================================
# Row count reconciliation checks
# ============================================================================


def check_row_counts(
    spark: SparkSession,
    report: QualityReport,
    source_path: str,
    database: str,
) -> None:
    """Compare source file row counts against target Delta table counts."""

    # Mapping: source file subfolder -> target table name
    table_map = {
        "CDW_BORR_MSTR": "borrowers",
        "CDW_LN_PROD": "loan_products",
        "CDW_LN_ACCT": "loan_accounts",
        "CDW_PMT_HIST": "payments",
    }

    for source_name, target_name in table_map.items():
        input_path = f"{source_path}/{source_name}"
        full_table = f"{database}.{target_name}"

        try:
            # Read source file to get row count
            source_df = (
                spark.read.format("csv")
                .option("header", "true")
                .load(input_path)
            )
            source_count = source_df.count()

            # Read target Delta table to get row count
            target_df = spark.table(full_table)
            target_count = target_df.count()

            # Compare counts — they should match exactly
            if source_count == target_count:
                report.add(
                    CheckResult(
                        table=target_name,
                        check_name="Row Count Reconciliation",
                        status="PASS",
                        message=(
                            f"Source ({source_count}) matches "
                            f"target ({target_count})"
                        ),
                    )
                )
            else:
                report.add(
                    CheckResult(
                        table=target_name,
                        check_name="Row Count Reconciliation",
                        status="FAIL",
                        message=(
                            f"Mismatch: source={source_count}, "
                            f"target={target_count}"
                        ),
                        details=(
                            f"Delta: {target_count - source_count} rows "
                            f"({'more' if target_count > source_count else 'fewer'} in target)"
                        ),
                    )
                )
        except Exception as exc:
            report.add(
                CheckResult(
                    table=target_name,
                    check_name="Row Count Reconciliation",
                    status="FAIL",
                    message=f"Error reading data: {exc}",
                )
            )


# ============================================================================
# Null checks on NOT NULL columns
# ============================================================================


def check_not_null_columns(
    spark: SparkSession,
    report: QualityReport,
    database: str,
) -> None:
    """Verify that columns marked NOT NULL contain no null values."""

    # Define required (NOT NULL) columns per table
    not_null_rules = {
        "borrowers": ["external_id", "first_name", "last_name"],
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
        ],
        "payments": [
            "payment_sequence",
            "loan_account_number",
            "payment_date",
            "total_amount",
            "type",
            "status",
        ],
    }

    for table_name, columns in not_null_rules.items():
        full_table = f"{database}.{table_name}"
        try:
            df = spark.table(full_table)
            for col_name in columns:
                # Count nulls in each NOT NULL column
                null_count = df.filter(F.col(col_name).isNull()).count()
                if null_count == 0:
                    report.add(
                        CheckResult(
                            table=table_name,
                            check_name=f"Not Null: {col_name}",
                            status="PASS",
                            message=f"No nulls found in {col_name}",
                        )
                    )
                else:
                    report.add(
                        CheckResult(
                            table=table_name,
                            check_name=f"Not Null: {col_name}",
                            status="FAIL",
                            message=f"{null_count} null(s) in {col_name}",
                        )
                    )
        except Exception as exc:
            report.add(
                CheckResult(
                    table=table_name,
                    check_name="Not Null Check",
                    status="FAIL",
                    message=f"Error: {exc}",
                )
            )


# ============================================================================
# Referential integrity checks
# ============================================================================


def check_referential_integrity(
    spark: SparkSession,
    report: QualityReport,
    database: str,
) -> None:
    """Validate that all FK references resolve to existing parent records."""

    # Check 1: loan_accounts.borrower_id -> borrowers.external_id
    try:
        loan_accounts = spark.table(f"{database}.loan_accounts")
        borrowers = spark.table(f"{database}.borrowers")

        # Find loan accounts referencing non-existent borrowers
        orphan_borrowers = loan_accounts.join(
            borrowers,
            loan_accounts["borrower_id"] == borrowers["external_id"],
            "left_anti",
        )
        orphan_count = orphan_borrowers.count()

        if orphan_count == 0:
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="FK: borrower_id -> borrowers.external_id",
                    status="PASS",
                    message="All borrower references resolve",
                )
            )
        else:
            # Collect sample orphan IDs for debugging
            samples = (
                orphan_borrowers.select("borrower_id")
                .distinct()
                .limit(5)
                .collect()
            )
            sample_ids = [str(r[0]) for r in samples]
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="FK: borrower_id -> borrowers.external_id",
                    status="FAIL",
                    message=f"{orphan_count} orphan loan account(s)",
                    details=f"Sample orphan borrower_ids: {sample_ids}",
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="loan_accounts",
                check_name="FK: borrower_id -> borrowers.external_id",
                status="FAIL",
                message=f"Error: {exc}",
            )
        )

    # Check 2: loan_accounts.product_code -> loan_products.code
    try:
        loan_accounts = spark.table(f"{database}.loan_accounts")
        products = spark.table(f"{database}.loan_products")

        # Find loan accounts referencing non-existent products
        orphan_products = loan_accounts.join(
            products,
            loan_accounts["product_code"] == products["code"],
            "left_anti",
        )
        orphan_count = orphan_products.count()

        if orphan_count == 0:
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="FK: product_code -> loan_products.code",
                    status="PASS",
                    message="All product references resolve",
                )
            )
        else:
            samples = (
                orphan_products.select("product_code")
                .distinct()
                .limit(5)
                .collect()
            )
            sample_ids = [str(r[0]) for r in samples]
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="FK: product_code -> loan_products.code",
                    status="FAIL",
                    message=f"{orphan_count} orphan loan account(s)",
                    details=f"Sample orphan product_codes: {sample_ids}",
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="loan_accounts",
                check_name="FK: product_code -> loan_products.code",
                status="FAIL",
                message=f"Error: {exc}",
            )
        )

    # Check 3: payments.loan_account_number -> loan_accounts.account_number
    try:
        payments = spark.table(f"{database}.payments")
        loan_accounts = spark.table(f"{database}.loan_accounts")

        # Find payments referencing non-existent loan accounts
        orphan_payments = payments.join(
            loan_accounts,
            payments["loan_account_number"]
            == loan_accounts["account_number"],
            "left_anti",
        )
        orphan_count = orphan_payments.count()

        if orphan_count == 0:
            report.add(
                CheckResult(
                    table="payments",
                    check_name=(
                        "FK: loan_account_number -> "
                        "loan_accounts.account_number"
                    ),
                    status="PASS",
                    message="All loan account references resolve",
                )
            )
        else:
            samples = (
                orphan_payments.select("loan_account_number")
                .distinct()
                .limit(5)
                .collect()
            )
            sample_ids = [str(r[0]) for r in samples]
            report.add(
                CheckResult(
                    table="payments",
                    check_name=(
                        "FK: loan_account_number -> "
                        "loan_accounts.account_number"
                    ),
                    status="FAIL",
                    message=f"{orphan_count} orphan payment(s)",
                    details=(
                        f"Sample orphan loan_account_numbers: {sample_ids}"
                    ),
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="payments",
                check_name=(
                    "FK: loan_account_number -> loan_accounts.account_number"
                ),
                status="FAIL",
                message=f"Error: {exc}",
            )
        )


# ============================================================================
# Business rule validations
# ============================================================================


def check_business_rules(
    spark: SparkSession,
    report: QualityReport,
    database: str,
) -> None:
    """Run domain-specific business rule validations."""

    # -------------------------------------------------------------------
    # Rule 1: Active loan accounts must have positive current balances
    # -------------------------------------------------------------------
    try:
        loans = spark.table(f"{database}.loan_accounts")
        active_negative = loans.filter(
            (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
        ).count()

        if active_negative == 0:
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="Active loans have positive balances",
                    status="PASS",
                    message="All active loans have balance > 0",
                )
            )
        else:
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="Active loans have positive balances",
                    status="FAIL",
                    message=(
                        f"{active_negative} active loan(s) "
                        f"with non-positive balance"
                    ),
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="loan_accounts",
                check_name="Active loans have positive balances",
                status="FAIL",
                message=f"Error: {exc}",
            )
        )

    # -------------------------------------------------------------------
    # Rule 2: Origination date must be before maturity date
    # -------------------------------------------------------------------
    try:
        loans = spark.table(f"{database}.loan_accounts")
        bad_dates = loans.filter(
            F.col("origination_date") >= F.col("maturity_date")
        ).count()

        if bad_dates == 0:
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="Origination date < maturity date",
                    status="PASS",
                    message="All loans have valid date ordering",
                )
            )
        else:
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="Origination date < maturity date",
                    status="FAIL",
                    message=(
                        f"{bad_dates} loan(s) with origination >= maturity"
                    ),
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="loan_accounts",
                check_name="Origination date < maturity date",
                status="FAIL",
                message=f"Error: {exc}",
            )
        )

    # -------------------------------------------------------------------
    # Rule 3: LTV percent must be in valid range (0-200%)
    # -------------------------------------------------------------------
    try:
        loans = spark.table(f"{database}.loan_accounts")
        bad_ltv = loans.filter(
            (F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200)
        ).count()

        if bad_ltv == 0:
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="LTV percent in valid range (0-200)",
                    status="PASS",
                    message="All LTV values are within 0-200%",
                )
            )
        else:
            report.add(
                CheckResult(
                    table="loan_accounts",
                    check_name="LTV percent in valid range (0-200)",
                    status="WARN",
                    message=f"{bad_ltv} loan(s) with LTV outside 0-200%",
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="loan_accounts",
                check_name="LTV percent in valid range (0-200)",
                status="FAIL",
                message=f"Error: {exc}",
            )
        )

    # -------------------------------------------------------------------
    # Rule 4: Credit score must be in valid range (300-850)
    # -------------------------------------------------------------------
    try:
        borrowers = spark.table(f"{database}.borrowers")
        bad_score = borrowers.filter(
            F.col("credit_score").isNotNull()
            & (
                (F.col("credit_score") < 300)
                | (F.col("credit_score") > 850)
            )
        ).count()

        if bad_score == 0:
            report.add(
                CheckResult(
                    table="borrowers",
                    check_name="Credit score in valid range (300-850)",
                    status="PASS",
                    message="All credit scores are within 300-850",
                )
            )
        else:
            report.add(
                CheckResult(
                    table="borrowers",
                    check_name="Credit score in valid range (300-850)",
                    status="WARN",
                    message=(
                        f"{bad_score} borrower(s) with credit "
                        f"score outside 300-850"
                    ),
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="borrowers",
                check_name="Credit score in valid range (300-850)",
                status="FAIL",
                message=f"Error: {exc}",
            )
        )

    # -------------------------------------------------------------------
    # Rule 5: Payment component amounts should sum to total (with tolerance)
    # Tolerance of 0.02 accounts for rounding differences
    # -------------------------------------------------------------------
    try:
        payments = spark.table(f"{database}.payments")

        # Sum principal + interest + escrow + late_fee and compare to total
        payments_with_sum = payments.withColumn(
            "_component_sum",
            (
                F.coalesce(F.col("principal_amount"), F.lit(0))
                + F.coalesce(F.col("interest_amount"), F.lit(0))
                + F.coalesce(F.col("escrow_amount"), F.lit(0))
                + F.coalesce(F.col("late_fee"), F.lit(0))
            ),
        )

        # Check where absolute difference exceeds tolerance
        tolerance = 0.02
        bad_sums = payments_with_sum.filter(
            F.abs(F.col("total_amount") - F.col("_component_sum"))
            > tolerance
        ).count()

        if bad_sums == 0:
            report.add(
                CheckResult(
                    table="payments",
                    check_name=(
                        "Payment components sum to total "
                        "(tolerance=0.02)"
                    ),
                    status="PASS",
                    message="All payment components sum correctly",
                )
            )
        else:
            # Collect sample discrepancies for debugging
            sample_rows = (
                payments_with_sum.filter(
                    F.abs(F.col("total_amount") - F.col("_component_sum"))
                    > tolerance
                )
                .select(
                    "payment_sequence",
                    "total_amount",
                    "_component_sum",
                )
                .limit(5)
                .collect()
            )
            details_lines = []
            for row in sample_rows:
                details_lines.append(
                    f"  {row['payment_sequence']}: "
                    f"total={row['total_amount']}, "
                    f"sum={row['_component_sum']}"
                )
            report.add(
                CheckResult(
                    table="payments",
                    check_name=(
                        "Payment components sum to total "
                        "(tolerance=0.02)"
                    ),
                    status="FAIL",
                    message=(
                        f"{bad_sums} payment(s) with component "
                        f"sum mismatch"
                    ),
                    details="\n".join(details_lines),
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="payments",
                check_name=(
                    "Payment components sum to total (tolerance=0.02)"
                ),
                status="FAIL",
                message=f"Error: {exc}",
            )
        )

    # -------------------------------------------------------------------
    # Rule 6: Loan product min_amount must be <= max_amount
    # -------------------------------------------------------------------
    try:
        products = spark.table(f"{database}.loan_products")
        bad_range = products.filter(
            F.col("min_amount") > F.col("max_amount")
        ).count()

        if bad_range == 0:
            report.add(
                CheckResult(
                    table="loan_products",
                    check_name="Product min_amount <= max_amount",
                    status="PASS",
                    message="All products have valid amount ranges",
                )
            )
        else:
            report.add(
                CheckResult(
                    table="loan_products",
                    check_name="Product min_amount <= max_amount",
                    status="FAIL",
                    message=(
                        f"{bad_range} product(s) with min > max amount"
                    ),
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="loan_products",
                check_name="Product min_amount <= max_amount",
                status="FAIL",
                message=f"Error: {exc}",
            )
        )

    # -------------------------------------------------------------------
    # Rule 7: Payment received_date should be on or before processed_date
    # -------------------------------------------------------------------
    try:
        payments = spark.table(f"{database}.payments")
        bad_order = payments.filter(
            F.col("received_date").isNotNull()
            & F.col("processed_date").isNotNull()
            & (F.col("received_date") > F.col("processed_date"))
        ).count()

        if bad_order == 0:
            report.add(
                CheckResult(
                    table="payments",
                    check_name="Received date <= processed date",
                    status="PASS",
                    message="All payments have valid date ordering",
                )
            )
        else:
            report.add(
                CheckResult(
                    table="payments",
                    check_name="Received date <= processed date",
                    status="WARN",
                    message=(
                        f"{bad_order} payment(s) received after "
                        f"processing date"
                    ),
                )
            )
    except Exception as exc:
        report.add(
            CheckResult(
                table="payments",
                check_name="Received date <= processed date",
                status="FAIL",
                message=f"Error: {exc}",
            )
        )


# ============================================================================
# Report generation
# ============================================================================


def generate_report(report: QualityReport, output_path: str) -> None:
    """Write a DATA_QUALITY_REPORT.md summarizing all check results."""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {timestamp}",
        "",
        "## Summary",
        "",
        "| Status | Count |",
        "|--------|-------|",
        f"| PASS   | {report.pass_count} |",
        f"| FAIL   | {report.fail_count} |",
        f"| WARN   | {report.warn_count} |",
        f"| **Total** | **{len(report.results)}** |",
        "",
    ]

    # Group results by table for organized output
    tables_seen = []
    for r in report.results:
        if r.table not in tables_seen:
            tables_seen.append(r.table)

    for table in tables_seen:
        table_results = [r for r in report.results if r.table == table]
        lines.append(f"## {table}")
        lines.append("")
        lines.append("| Check | Status | Message |")
        lines.append("|-------|--------|---------|")
        for r in table_results:
            # Use emoji-free status indicators
            status_indicator = r.status
            lines.append(
                f"| {r.check_name} | {status_indicator} | {r.message} |"
            )
        lines.append("")

        # Add details section for any checks with details
        for r in table_results:
            if r.details:
                lines.append(f"### {r.check_name} — Details")
                lines.append("")
                lines.append("```")
                lines.append(r.details)
                lines.append("```")
                lines.append("")

    report_content = "\n".join(lines)
    report_file = os.path.join(output_path, "DATA_QUALITY_REPORT.md")

    # Write report to file system
    with open(report_file, "w") as f:
        f.write(report_content)

    print(f"Data quality report written to: {report_file}")
    print(
        f"Summary: {report.pass_count} PASS, "
        f"{report.fail_count} FAIL, "
        f"{report.warn_count} WARN"
    )


# ============================================================================
# Main entry point
# ============================================================================


def run_all_checks(
    spark: SparkSession,
    database: str,
    source_path: str,
    report_path: str,
) -> QualityReport:
    """Execute all data quality checks and generate the report."""

    report = QualityReport()

    print("=" * 70)
    print("CDW Migration — Data Quality Checks")
    print("=" * 70)

    # Run all check categories
    print("\n--- Row Count Reconciliation ---")
    check_row_counts(spark, report, source_path, database)

    print("\n--- Not Null Checks ---")
    check_not_null_columns(spark, report, database)

    print("\n--- Referential Integrity Checks ---")
    check_referential_integrity(spark, report, database)

    print("\n--- Business Rule Validations ---")
    check_business_rules(spark, report, database)

    # Generate the markdown report
    generate_report(report, report_path)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run data quality checks on migrated Delta Lake tables"
    )
    parser.add_argument(
        "--database",
        default="loan_warehouse",
        help="Databricks database name",
    )
    parser.add_argument(
        "--source-path",
        default="/mnt/landing/cdw",
        help="Base path to source landing zone files",
    )
    parser.add_argument(
        "--report-path",
        default="/mnt/reports",
        help="Directory to write the quality report",
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName(
        "CDW_Migration_QualityChecks"
    ).getOrCreate()

    result = run_all_checks(
        spark, args.database, args.source_path, args.report_path
    )

    spark.stop()

    # Exit with non-zero code if any checks failed
    if result.fail_count > 0:
        exit(1)
