"""
Data Quality Framework for CDW Legacy to Delta Lake Migration.

Runs post-ingestion validation checks:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan and borrower tables
  4. Business rule validation

Generates a DATA_QUALITY_REPORT.md summarizing pass/fail results.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, count, sum as spark_sum, when, lit

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("data_quality")

CATALOG = "lending_warehouse"
SCHEMA = "loan_management"


# ---------------------------------------------------------------------------
# Data Quality Result Model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Result of a single data quality check."""
    category: str
    check_name: str
    passed: bool
    details: str
    severity: str = "ERROR"  # ERROR, WARNING, INFO


@dataclass
class QualityReport:
    """Aggregated quality report."""
    run_timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"))
    results: list = field(default_factory=list)

    @property
    def total_checks(self) -> int:
        return len(self.results)

    @property
    def passed_checks(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_checks(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def overall_status(self) -> str:
        errors = [r for r in self.results if not r.passed and r.severity == "ERROR"]
        if errors:
            return "FAILED"
        warnings = [r for r in self.results if not r.passed and r.severity == "WARNING"]
        if warnings:
            return "PASSED WITH WARNINGS"
        return "PASSED"

    def add(self, result: CheckResult):
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info(f"[{status}] {result.category} > {result.check_name}: {result.details}")


# ---------------------------------------------------------------------------
# Check Implementations
# ---------------------------------------------------------------------------


def check_row_count_reconciliation(
    spark: SparkSession,
    report: QualityReport,
    source_counts: dict,
):
    """
    Verify that source and target row counts match for each table.

    Args:
        source_counts: Dict mapping table name -> expected source row count.
                       e.g. {"borrowers": 5, "loan_products": 5, ...}
    """
    table_map = {
        "borrowers": f"{CATALOG}.{SCHEMA}.borrowers",
        "loan_products": f"{CATALOG}.{SCHEMA}.loan_products",
        "loan_accounts": f"{CATALOG}.{SCHEMA}.loan_accounts",
        "payments": f"{CATALOG}.{SCHEMA}.payments",
    }

    for table_name, full_name in table_map.items():
        try:
            target_count = spark.table(full_name).count()
            expected = source_counts.get(table_name, 0)
            passed = target_count == expected

            report.add(CheckResult(
                category="Row Count Reconciliation",
                check_name=f"{table_name}: source vs target",
                passed=passed,
                details=f"Source={expected}, Target={target_count}",
                severity="ERROR" if not passed else "INFO",
            ))
        except Exception as e:
            report.add(CheckResult(
                category="Row Count Reconciliation",
                check_name=f"{table_name}: table accessible",
                passed=False,
                details=f"Error accessing table: {str(e)}",
                severity="ERROR",
            ))


def check_required_fields_not_null(spark: SparkSession, report: QualityReport):
    """Check that required (NOT NULL) fields have no null values."""
    required_fields = {
        "borrowers": ["external_id", "first_name", "last_name", "status"],
        "loan_products": ["code", "name", "type", "is_active"],
        "loan_accounts": [
            "account_number", "borrower_id", "product_id",
            "original_amount", "current_balance", "interest_rate",
            "term_months", "monthly_payment", "origination_date",
            "maturity_date", "status",
        ],
        "payments": ["loan_account_id", "payment_date", "total_amount", "type", "status"],
    }

    for table_name, fields in required_fields.items():
        full_name = f"{CATALOG}.{SCHEMA}.{table_name}"
        try:
            df = spark.table(full_name)
            total = df.count()

            for field_name in fields:
                null_count = df.filter(col(field_name).isNull()).count()
                passed = null_count == 0

                report.add(CheckResult(
                    category="Null Checks",
                    check_name=f"{table_name}.{field_name} NOT NULL",
                    passed=passed,
                    details=f"{null_count}/{total} records have NULL" if not passed else f"0/{total} nulls",
                    severity="ERROR" if not passed else "INFO",
                ))
        except Exception as e:
            report.add(CheckResult(
                category="Null Checks",
                check_name=f"{table_name}: field null checks",
                passed=False,
                details=f"Error: {str(e)}",
                severity="ERROR",
            ))


def check_referential_integrity(spark: SparkSession, report: QualityReport):
    """Verify FK relationships between tables."""

    # loan_accounts.borrower_id -> borrowers.id
    try:
        loans_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")
        borrowers_df = spark.table(f"{CATALOG}.{SCHEMA}.borrowers")

        orphan_borrowers = loans_df.join(
            borrowers_df,
            loans_df["borrower_id"] == borrowers_df["id"],
            "left_anti"
        ).count()

        # left_anti gives rows in loans_df with no match in borrowers_df
        # Actually we need to check the other way
        orphan_count = loans_df.alias("l").join(
            borrowers_df.alias("b"),
            col("l.borrower_id") == col("b.id"),
            "left"
        ).filter(col("b.id").isNull()).count()

        passed = orphan_count == 0
        report.add(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.borrower_id -> borrowers.id",
            passed=passed,
            details=f"{orphan_count} orphan records" if not passed else "All FKs resolve",
            severity="ERROR" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.borrower_id -> borrowers.id",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))

    # loan_accounts.product_id -> loan_products.id
    try:
        loans_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")
        products_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_products")

        orphan_count = loans_df.alias("l").join(
            products_df.alias("p"),
            col("l.product_id") == col("p.id"),
            "left"
        ).filter(col("p.id").isNull()).count()

        passed = orphan_count == 0
        report.add(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.product_id -> loan_products.id",
            passed=passed,
            details=f"{orphan_count} orphan records" if not passed else "All FKs resolve",
            severity="ERROR" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.product_id -> loan_products.id",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))

    # payments.loan_account_id -> loan_accounts.id
    try:
        payments_df = spark.table(f"{CATALOG}.{SCHEMA}.payments")
        loans_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")

        orphan_count = payments_df.alias("p").join(
            loans_df.alias("l"),
            col("p.loan_account_id") == col("l.id"),
            "left"
        ).filter(col("l.id").isNull()).count()

        passed = orphan_count == 0
        report.add(CheckResult(
            category="Referential Integrity",
            check_name="payments.loan_account_id -> loan_accounts.id",
            passed=passed,
            details=f"{orphan_count} orphan records" if not passed else "All FKs resolve",
            severity="ERROR" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Referential Integrity",
            check_name="payments.loan_account_id -> loan_accounts.id",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))


def check_business_rules(spark: SparkSession, report: QualityReport):
    """Validate domain-specific business rules."""

    # Rule 1: Active loans must have positive balance
    try:
        loans_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")

        active_zero_balance = loans_df.filter(
            (col("status") == "ACTIVE") & (col("current_balance") <= 0)
        ).count()

        passed = active_zero_balance == 0
        report.add(CheckResult(
            category="Business Rules",
            check_name="Active loans have positive balance",
            passed=passed,
            details=f"{active_zero_balance} active loans with balance <= 0" if not passed else "All active loans have positive balance",
            severity="ERROR" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Active loans have positive balance",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))

    # Rule 2: Closed loans should have a maturity_date in the past or current_balance = 0
    try:
        loans_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")
        from pyspark.sql.functions import current_date

        closed_invalid = loans_df.filter(
            (col("status") == "CLOSED") &
            (col("current_balance") > 0) &
            (col("maturity_date") > current_date())
        ).count()

        passed = closed_invalid == 0
        report.add(CheckResult(
            category="Business Rules",
            check_name="Closed loans have zero balance or past maturity",
            passed=passed,
            details=f"{closed_invalid} closed loans with balance > 0 and future maturity" if not passed else "All closed loans validated",
            severity="WARNING" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Closed loans have zero balance or past maturity",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))

    # Rule 3: Interest rate must be between 0 and 25%
    try:
        loans_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")

        invalid_rate = loans_df.filter(
            (col("interest_rate") < 0) | (col("interest_rate") > 25)
        ).count()

        passed = invalid_rate == 0
        report.add(CheckResult(
            category="Business Rules",
            check_name="Interest rate within valid range (0-25%)",
            passed=passed,
            details=f"{invalid_rate} loans with out-of-range interest rates" if not passed else "All rates within valid range",
            severity="ERROR" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Interest rate within valid range (0-25%)",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))

    # Rule 4: Payment amounts must be positive
    try:
        payments_df = spark.table(f"{CATALOG}.{SCHEMA}.payments")

        negative_payments = payments_df.filter(col("total_amount") <= 0).count()

        passed = negative_payments == 0
        report.add(CheckResult(
            category="Business Rules",
            check_name="Payment amounts are positive",
            passed=passed,
            details=f"{negative_payments} payments with non-positive amounts" if not passed else "All payment amounts positive",
            severity="ERROR" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Payment amounts are positive",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))

    # Rule 5: Origination date must be before maturity date
    try:
        loans_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")

        invalid_dates = loans_df.filter(
            col("origination_date") >= col("maturity_date")
        ).count()

        passed = invalid_dates == 0
        report.add(CheckResult(
            category="Business Rules",
            check_name="Origination date before maturity date",
            passed=passed,
            details=f"{invalid_dates} loans with origination >= maturity" if not passed else "All date ranges valid",
            severity="ERROR" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Origination date before maturity date",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))

    # Rule 6: Credit scores should be in valid range (300-850)
    try:
        borrowers_df = spark.table(f"{CATALOG}.{SCHEMA}.borrowers")

        invalid_scores = borrowers_df.filter(
            col("credit_score").isNotNull() &
            ((col("credit_score") < 300) | (col("credit_score") > 850))
        ).count()

        passed = invalid_scores == 0
        report.add(CheckResult(
            category="Business Rules",
            check_name="Credit scores in valid range (300-850)",
            passed=passed,
            details=f"{invalid_scores} borrowers with out-of-range credit scores" if not passed else "All credit scores in valid range",
            severity="WARNING" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="Credit scores in valid range (300-850)",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))

    # Rule 7: LTV percent should be between 0 and 200
    try:
        loans_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")

        invalid_ltv = loans_df.filter(
            col("ltv_percent").isNotNull() &
            ((col("ltv_percent") < 0) | (col("ltv_percent") > 200))
        ).count()

        passed = invalid_ltv == 0
        report.add(CheckResult(
            category="Business Rules",
            check_name="LTV percent in valid range (0-200%)",
            passed=passed,
            details=f"{invalid_ltv} loans with out-of-range LTV" if not passed else "All LTV values in valid range",
            severity="WARNING" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="LTV percent in valid range (0-200%)",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))

    # Rule 8: Delinquent loans (DLQ_DAYS > 0) should not be status ACTIVE without warning
    try:
        loans_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_accounts")

        delinquent_active = loans_df.filter(
            (col("status") == "ACTIVE") & (col("delinquency_days") > 90)
        ).count()

        passed = delinquent_active == 0
        report.add(CheckResult(
            category="Business Rules",
            check_name="No active loans with >90 days delinquency",
            passed=passed,
            details=f"{delinquent_active} active loans severely delinquent (>90 days)" if not passed else "No severely delinquent active loans",
            severity="WARNING" if not passed else "INFO",
        ))
    except Exception as e:
        report.add(CheckResult(
            category="Business Rules",
            check_name="No active loans with >90 days delinquency",
            passed=False,
            details=f"Error: {str(e)}",
            severity="ERROR",
        ))


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------


def generate_report_markdown(report: QualityReport) -> str:
    """Generate a markdown report from the quality check results."""
    lines = []
    lines.append("# Data Quality Report")
    lines.append("")
    lines.append(f"**Run Timestamp:** {report.run_timestamp}")
    lines.append(f"**Overall Status:** {report.overall_status}")
    lines.append(f"**Total Checks:** {report.total_checks}")
    lines.append(f"**Passed:** {report.passed_checks}")
    lines.append(f"**Failed:** {report.failed_checks}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Group by category
    categories = {}
    for result in report.results:
        categories.setdefault(result.category, []).append(result)

    for category, results in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Status | Check | Severity | Details |")
        lines.append("|--------|-------|----------|---------|")
        for r in results:
            status_icon = "PASS" if r.passed else "FAIL"
            lines.append(f"| {status_icon} | {r.check_name} | {r.severity} | {r.details} |")
        lines.append("")

    # Summary
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    if report.overall_status == "PASSED":
        lines.append("All data quality checks passed successfully. The migration data is ready for production use.")
    elif report.overall_status == "PASSED WITH WARNINGS":
        lines.append("Data quality checks passed with warnings. Review WARNING items before production deployment.")
    else:
        lines.append("**Data quality checks FAILED.** Review ERROR items and remediate before production deployment.")
        lines.append("")
        lines.append("### Failed Checks:")
        lines.append("")
        for r in report.results:
            if not r.passed and r.severity == "ERROR":
                lines.append(f"- **{r.check_name}**: {r.details}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def run_quality_checks(source_counts: Optional[dict] = None, output_path: str = "DATA_QUALITY_REPORT.md"):
    """
    Run all data quality checks and generate the report.

    Args:
        source_counts: Dict of table_name -> expected row count for reconciliation.
                       If None, reconciliation checks are skipped.
        output_path: Path to write the markdown report.
    """
    spark = SparkSession.builder.appName("CDW_DataQuality").getOrCreate()
    report = QualityReport()

    logger.info("=" * 70)
    logger.info("DATA QUALITY VALIDATION")
    logger.info("=" * 70)

    # 1. Row count reconciliation
    if source_counts:
        logger.info("--- Row Count Reconciliation ---")
        check_row_count_reconciliation(spark, report, source_counts)

    # 2. Null checks on required fields
    logger.info("--- Null Checks ---")
    check_required_fields_not_null(spark, report)

    # 3. Referential integrity
    logger.info("--- Referential Integrity ---")
    check_referential_integrity(spark, report)

    # 4. Business rules
    logger.info("--- Business Rule Validation ---")
    check_business_rules(spark, report)

    # Generate report
    logger.info("=" * 70)
    logger.info(f"QUALITY CHECK COMPLETE: {report.overall_status}")
    logger.info(f"  Passed: {report.passed_checks}/{report.total_checks}")
    logger.info(f"  Failed: {report.failed_checks}/{report.total_checks}")
    logger.info("=" * 70)

    report_md = generate_report_markdown(report)

    # Write report to file
    with open(output_path, "w") as f:
        f.write(report_md)
    logger.info(f"Report written to: {output_path}")

    # Also write to DBFS if available
    try:
        dbutils = spark._jvm.com.databricks.dbutils.DBUtilsHolder.dbutils()
        dbfs_path = f"/FileStore/migration_reports/DATA_QUALITY_REPORT_{report.run_timestamp.replace(' ', '_').replace(':', '-')}.md"
        dbutils.fs.put(dbfs_path, report_md, overwrite=True)
        logger.info(f"Report also written to DBFS: {dbfs_path}")
    except Exception:
        pass  # Not running on Databricks, skip DBFS write

    return report


if __name__ == "__main__":
    import sys

    # Optional: pass source counts as JSON string argument
    source_counts = None
    if len(sys.argv) > 1:
        import json
        source_counts = json.loads(sys.argv[1])

    output_path = sys.argv[2] if len(sys.argv) > 2 else "DATA_QUALITY_REPORT.md"
    run_quality_checks(source_counts=source_counts, output_path=output_path)
