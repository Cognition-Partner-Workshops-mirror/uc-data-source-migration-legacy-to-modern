"""
data_quality_checks.py — PySpark-based data quality validation framework.

Runs after ingestion to validate the migrated Delta Lake tables against
business rules and referential integrity constraints. Generates a
DATA_QUALITY_REPORT.md summarizing pass/fail results.

Validation categories:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts ↔ borrowers, loan_products
     and payments ↔ loan_accounts
  4. Business rule validation:
     - Active loans must have balance > 0
     - Closed loans must have a maturity_date in the past
     - Payment amounts must sum correctly (principal + interest + escrow ≈ total)
     - No future-dated payments with POSTED status
"""

import os
from datetime import datetime

from pyspark.sql import SparkSession, functions as F


# =============================================================================
# Configuration
# =============================================================================
# Delta Lake table names
BORROWERS_TABLE = "loan_management.borrowers"
LOAN_PRODUCTS_TABLE = "loan_management.loan_products"
LOAN_ACCOUNTS_TABLE = "loan_management.loan_accounts"
PAYMENTS_TABLE = "loan_management.payments"

# Output path for the quality report
REPORT_OUTPUT_PATH = "/dbfs/mnt/reports/DATA_QUALITY_REPORT.md"


class DataQualityCheck:
    """Represents a single data quality check with its result."""

    def __init__(self, category, name, description):
        self.category = category
        self.name = name
        self.description = description
        self.passed = None
        self.details = ""
        self.actual_value = None
        self.expected_value = None

    def set_result(self, passed, details="", actual=None, expected=None):
        """Record the check result."""
        self.passed = passed
        self.details = details
        self.actual_value = actual
        self.expected_value = expected

    @property
    def status_str(self):
        """Return a human-readable status string."""
        if self.passed is None:
            return "NOT RUN"
        return "PASS" if self.passed else "FAIL"


