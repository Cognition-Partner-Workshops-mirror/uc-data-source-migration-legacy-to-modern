"""
data_quality_checks.py — Post-ingestion data quality validation framework.

Runs after all ingestion scripts complete to verify:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts ↔ borrowers ↔ loan_products ↔ payments
  4. Business rule validation (e.g., active loans must have balance > 0)
  5. Generates a DATA_QUALITY_REPORT.md summarizing all pass/fail results

Design: Each check is a self-contained function that returns a CheckResult
named tuple. The orchestrator collects all results and writes the final report.
"""

from dataclasses import dataclass, field
from typing import List
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
import logging
from datetime import datetime

logger = logging.getLogger("cdw_migration.quality")

# ---------------------------------------------------------------------------
# Configuration — source paths for row count reconciliation
# ---------------------------------------------------------------------------
SOURCE_PATHS = {
    "borrowers": "dbfs:/mnt/legacy-extract/CDW_BORR_MSTR",
    "loan_products": "dbfs:/mnt/legacy-extract/CDW_LN_PROD",
    "loan_accounts": "dbfs:/mnt/legacy-extract/CDW_LN_ACCT",
    "payments": "dbfs:/mnt/legacy-extract/CDW_PMT_HIST",
}

SOURCE_FORMAT = "csv"

TARGET_TABLES = {
    "borrowers": "loan_warehouse.borrowers",
    "loan_products": "loan_warehouse.loan_products",
    "loan_accounts": "loan_warehouse.loan_accounts",
    "payments": "loan_warehouse.payments",
}

# Path where the quality report markdown file is written
REPORT_OUTPUT_PATH = "dbfs:/mnt/migration-reports/DATA_QUALITY_REPORT.md"


# ---------------------------------------------------------------------------
# Check Result Model
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Represents the outcome of a single data quality check."""
    category: str       # e.g., "Row Count", "Null Check", "Referential Integrity"
    table: str          # Target table name
    check_name: str     # Short description of the check
    passed: bool        # Whether the check passed
    details: str        # Detailed message (counts, mismatches, etc.)
    severity: str = "ERROR"  # ERROR, WARNING, INFO


@dataclass
class QualityReport:
    """Aggregates all check results for the migration run."""
    run_timestamp: str = ""
    results: List[CheckResult] = field(default_factory=list)

    @property
    def total_checks(self) -> int:
        return len(self.results)

    @property
    def passed_checks(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_checks(self) -> int:
        return sum(1 for r in self.results if not r.passed)


# ===========================================================================
# 1. ROW COUNT RECONCILIATION
# ===========================================================================

def check_row_counts(spark: SparkSession, report: QualityReport) -> None:
    """Compare source file row counts against target Delta table row counts.

    A mismatch indicates records were either dropped during ingestion or
    duplicated. Both scenarios should be investigated.
    """
    for entity, target_table in TARGET_TABLES.items():
        source_path = SOURCE_PATHS[entity]

        # Read source count
        try:
            if SOURCE_FORMAT == "csv":
                source_df = spark.read.option("header", "true").csv(source_path)
            else:
                source_df = spark.read.parquet(source_path)
            source_count = source_df.count()
        except Exception as e:
            # Source file may not exist in test environments — log and skip
            report.results.append(CheckResult(
                category="Row Count",
                table=target_table,
                check_name=f"Source row count for {entity}",
                passed=False,
                details=f"Could not read source at {source_path}: {str(e)}",
                severity="WARNING",
            ))
            continue

        # Read target count
        target_count = spark.table(target_table).count()

        passed = source_count == target_count
        report.results.append(CheckResult(
            category="Row Count",
            table=target_table,
            check_name=f"Row count reconciliation: {entity}",
            passed=passed,
            details=(
                f"Source: {source_count}, Target: {target_count}"
                + ("" if passed else f" — DELTA: {target_count - source_count}")
            ),
        ))
        logger.info(
            "[Row Count] %s — source=%d, target=%d, match=%s",
            entity, source_count, target_count, passed,
        )


# ===========================================================================
# 2. NULL CHECKS ON REQUIRED FIELDS
# ===========================================================================

# Mapping of table → list of columns that must NOT be null
REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": [
        "external_id", "first_name", "last_name", "status",
    ],
    "loan_warehouse.loan_products": [
        "code", "name", "type", "is_active",
    ],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id", "status",
        "original_amount", "current_balance", "origination_date",
    ],
    "loan_warehouse.payments": [
        "legacy_sequence_nbr", "loan_account_id", "payment_date",
        "total_amount", "type", "status",
    ],
}


def check_nulls(spark: SparkSession, report: QualityReport) -> None:
    """Verify that required (NOT NULL) columns contain no null values."""
    for table, columns in REQUIRED_FIELDS.items():
        df = spark.table(table)
        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            passed = null_count == 0
            report.results.append(CheckResult(
                category="Null Check",
                table=table,
                check_name=f"NOT NULL: {col_name}",
                passed=passed,
                details=f"Null count: {null_count}" + ("" if passed else " — VIOLATION"),
            ))
            if not passed:
                logger.warning("[Null Check] %s.%s has %d NULLs", table, col_name, null_count)


# ===========================================================================
# 3. REFERENTIAL INTEGRITY
# ===========================================================================

def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Verify foreign key relationships between tables.

    Checks:
      - loan_accounts.borrower_id  → borrowers.id
      - loan_accounts.product_id   → loan_products.id
      - payments.loan_account_id   → loan_accounts.id
    """
    # --- loan_accounts.borrower_id → borrowers.id ---
    loans = spark.table("loan_warehouse.loan_accounts")
    borrowers = spark.table("loan_warehouse.borrowers")
    orphan_borrower = (
        loans
        .join(borrowers, loans["borrower_id"] == borrowers["id"], "left_anti")
        .count()
    )
    report.results.append(CheckResult(
        category="Referential Integrity",
        table="loan_warehouse.loan_accounts",
        check_name="FK: borrower_id → borrowers.id",
        passed=orphan_borrower == 0,
        details=f"Orphan loan_accounts (missing borrower): {orphan_borrower}",
    ))

    # --- loan_accounts.product_id → loan_products.id ---
    products = spark.table("loan_warehouse.loan_products")
    orphan_product = (
        loans
        .join(products, loans["product_id"] == products["id"], "left_anti")
        .count()
    )
    report.results.append(CheckResult(
        category="Referential Integrity",
        table="loan_warehouse.loan_accounts",
        check_name="FK: product_id → loan_products.id",
        passed=orphan_product == 0,
        details=f"Orphan loan_accounts (missing product): {orphan_product}",
    ))

    # --- payments.loan_account_id → loan_accounts.id ---
    payments = spark.table("loan_warehouse.payments")
    orphan_loan = (
        payments
        .join(loans, payments["loan_account_id"] == loans["id"], "left_anti")
        .count()
    )
    report.results.append(CheckResult(
        category="Referential Integrity",
        table="loan_warehouse.payments",
        check_name="FK: loan_account_id → loan_accounts.id",
        passed=orphan_loan == 0,
        details=f"Orphan payments (missing loan account): {orphan_loan}",
    ))


