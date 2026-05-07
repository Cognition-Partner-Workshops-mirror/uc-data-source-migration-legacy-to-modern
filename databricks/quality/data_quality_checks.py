"""
Data Quality Framework: Post-Ingestion Validation
===================================================
Runs comprehensive data quality checks after the ingestion pipeline completes.
Validates row counts, null constraints, referential integrity, and business rules.
Generates a DATA_QUALITY_REPORT.md summarizing pass/fail results.

Execution order: Run AFTER all four ingestion scripts have completed.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, when, lit, sum as spark_sum
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("data_quality_checks")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Expected source record counts (from legacy system extract metadata)
EXPECTED_SOURCE_COUNTS = {
    "borrowers": 5,
    "loan_products": 5,
    "loan_accounts": 5,
    "payments": 10
}

# Output path for the quality report
REPORT_OUTPUT_PATH = "/mnt/reports/DATA_QUALITY_REPORT.md"

# Database/catalog name
DATABASE = "loan_warehouse"


class DataQualityResult:
    """Stores the result of a single data quality check."""

    def __init__(self, check_name, category, passed, details="", severity="ERROR"):
        self.check_name = check_name
        self.category = category
        self.passed = passed
        self.details = details
        self.severity = severity  # ERROR, WARNING, INFO
        self.timestamp = datetime.utcnow().isoformat()


class DataQualityFramework:
    """
    Orchestrates data quality validation across all migrated tables.
    Collects results and generates a markdown report.
    """

    def __init__(self, spark):
        self.spark = spark
        self.results = []

    def add_result(self, result):
        """Add a check result to the collection."""
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info(f"[{status}] {result.category} - {result.check_name}: {result.details}")

    # =========================================================================
    # Category 1: Row Count Reconciliation
    # =========================================================================
    def check_row_counts(self):
        """
        Verify that target table row counts match expected source counts.
        Ensures no records were silently dropped during ingestion.
        """
        logger.info("Running row count reconciliation checks...")

        for table_name, expected_count in EXPECTED_SOURCE_COUNTS.items():
            target_table = f"{DATABASE}.{table_name}"
            try:
                actual_count = self.spark.table(target_table).count()
                passed = actual_count == expected_count
                details = (
                    f"Expected: {expected_count}, Actual: {actual_count}"
                    + ("" if passed else f" (MISSING {expected_count - actual_count} records)")
                )
                self.add_result(DataQualityResult(
                    check_name=f"Row count - {table_name}",
                    category="Row Count Reconciliation",
                    passed=passed,
                    details=details,
                    severity="ERROR" if not passed else "INFO"
                ))
            except Exception as e:
                self.add_result(DataQualityResult(
                    check_name=f"Row count - {table_name}",
                    category="Row Count Reconciliation",
                    passed=False,
                    details=f"Table not accessible: {str(e)}",
                    severity="ERROR"
                ))

    # =========================================================================
    # Category 2: Null Checks on Required Fields
    # =========================================================================
    def check_null_constraints(self):
        """
        Validate that required (NOT NULL) fields have no null values.
        Based on the modern schema constraints defined in the DDL.
        """
        logger.info("Running null constraint checks...")

        # Define required fields per table
        required_fields = {
            "borrowers": ["external_id", "first_name", "last_name"],
            "loan_products": ["code", "name", "type", "term_months", "rate_type"],
            "loan_accounts": [
                "account_number", "borrower_id", "product_id",
                "original_amount", "current_balance", "interest_rate",
                "term_months", "monthly_payment", "origination_date", "maturity_date"
            ],
            "payments": [
                "loan_account_id", "payment_date", "total_amount", "type", "status"
            ]
        }

        for table_name, fields in required_fields.items():
            target_table = f"{DATABASE}.{table_name}"
            try:
                df = self.spark.table(target_table)
                for field in fields:
                    null_count = df.filter(col(field).isNull()).count()
                    passed = null_count == 0
                    details = (
                        f"No nulls found in {table_name}.{field}"
                        if passed
                        else f"Found {null_count} null values in {table_name}.{field}"
                    )
                    self.add_result(DataQualityResult(
                        check_name=f"NOT NULL - {table_name}.{field}",
                        category="Null Checks",
                        passed=passed,
                        details=details,
                        severity="ERROR" if not passed else "INFO"
                    ))
            except Exception as e:
                self.add_result(DataQualityResult(
                    check_name=f"NOT NULL - {table_name}",
                    category="Null Checks",
                    passed=False,
                    details=f"Table not accessible: {str(e)}",
                    severity="ERROR"
                ))

    # =========================================================================
    # Category 3: Referential Integrity
    # =========================================================================
    def check_referential_integrity(self):
        """
        Validate foreign key relationships between tables:
        - loan_accounts.borrower_id → borrowers.id
        - loan_accounts.product_id → loan_products.id
        - payments.loan_account_id → loan_accounts.id
        """
        logger.info("Running referential integrity checks...")

        # Check loan_accounts.borrower_id → borrowers.id
        try:
            loan_accounts = self.spark.table(f"{DATABASE}.loan_accounts")
            borrowers = self.spark.table(f"{DATABASE}.borrowers")

            orphan_borrower_refs = (
                loan_accounts
                .join(borrowers, loan_accounts["borrower_id"] == borrowers["id"], "left_anti")
                .count()
            )
            passed = orphan_borrower_refs == 0
            self.add_result(DataQualityResult(
                check_name="FK - loan_accounts.borrower_id → borrowers.id",
                category="Referential Integrity",
                passed=passed,
                details=(
                    "All borrower references valid"
                    if passed
                    else f"Found {orphan_borrower_refs} orphan borrower references"
                ),
                severity="ERROR" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="FK - loan_accounts.borrower_id → borrowers.id",
                category="Referential Integrity",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

        # Check loan_accounts.product_id → loan_products.id
        try:
            loan_accounts = self.spark.table(f"{DATABASE}.loan_accounts")
            loan_products = self.spark.table(f"{DATABASE}.loan_products")

            orphan_product_refs = (
                loan_accounts
                .join(loan_products, loan_accounts["product_id"] == loan_products["id"], "left_anti")
                .count()
            )
            passed = orphan_product_refs == 0
            self.add_result(DataQualityResult(
                check_name="FK - loan_accounts.product_id → loan_products.id",
                category="Referential Integrity",
                passed=passed,
                details=(
                    "All product references valid"
                    if passed
                    else f"Found {orphan_product_refs} orphan product references"
                ),
                severity="ERROR" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="FK - loan_accounts.product_id → loan_products.id",
                category="Referential Integrity",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

        # Check payments.loan_account_id → loan_accounts.id
        try:
            payments = self.spark.table(f"{DATABASE}.payments")
            loan_accounts = self.spark.table(f"{DATABASE}.loan_accounts")

            orphan_loan_refs = (
                payments
                .join(loan_accounts, payments["loan_account_id"] == loan_accounts["id"], "left_anti")
                .count()
            )
            passed = orphan_loan_refs == 0
            self.add_result(DataQualityResult(
                check_name="FK - payments.loan_account_id → loan_accounts.id",
                category="Referential Integrity",
                passed=passed,
                details=(
                    "All loan account references valid"
                    if passed
                    else f"Found {orphan_loan_refs} orphan loan account references"
                ),
                severity="ERROR" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="FK - payments.loan_account_id → loan_accounts.id",
                category="Referential Integrity",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

    # =========================================================================
    # Category 4: Business Rule Validation
    # =========================================================================
    def check_business_rules(self):
        """
        Validate domain-specific business rules:
        - Active loans must have balance > 0
        - Closed loans should have a maturity_date <= today (or explicit close)
        - Payment amounts must be positive
        - Credit scores in valid range (300-850)
        - Interest rates in valid range (0-30%)
        - Delinquency days >= 0
        """
        logger.info("Running business rule validation checks...")

        # Rule: Active loans must have current_balance > 0
        try:
            loan_accounts = self.spark.table(f"{DATABASE}.loan_accounts")
            active_zero_balance = (
                loan_accounts
                .filter((col("status") == "Active") & (col("current_balance") <= 0))
                .count()
            )
            passed = active_zero_balance == 0
            self.add_result(DataQualityResult(
                check_name="Active loans must have balance > 0",
                category="Business Rules",
                passed=passed,
                details=(
                    "All active loans have positive balance"
                    if passed
                    else f"Found {active_zero_balance} active loans with balance <= 0"
                ),
                severity="ERROR" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="Active loans must have balance > 0",
                category="Business Rules",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

        # Rule: Payment total_amount must be positive
        try:
            payments = self.spark.table(f"{DATABASE}.payments")
            negative_payments = (
                payments
                .filter(col("total_amount") <= 0)
                .count()
            )
            passed = negative_payments == 0
            self.add_result(DataQualityResult(
                check_name="Payment amounts must be positive",
                category="Business Rules",
                passed=passed,
                details=(
                    "All payment amounts are positive"
                    if passed
                    else f"Found {negative_payments} payments with non-positive amounts"
                ),
                severity="ERROR" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="Payment amounts must be positive",
                category="Business Rules",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

        # Rule: Credit scores in valid range (300-850)
        try:
            borrowers = self.spark.table(f"{DATABASE}.borrowers")
            invalid_scores = (
                borrowers
                .filter(
                    col("credit_score").isNotNull() &
                    ((col("credit_score") < 300) | (col("credit_score") > 850))
                )
                .count()
            )
            passed = invalid_scores == 0
            self.add_result(DataQualityResult(
                check_name="Credit scores in valid range (300-850)",
                category="Business Rules",
                passed=passed,
                details=(
                    "All credit scores within valid range"
                    if passed
                    else f"Found {invalid_scores} borrowers with invalid credit scores"
                ),
                severity="WARNING" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="Credit scores in valid range (300-850)",
                category="Business Rules",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

        # Rule: Interest rates in valid range (0-30%)
        try:
            loan_accounts = self.spark.table(f"{DATABASE}.loan_accounts")
            invalid_rates = (
                loan_accounts
                .filter(
                    (col("interest_rate") < 0) | (col("interest_rate") > 30)
                )
                .count()
            )
            passed = invalid_rates == 0
            self.add_result(DataQualityResult(
                check_name="Interest rates in valid range (0-30%)",
                category="Business Rules",
                passed=passed,
                details=(
                    "All interest rates within valid range"
                    if passed
                    else f"Found {invalid_rates} loans with invalid interest rates"
                ),
                severity="WARNING" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="Interest rates in valid range (0-30%)",
                category="Business Rules",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

        # Rule: Delinquency days must be non-negative
        try:
            loan_accounts = self.spark.table(f"{DATABASE}.loan_accounts")
            negative_delinquency = (
                loan_accounts
                .filter(col("delinquency_days") < 0)
                .count()
            )
            passed = negative_delinquency == 0
            self.add_result(DataQualityResult(
                check_name="Delinquency days must be >= 0",
                category="Business Rules",
                passed=passed,
                details=(
                    "All delinquency days are non-negative"
                    if passed
                    else f"Found {negative_delinquency} loans with negative delinquency days"
                ),
                severity="ERROR" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="Delinquency days must be >= 0",
                category="Business Rules",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

        # Rule: Loan status must be a valid expanded value
        try:
            loan_accounts = self.spark.table(f"{DATABASE}.loan_accounts")
            valid_statuses = ["Active", "Closed", "Default", "Forbearance"]
            invalid_status = (
                loan_accounts
                .filter(~col("status").isin(valid_statuses))
                .count()
            )
            passed = invalid_status == 0
            self.add_result(DataQualityResult(
                check_name="Loan status values are valid",
                category="Business Rules",
                passed=passed,
                details=(
                    "All loan statuses are valid expanded values"
                    if passed
                    else f"Found {invalid_status} loans with unexpected status values"
                ),
                severity="ERROR" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="Loan status values are valid",
                category="Business Rules",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

        # Rule: Origination date must be before maturity date
        try:
            loan_accounts = self.spark.table(f"{DATABASE}.loan_accounts")
            date_mismatch = (
                loan_accounts
                .filter(col("origination_date") >= col("maturity_date"))
                .count()
            )
            passed = date_mismatch == 0
            self.add_result(DataQualityResult(
                check_name="Origination date before maturity date",
                category="Business Rules",
                passed=passed,
                details=(
                    "All origination dates precede maturity dates"
                    if passed
                    else f"Found {date_mismatch} loans where origination >= maturity"
                ),
                severity="ERROR" if not passed else "INFO"
            ))
        except Exception as e:
            self.add_result(DataQualityResult(
                check_name="Origination date before maturity date",
                category="Business Rules",
                passed=False,
                details=f"Check failed: {str(e)}",
                severity="ERROR"
            ))

    # =========================================================================
    # Report Generation
    # =========================================================================
    def generate_report(self, output_path=None):
        """
        Generate a markdown report summarizing all data quality check results.
        Returns the report content as a string and optionally writes to file.
        """
        if output_path is None:
            output_path = REPORT_OUTPUT_PATH

        total_checks = len(self.results)
        passed_checks = sum(1 for r in self.results if r.passed)
        failed_checks = total_checks - passed_checks

        # Build the markdown report
        report_lines = [
            "# Data Quality Report",
            "",
            f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Pipeline:** Legacy CDW → Delta Lake Migration",
            f"**Database:** {DATABASE}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Checks | {total_checks} |",
            f"| Passed | {passed_checks} |",
            f"| Failed | {failed_checks} |",
            f"| Pass Rate | {(passed_checks / total_checks * 100):.1f}% |",
            "",
            f"**Overall Status:** {'PASS' if failed_checks == 0 else 'FAIL'}",
            "",
        ]

        # Group results by category
        categories = {}
        for result in self.results:
            if result.category not in categories:
                categories[result.category] = []
            categories[result.category].append(result)

        # Render each category
        for category, checks in categories.items():
            cat_passed = sum(1 for c in checks if c.passed)
            cat_total = len(checks)
            report_lines.append(f"## {category} ({cat_passed}/{cat_total} passed)")
            report_lines.append("")
            report_lines.append("| Check | Status | Details |")
            report_lines.append("|-------|--------|---------|")

            for check in checks:
                status_icon = "PASS" if check.passed else "FAIL"
                report_lines.append(
                    f"| {check.check_name} | {status_icon} | {check.details} |"
                )

            report_lines.append("")

        report_content = "\n".join(report_lines)

        # Write report to file
        logger.info(f"Writing data quality report to: {output_path}")
        try:
            # Use DBFS or local filesystem depending on environment
            dbutils = self.spark._jvm.com.databricks.dbutils.DBUtilsHolder.dbutils()
            dbutils.fs.put(output_path, report_content, True)
        except Exception:
            # Fallback: write locally if not running in Databricks
            logger.info("Writing report to local filesystem (non-Databricks environment)")
            with open(output_path, "w") as f:
                f.write(report_content)

        logger.info(f"Report generated: {total_checks} checks, {passed_checks} passed, {failed_checks} failed")
        return report_content

    # =========================================================================
    # Main Orchestrator
    # =========================================================================
    def run_all_checks(self):
        """Run all data quality checks in sequence."""
        logger.info("=" * 60)
        logger.info("Starting Data Quality Validation")
        logger.info("=" * 60)

        self.check_row_counts()
        self.check_null_constraints()
        self.check_referential_integrity()
        self.check_business_rules()

        report = self.generate_report()

        logger.info("=" * 60)
        logger.info("Data Quality Validation Complete")
        logger.info("=" * 60)

        return report


def main():
    """Main entry point for data quality validation."""
    spark = (
        SparkSession.builder
        .appName("LoanMigration_DataQuality")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )

    framework = DataQualityFramework(spark)
    report = framework.run_all_checks()

    # Print the report to stdout for notebook visibility
    print(report)

    # Return non-zero exit if any checks failed
    failed = sum(1 for r in framework.results if not r.passed)
    if failed > 0:
        logger.error(f"Data quality validation FAILED with {failed} failing checks")
        raise SystemExit(1)

    spark.stop()


if __name__ == "__main__":
    main()