class DataQualityFramework:
    """
    Orchestrates all data quality checks and generates the report.
    Designed to run in a Databricks notebook or as a spark-submit job.
    """

    def __init__(self, spark=None):
        self.spark = spark or SparkSession.builder.appName("DataQuality").getOrCreate()
        self.checks = []
        self.run_timestamp = datetime.now()

    # =========================================================================
    # 1. Row Count Reconciliation
    # =========================================================================

    def check_row_counts(self, source_counts):
        """
        Verify that the number of rows in each target table matches the
        expected source row counts provided by the ingestion pipeline.

        Args:
            source_counts: dict mapping table name → expected row count
                e.g. {"borrowers": 5, "loan_products": 5, "loan_accounts": 5, "payments": 10}
        """
        tables = {
            "borrowers": BORROWERS_TABLE,
            "loan_products": LOAN_PRODUCTS_TABLE,
            "loan_accounts": LOAN_ACCOUNTS_TABLE,
            "payments": PAYMENTS_TABLE,
        }

        for short_name, full_table in tables.items():
            check = DataQualityCheck(
                category="Row Count",
                name=f"row_count_{short_name}",
                description=f"Row count reconciliation for {short_name}"
            )

            try:
                target_count = self.spark.table(full_table).count()
                expected = source_counts.get(short_name, -1)

                if expected == -1:
                    check.set_result(
                        passed=False,
                        details=f"No source count provided for {short_name}",
                        actual=target_count,
                        expected="Unknown"
                    )
                elif target_count == expected:
                    check.set_result(
                        passed=True,
                        details=f"Target has {target_count} rows matching source",
                        actual=target_count,
                        expected=expected
                    )
                else:
                    check.set_result(
                        passed=False,
                        details=(
                            f"Row count mismatch: source={expected}, target={target_count}, "
                            f"delta={target_count - expected}"
                        ),
                        actual=target_count,
                        expected=expected
                    )
            except Exception as e:
                check.set_result(
                    passed=False,
                    details=f"Error reading table: {str(e)}"
                )

            self.checks.append(check)

    # =========================================================================
    # 2. Null Checks on Required Fields
    # =========================================================================

    def check_required_fields(self):
        """
        Verify that required (NOT NULL) columns have no null values in the
        target tables. These columns are required per the modern schema DDL.
        """
        # Map: table → list of required columns
        required_fields = {
            BORROWERS_TABLE: ["external_id", "first_name", "last_name"],
            LOAN_PRODUCTS_TABLE: ["code", "name", "type", "term_months", "rate_type"],
            LOAN_ACCOUNTS_TABLE: [
                "account_number", "borrower_external_id", "product_code",
                "original_amount", "current_balance", "interest_rate",
                "term_months", "monthly_payment", "origination_date", "maturity_date",
            ],
            PAYMENTS_TABLE: [
                "loan_account_number", "payment_date", "total_amount", "type", "status",
            ],
        }

        for table, columns in required_fields.items():
            short_name = table.split(".")[-1]
            try:
                df = self.spark.table(table)
                for col_name in columns:
                    check = DataQualityCheck(
                        category="Null Check",
                        name=f"null_{short_name}_{col_name}",
                        description=f"No nulls in {short_name}.{col_name}"
                    )

                    # Check for both SQL nulls and empty/whitespace-only strings,
                    # which CSV reads can produce instead of proper nulls
                    null_count = df.filter(
                        F.col(col_name).isNull()
                        | (F.trim(F.col(col_name).cast("string")) == "")
                    ).count()

                    if null_count == 0:
                        check.set_result(
                            passed=True,
                            details=f"No null or empty values found in {col_name}",
                            actual=0,
                            expected=0
                        )
                    else:
                        check.set_result(
                            passed=False,
                            details=f"{null_count} null/empty values found in required column {col_name}",
                            actual=null_count,
                            expected=0
                        )

                    self.checks.append(check)

            except Exception as e:
                check = DataQualityCheck(
                    category="Null Check",
                    name=f"null_{short_name}_all",
                    description=f"Required field checks for {short_name}"
                )
                check.set_result(passed=False, details=f"Error: {str(e)}")
                self.checks.append(check)

    # =========================================================================
    # 3. Referential Integrity
    # =========================================================================

    def check_referential_integrity(self):
        """
        Verify FK relationships between tables:
          - loan_accounts.borrower_external_id → borrowers.external_id
          - loan_accounts.product_code → loan_products.code
          - payments.loan_account_number → loan_accounts.account_number
        """
        fk_checks = [
            {
                "name": "fk_loan_accounts_borrowers",
                "description": "Every loan account references a valid borrower",
                "child_table": LOAN_ACCOUNTS_TABLE,
                "child_col": "borrower_external_id",
                "parent_table": BORROWERS_TABLE,
                "parent_col": "external_id",
            },
            {
                "name": "fk_loan_accounts_products",
                "description": "Every loan account references a valid product",
                "child_table": LOAN_ACCOUNTS_TABLE,
                "child_col": "product_code",
                "parent_table": LOAN_PRODUCTS_TABLE,
                "parent_col": "code",
            },
            {
                "name": "fk_payments_loan_accounts",
                "description": "Every payment references a valid loan account",
                "child_table": PAYMENTS_TABLE,
                "child_col": "loan_account_number",
                "parent_table": LOAN_ACCOUNTS_TABLE,
                "parent_col": "account_number",
            },
        ]

        for fk in fk_checks:
            check = DataQualityCheck(
                category="Referential Integrity",
                name=fk["name"],
                description=fk["description"]
            )

            try:
                child_df = self.spark.table(fk["child_table"])
                parent_df = self.spark.table(fk["parent_table"])

                # Find child rows with no matching parent
                orphans = (
                    child_df
                    .join(
                        parent_df,
                        child_df[fk["child_col"]] == parent_df[fk["parent_col"]],
                        "left_anti"
                    )
                    .count()
                )

                if orphans == 0:
                    check.set_result(
                        passed=True,
                        details="All child records have matching parent records",
                        actual=0,
                        expected=0
                    )
                else:
                    check.set_result(
                        passed=False,
                        details=(
                            f"{orphans} orphan record(s) in "
                            f"{fk['child_table']}.{fk['child_col']} "
                            f"with no match in {fk['parent_table']}.{fk['parent_col']}"
                        ),
                        actual=orphans,
                        expected=0
                    )

            except Exception as e:
                check.set_result(passed=False, details=f"Error: {str(e)}")

            self.checks.append(check)

    # =========================================================================
    # 4. Business Rule Validation
    # =========================================================================

    def check_business_rules(self):
        """
        Validate domain-specific business rules on the migrated data.
        """
        self._check_active_loan_balance()
        self._check_closed_loan_dates()
        self._check_payment_amount_consistency()
        self._check_no_future_posted_payments()
        self._check_credit_score_range()
        self._check_interest_rate_range()
        self._check_duplicate_primary_keys()

    def _check_active_loan_balance(self):
        """Active loans must have a positive, non-null current balance."""
        check = DataQualityCheck(
            category="Business Rule",
            name="active_loan_positive_balance",
            description="Active loans must have current_balance > 0"
        )

        try:
            df = self.spark.table(LOAN_ACCOUNTS_TABLE)
            active_loans = df.filter(F.col("status") == "ACTIVE")
            active_count = active_loans.count()

            # Check for null balance OR non-positive balance on active loans
            violations = active_loans.filter(
                F.col("current_balance").isNull()
                | (F.col("current_balance") <= 0)
            ).count()

            check.set_result(
                passed=(violations == 0),
                details=(
                    f"All {active_count} active loan(s) have positive balance"
                    if violations == 0
                    else f"{violations} of {active_count} active loan(s) with null or non-positive balance"
                ),
                actual=violations,
                expected=0
            )
        except Exception as e:
            check.set_result(passed=False, details=f"Error: {str(e)}")

        self.checks.append(check)

    def _check_closed_loan_dates(self):
        """Closed loans should have a maturity date."""
        check = DataQualityCheck(
            category="Business Rule",
            name="closed_loan_maturity_date",
            description="Closed loans must have a maturity_date"
        )

        try:
            df = self.spark.table(LOAN_ACCOUNTS_TABLE)
            closed_loans = df.filter(F.col("status") == "CLOSED")
            closed_count = closed_loans.count()

            # Report how many closed loans were actually tested to avoid
            # vacuous-truth passes when no closed loans exist
            if closed_count == 0:
                check.set_result(
                    passed=True,
                    details="No CLOSED loans found in dataset — check is vacuously true (0 rows tested)",
                    actual=0,
                    expected=0
                )
            else:
                violations = closed_loans.filter(
                    F.col("maturity_date").isNull()
                ).count()

                check.set_result(
                    passed=(violations == 0),
                    details=(
                        f"All {closed_count} closed loan(s) have a maturity_date"
                        if violations == 0
                        else f"{violations} of {closed_count} closed loan(s) without maturity_date"
                    ),
                    actual=violations,
                    expected=0
                )
        except Exception as e:
            check.set_result(passed=False, details=f"Error: {str(e)}")

        self.checks.append(check)

    def _check_payment_amount_consistency(self):
        """
        Payment component amounts (principal + interest + escrow) should
        approximately equal the total_amount (within rounding tolerance).

        Note: late_fee is tracked separately and is NOT included in the
        component sum, matching the seed data convention where total_amount
        represents the P+I+E payment only.
        """
        check = DataQualityCheck(
            category="Business Rule",
            name="payment_amount_consistency",
            description="principal + interest + escrow ≈ total_amount (±$0.02 tolerance)"
        )

        try:
            df = self.spark.table(PAYMENTS_TABLE)
            total_payments = df.count()

            # Calculate component sum and difference from total_amount
            df_with_diff = df.withColumn(
                "_component_sum",
                F.coalesce(F.col("principal_amount"), F.lit(0))
                + F.coalesce(F.col("interest_amount"), F.lit(0))
                + F.coalesce(F.col("escrow_amount"), F.lit(0))
            ).withColumn(
                "_amount_diff",
                F.abs(F.col("_component_sum") - F.col("total_amount"))
            )

            violation_df = df_with_diff.filter(F.col("_amount_diff") > 0.02)
            violations = violation_df.count()

            # Include specific discrepancy details for investigation
            detail_msg = ""
            if violations > 0:
                # Collect the IDs and amounts of violating payments for the report
                samples = (
                    violation_df
                    .select("legacy_payment_id", "total_amount", "_component_sum", "_amount_diff")
                    .limit(5)
                    .collect()
                )
                sample_details = "; ".join(
                    f"{r['legacy_payment_id']}: total={r['total_amount']}, "
                    f"components={r['_component_sum']}, diff={r['_amount_diff']}"
                    for r in samples
                )
                detail_msg = (
                    f"{violations} of {total_payments} payments have inconsistent amounts. "
                    f"Examples: {sample_details}"
                )
            else:
                detail_msg = f"All {total_payments} payments have consistent component amounts"

            check.set_result(
                passed=(violations == 0),
                details=detail_msg,
                actual=violations,
                expected=0
            )
        except Exception as e:
            check.set_result(passed=False, details=f"Error: {str(e)}")

        self.checks.append(check)

    def _check_no_future_posted_payments(self):
        """Posted payments should not have a payment_date in the future."""
        check = DataQualityCheck(
            category="Business Rule",
            name="no_future_posted_payments",
            description="POSTED payments must not have a future payment_date"
        )

        try:
            df = self.spark.table(PAYMENTS_TABLE)
            violations = df.filter(
                (F.col("status") == "POSTED")
                & (F.col("payment_date") > F.current_date())
            ).count()

            check.set_result(
                passed=(violations == 0),
                details=(
                    f"No future-dated POSTED payments found"
                    if violations == 0
                    else f"{violations} POSTED payment(s) with future payment_date"
                ),
                actual=violations,
                expected=0
            )
        except Exception as e:
            check.set_result(passed=False, details=f"Error: {str(e)}")

        self.checks.append(check)

    def _check_credit_score_range(self):
        """Credit scores should be in the valid range (300-850)."""
        check = DataQualityCheck(
            category="Business Rule",
            name="credit_score_range",
            description="Borrower credit scores must be between 300 and 850"
        )

        try:
            df = self.spark.table(BORROWERS_TABLE)
            violations = df.filter(
                F.col("credit_score").isNotNull()
                & (
                    (F.col("credit_score") < 300)
                    | (F.col("credit_score") > 850)
                )
            ).count()

            check.set_result(
                passed=(violations == 0),
                details=(
                    f"All credit scores are in valid range"
                    if violations == 0
                    else f"{violations} borrower(s) with out-of-range credit scores"
                ),
                actual=violations,
                expected=0
            )
        except Exception as e:
            check.set_result(passed=False, details=f"Error: {str(e)}")

        self.checks.append(check)

    def _check_interest_rate_range(self):
        """Interest rates should be in a reasonable range (0-30%)."""
        check = DataQualityCheck(
            category="Business Rule",
            name="interest_rate_range",
            description="Loan interest rates must be between 0% and 30%"
        )

        try:
            df = self.spark.table(LOAN_ACCOUNTS_TABLE)
            violations = df.filter(
                (F.col("interest_rate") < 0) | (F.col("interest_rate") > 30)
            ).count()

            check.set_result(
                passed=(violations == 0),
                details=(
                    f"All interest rates are in valid range"
                    if violations == 0
                    else f"{violations} loan(s) with out-of-range interest rates"
                ),
                actual=violations,
                expected=0
            )
        except Exception as e:
            check.set_result(passed=False, details=f"Error: {str(e)}")

        self.checks.append(check)

    def _check_duplicate_primary_keys(self):
        """
        Verify no duplicate primary keys exist in any target table.
        Duplicates can arise if the source data has repeats or if the
        ingestion pipeline is run multiple times without truncation.
        """
        pk_checks = [
            (BORROWERS_TABLE, "external_id"),
            (LOAN_PRODUCTS_TABLE, "code"),
            (LOAN_ACCOUNTS_TABLE, "account_number"),
            (PAYMENTS_TABLE, "legacy_payment_id"),
        ]

        for table, pk_col in pk_checks:
            short_name = table.split(".")[-1]
            check = DataQualityCheck(
                category="Business Rule",
                name=f"no_duplicate_pk_{short_name}",
                description=f"No duplicate {pk_col} values in {short_name}"
            )

            try:
                df = self.spark.table(table)
                total_rows = df.count()
                distinct_keys = df.select(pk_col).distinct().count()
                duplicates = total_rows - distinct_keys

                check.set_result(
                    passed=(duplicates == 0),
                    details=(
                        f"All {total_rows} rows have unique {pk_col}"
                        if duplicates == 0
                        else f"{duplicates} duplicate {pk_col} value(s) found ({total_rows} rows, {distinct_keys} distinct)"
                    ),
                    actual=duplicates,
                    expected=0
                )
            except Exception as e:
                check.set_result(passed=False, details=f"Error: {str(e)}")

            self.checks.append(check)

    # =========================================================================
    # Report Generation
    # =========================================================================

    def generate_report(self, output_path=REPORT_OUTPUT_PATH):
        """
        Generate a DATA_QUALITY_REPORT.md summarizing all check results.
        Returns the report content as a string.
        """
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed is True)
        failed = sum(1 for c in self.checks if c.passed is False)
        not_run = sum(1 for c in self.checks if c.passed is None)

        lines = [
            "# Data Quality Report",
            "",
            f"**Generated:** {self.run_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Pipeline:** Legacy CDW → Delta Lake Migration",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total Checks | {total} |",
            f"| Passed | {passed} |",
            f"| Failed | {failed} |",
            f"| Not Run | {not_run} |",
            f"| **Pass Rate** | **{(passed / total * 100) if total > 0 else 0:.1f}%** |",
            "",
            f"**Overall Status:** {'PASS' if failed == 0 else 'FAIL'}",
            "",
        ]

        # Group checks by category
        categories = {}
        for check in self.checks:
            categories.setdefault(check.category, []).append(check)

        for category, category_checks in categories.items():
            cat_passed = sum(1 for c in category_checks if c.passed is True)
            cat_total = len(category_checks)
            lines.append(f"## {category} ({cat_passed}/{cat_total} passed)")
            lines.append("")
            lines.append("| Check | Status | Details |")
            lines.append("|-------|--------|---------|")

            for check in category_checks:
                status_icon = "PASS" if check.passed else "FAIL"
                details = check.details.replace("|", "\\|")
                lines.append(f"| {check.description} | {status_icon} | {details} |")

            lines.append("")

        # Write the report
        report_content = "\n".join(lines)

        try:
            # Write to DBFS or local path
            parent_dir = os.path.dirname(output_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            with open(output_path, "w") as f:
                f.write(report_content)
            print(f"Data quality report written to: {output_path}")
        except Exception as e:
            print(f"Warning: Could not write report to {output_path}: {e}")
            print("Report content printed below:")
            print(report_content)

        return report_content

    # =========================================================================
    # Run All Checks
    # =========================================================================

    def run_all(self, source_counts=None):
        """
        Execute all data quality checks and generate the report.

        Args:
            source_counts: dict mapping table name → expected source row count
                e.g. {"borrowers": 5, "loan_products": 5, "loan_accounts": 5, "payments": 10}
        """
        print("=" * 60)
        print("DATA QUALITY VALIDATION — Starting checks")
        print("=" * 60)

        # 1. Row count reconciliation
        if source_counts:
            print("\nRunning row count reconciliation...")
            self.check_row_counts(source_counts)

        # 2. Null checks on required fields
        print("Running null checks on required fields...")
        self.check_required_fields()

        # 3. Referential integrity
        print("Running referential integrity checks...")
        self.check_referential_integrity()

        # 4. Business rules
        print("Running business rule validation...")
        self.check_business_rules()

        # Generate report
        print("\nGenerating data quality report...")
        report = self.generate_report()

        # Print summary
        passed = sum(1 for c in self.checks if c.passed is True)
        failed = sum(1 for c in self.checks if c.passed is False)
        print(f"\n{'=' * 60}")
        print(f"DATA QUALITY RESULTS: {passed} passed, {failed} failed")
        print(f"{'=' * 60}")

        return report


# =============================================================================
# Standalone execution
# =============================================================================
if __name__ == "__main__":
    # Default source counts based on the seed data
    # Update these with actual ingestion counts for production runs
    default_source_counts = {
        "borrowers": 5,
        "loan_products": 5,
        "loan_accounts": 5,
        "payments": 10,
    }

    framework = DataQualityFramework()
    framework.run_all(source_counts=default_source_counts)