# ===========================================================================
# 4. BUSINESS RULE VALIDATION
# ===========================================================================

def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules on the migrated data.

    Rules:
      BR-1: Active loans must have current_balance > 0
      BR-2: Closed loans should have a maturity_date that is not null
      BR-3: Payment total must equal principal + interest + escrow + late_fee (± 0.01 tolerance)
      BR-4: Delinquency days must be >= 0 for all loans
      BR-5: Interest rate must be between 0 and 100 for all loans
      BR-6: Credit score must be between 300 and 850 for all borrowers (if not null)
    """
    loans = spark.table("loan_warehouse.loan_accounts")
    payments = spark.table("loan_warehouse.payments")
    borrowers = spark.table("loan_warehouse.borrowers")

    # --- BR-1: Active loans must have balance > 0 ---
    active_zero_bal = (
        loans
        .filter(F.col("status") == "ACTIVE")
        .filter((F.col("current_balance").isNull()) | (F.col("current_balance") <= 0))
        .count()
    )
    report.results.append(CheckResult(
        category="Business Rule",
        table="loan_warehouse.loan_accounts",
        check_name="BR-1: Active loans balance > 0",
        passed=active_zero_bal == 0,
        details=f"Active loans with balance <= 0: {active_zero_bal}",
    ))

    # --- BR-2: Closed loans must have maturity_date ---
    closed_no_maturity = (
        loans
        .filter(F.col("status") == "CLOSED")
        .filter(F.col("maturity_date").isNull())
        .count()
    )
    report.results.append(CheckResult(
        category="Business Rule",
        table="loan_warehouse.loan_accounts",
        check_name="BR-2: Closed loans have maturity_date",
        passed=closed_no_maturity == 0,
        details=f"Closed loans missing maturity_date: {closed_no_maturity}",
    ))

    # --- BR-3: Payment amount components sum check ---
    # total_amount ≈ principal_amount + interest_amount + escrow_amount + late_fee
    payment_sum_mismatch = (
        payments
        .withColumn(
            "_computed_total",
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0))
        )
        .filter(
            F.abs(F.col("total_amount") - F.col("_computed_total")) > 0.01
        )
        .count()
    )
    report.results.append(CheckResult(
        category="Business Rule",
        table="loan_warehouse.payments",
        check_name="BR-3: Payment components sum matches total (± $0.01)",
        passed=payment_sum_mismatch == 0,
        details=f"Payments with component sum mismatch: {payment_sum_mismatch}",
        severity="WARNING",
    ))

    # --- BR-4: Delinquency days >= 0 ---
    negative_dlq = (
        loans
        .filter(F.col("delinquency_days") < 0)
        .count()
    )
    report.results.append(CheckResult(
        category="Business Rule",
        table="loan_warehouse.loan_accounts",
        check_name="BR-4: Delinquency days >= 0",
        passed=negative_dlq == 0,
        details=f"Loans with negative delinquency days: {negative_dlq}",
    ))

    # --- BR-5: Interest rate between 0 and 100 ---
    bad_rate = (
        loans
        .filter(
            (F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)
        )
        .count()
    )
    report.results.append(CheckResult(
        category="Business Rule",
        table="loan_warehouse.loan_accounts",
        check_name="BR-5: Interest rate in [0, 100]",
        passed=bad_rate == 0,
        details=f"Loans with out-of-range interest rate: {bad_rate}",
    ))

    # --- BR-6: Credit score in [300, 850] where not null ---
    bad_credit = (
        borrowers
        .filter(F.col("credit_score").isNotNull())
        .filter(
            (F.col("credit_score") < 300) | (F.col("credit_score") > 850)
        )
        .count()
    )
    report.results.append(CheckResult(
        category="Business Rule",
        table="loan_warehouse.borrowers",
        check_name="BR-6: Credit score in [300, 850]",
        passed=bad_credit == 0,
        details=f"Borrowers with out-of-range credit score: {bad_credit}",
    ))


# ===========================================================================
# 5. REPORT GENERATION
# ===========================================================================

def generate_report_markdown(report: QualityReport) -> str:
    """Render the quality report as a Markdown document."""
    lines = []
    lines.append("# Data Quality Report — CDW → Delta Lake Migration")
    lines.append("")
    lines.append(f"**Run Timestamp:** {report.run_timestamp}")
    lines.append(f"**Total Checks:** {report.total_checks}")
    lines.append(f"**Passed:** {report.passed_checks}")
    lines.append(f"**Failed:** {report.failed_checks}")
    lines.append(
        f"**Overall Status:** {'PASS ✓' if report.failed_checks == 0 else 'FAIL ✗'}"
    )
    lines.append("")

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
            lines.append(
                f"| `{r.table}` | {r.check_name} | {status} | {r.details} | {r.severity} |"
            )
        lines.append("")

    # Summary of failures (if any)
    failures = [r for r in report.results if not r.passed]
    if failures:
        lines.append("## Failed Checks Summary")
        lines.append("")
        for i, r in enumerate(failures, 1):
            lines.append(f"{i}. **[{r.severity}]** `{r.table}` — {r.check_name}: {r.details}")
        lines.append("")
        lines.append("---")
        lines.append("**Action Required:** Investigate and resolve the above failures before")
        lines.append("promoting the migrated data to production.")
    else:
        lines.append("---")
        lines.append("All quality checks passed. The migrated data is ready for review.")

    return "\n".join(lines)


# ===========================================================================
# MAIN ORCHESTRATOR
# ===========================================================================

def main():
    """Run all data quality checks and generate the report."""
    spark = SparkSession.builder.appName("CDW Migration — Data Quality").getOrCreate()

    report = QualityReport(
        run_timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    )

    logger.info("=" * 60)
    logger.info("DATA QUALITY CHECKS — Starting")
    logger.info("=" * 60)

    # Run all check categories
    check_row_counts(spark, report)
    check_nulls(spark, report)
    check_referential_integrity(spark, report)
    check_business_rules(spark, report)

    # Generate report markdown
    report_md = generate_report_markdown(report)

    # Write report to DBFS
    spark.sparkContext.parallelize([report_md]).coalesce(1).saveAsTextFile(
        REPORT_OUTPUT_PATH + "_tmp"
    )
    logger.info("Data quality report written to %s", REPORT_OUTPUT_PATH)

    # Also print the report to the driver log for visibility
    print("\n" + report_md)

    logger.info("=" * 60)
    logger.info(
        "DATA QUALITY CHECKS — Complete: %d/%d passed",
        report.passed_checks, report.total_checks,
    )
    logger.info("=" * 60)

    # Return non-zero exit if any checks failed (useful for job orchestration)
    if report.failed_checks > 0:
        logger.error("%d quality check(s) FAILED — see report for details", report.failed_checks)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
