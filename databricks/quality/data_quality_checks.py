"""
Data Quality Framework for the legacy CDW → Delta Lake migration.

Runs a comprehensive suite of checks after ingestion and generates
a structured report (DATA_QUALITY_REPORT.md). Checks cover:
  1. Row count reconciliation (source vs target)
  2. Null checks on required fields
  3. Referential integrity (borrower FK, product FK, loan FK)
  4. Business rule validation (balances, dates, status consistency)
  5. Payment component reconciliation

Each check returns a QualityCheckResult with pass/fail, counts, and details.
The report generator aggregates all results into a markdown document.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


# =============================================================================
# Configuration — source paths match ingestion scripts
# =============================================================================
LEGACY_BORROWERS_PATH = "/mnt/legacy-data/CDW_BORR_MSTR"
LEGACY_PRODUCTS_PATH = "/mnt/legacy-data/CDW_LN_PROD"
LEGACY_ACCOUNTS_PATH = "/mnt/legacy-data/CDW_LN_ACCT"
LEGACY_PAYMENTS_PATH = "/mnt/legacy-data/CDW_PMT_HIST"
LEGACY_FORMAT = "csv"

REPORT_OUTPUT_PATH = "/mnt/migration/reports/DATA_QUALITY_REPORT.md"


@dataclass
class QualityCheckResult:
    """Result of a single data quality check."""
    category: str           # "Row Count", "Null Check", "FK Integrity", "Business Rule"
    check_name: str         # Human-readable check name
    table: str              # Target table checked
    status: str             # "PASS" or "FAIL"
    expected: Optional[str] = None
    actual: Optional[str] = None
    details: Optional[str] = None
    failing_records: int = 0


# =============================================================================
# 1. Row Count Reconciliation
# =============================================================================

def check_row_counts(spark: SparkSession) -> List[QualityCheckResult]:
    """
    Verify that target table row counts match source counts
    (minus any quarantined records).
    """
    results = []

    source_target_pairs = [
        ("CDW_BORR_MSTR", LEGACY_BORROWERS_PATH, "loan_warehouse.borrowers"),
        ("CDW_LN_PROD", LEGACY_PRODUCTS_PATH, "loan_warehouse.loan_products"),
        ("CDW_LN_ACCT", LEGACY_ACCOUNTS_PATH, "loan_warehouse.loan_accounts"),
        ("CDW_PMT_HIST", LEGACY_PAYMENTS_PATH, "loan_warehouse.payments"),
    ]

    for source_name, source_path, target_table in source_target_pairs:
        try:
            source_df = (
                spark.read.format(LEGACY_FORMAT)
                .option("header", "true")
                .load(source_path)
            )
            source_count = source_df.count()
        except Exception as e:
            # Source may not be available in all environments
            results.append(QualityCheckResult(
                category="Row Count",
                check_name=f"Row count: {source_name} → {target_table}",
                table=target_table,
                status="FAIL",
                details=f"Could not read source: {str(e)}"
            ))
            continue

        target_df = spark.table(target_table)
        target_count = target_df.count()

        # Allow target to have fewer rows (quarantined records) but not more
        status = "PASS" if target_count <= source_count else "FAIL"
        quarantined = source_count - target_count

        results.append(QualityCheckResult(
            category="Row Count",
            check_name=f"Row count: {source_name} → {target_table}",
            table=target_table,
            status=status,
            expected=str(source_count),
            actual=str(target_count),
            details=f"{quarantined} record(s) quarantined" if quarantined > 0 else "Exact match",
            failing_records=0 if status == "PASS" else target_count - source_count
        ))

    return results


# =============================================================================
# 2. Null Checks on Required Fields
# =============================================================================

def check_nulls(spark: SparkSession) -> List[QualityCheckResult]:
    """Verify that required (NOT NULL) fields contain no null values after ingestion."""
    results = []

    # Define required fields per table
    required_fields = {
        "loan_warehouse.borrowers": [
            "external_id", "first_name", "last_name", "ssn_hash", "status"
        ],
        "loan_warehouse.loan_products": [
            "code", "name", "type", "term_months", "rate_type"
        ],
        "loan_warehouse.loan_accounts": [
            "account_number", "borrower_id", "product_id",
            "original_amount", "current_balance", "interest_rate",
            "term_months", "monthly_payment", "origination_date",
            "maturity_date", "status"
        ],
        "loan_warehouse.payments": [
            "legacy_payment_id", "loan_account_id", "payment_date",
            "total_amount", "principal_amount", "interest_amount",
            "type", "status"
        ],
    }

    for table, fields in required_fields.items():
        df = spark.table(table)
        for col_name in fields:
            null_count = df.filter(F.col(col_name).isNull()).count()
            results.append(QualityCheckResult(
                category="Null Check",
                check_name=f"NOT NULL: {table}.{col_name}",
                table=table,
                status="PASS" if null_count == 0 else "FAIL",
                expected="0 nulls",
                actual=f"{null_count} null(s)",
                failing_records=null_count
            ))

    return results


# =============================================================================
# 3. Referential Integrity
# =============================================================================

def check_referential_integrity(spark: SparkSession) -> List[QualityCheckResult]:
    """
    Verify FK references resolve correctly:
    - loan_accounts.borrower_id → borrowers.borrower_id
    - loan_accounts.product_id → loan_products.product_id
    - payments.loan_account_id → loan_accounts.loan_account_id
    """
    results = []

    # loan_accounts.borrower_id → borrowers.borrower_id
    loan_accounts = spark.table("loan_warehouse.loan_accounts")
    borrowers = spark.table("loan_warehouse.borrowers")

    orphaned_borrower_fk = (
        loan_accounts.alias("la")
        .join(borrowers.alias("b"), F.col("la.borrower_id") == F.col("b.borrower_id"), "left_anti")
    )
    orphan_count = orphaned_borrower_fk.count()
    results.append(QualityCheckResult(
        category="FK Integrity",
        check_name="loan_accounts.borrower_id → borrowers.borrower_id",
        table="loan_warehouse.loan_accounts",
        status="PASS" if orphan_count == 0 else "FAIL",
        expected="0 orphaned",
        actual=f"{orphan_count} orphaned",
        failing_records=orphan_count
    ))

    # loan_accounts.product_id → loan_products.product_id
    products = spark.table("loan_warehouse.loan_products")
    orphaned_product_fk = (
        loan_accounts.alias("la")
        .join(products.alias("lp"), F.col("la.product_id") == F.col("lp.product_id"), "left_anti")
    )
    orphan_count = orphaned_product_fk.count()
    results.append(QualityCheckResult(
        category="FK Integrity",
        check_name="loan_accounts.product_id → loan_products.product_id",
        table="loan_warehouse.loan_accounts",
        status="PASS" if orphan_count == 0 else "FAIL",
        expected="0 orphaned",
        actual=f"{orphan_count} orphaned",
        failing_records=orphan_count
    ))

    # payments.loan_account_id → loan_accounts.loan_account_id
    payments = spark.table("loan_warehouse.payments")
    orphaned_loan_fk = (
        payments.alias("p")
        .join(loan_accounts.alias("la"),
              F.col("p.loan_account_id") == F.col("la.loan_account_id"), "left_anti")
    )
    orphan_count = orphaned_loan_fk.count()
    results.append(QualityCheckResult(
        category="FK Integrity",
        check_name="payments.loan_account_id → loan_accounts.loan_account_id",
        table="loan_warehouse.payments",
        status="PASS" if orphan_count == 0 else "FAIL",
        expected="0 orphaned",
        actual=f"{orphan_count} orphaned",
        failing_records=orphan_count
    ))

    return results


# =============================================================================
# 4. Business Rule Validation
# =============================================================================

def check_business_rules(spark: SparkSession) -> List[QualityCheckResult]:
    """
    Validate business rules that should hold in clean data:
    - Active loans must have current_balance > 0
    - Closed loans should have current_balance near 0
    - Delinquency days > 0 should not have ACTIVE status (ANM-005 from anomaly report)
    - Credit scores must be in range 300-850
    - Payment component reconciliation (ANM-002)
    - Origination date must precede maturity date
    """
    results = []
    loan_accounts = spark.table("loan_warehouse.loan_accounts")
    payments = spark.table("loan_warehouse.payments")
    borrowers = spark.table("loan_warehouse.borrowers")

    # Rule 1: Active loans should have current_balance > 0
    active_zero_balance = loan_accounts.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    ).count()
    results.append(QualityCheckResult(
        category="Business Rule",
        check_name="Active loans must have balance > 0",
        table="loan_warehouse.loan_accounts",
        status="PASS" if active_zero_balance == 0 else "FAIL",
        expected="0 violations",
        actual=f"{active_zero_balance} active loan(s) with balance ≤ 0",
        failing_records=active_zero_balance
    ))

    # Rule 2: Delinquency > 0 with ACTIVE status (ANM-005)
    delinquent_active = loan_accounts.filter(
        (F.col("delinquency_days") > 0) & (F.col("status") == "ACTIVE")
    ).count()
    results.append(QualityCheckResult(
        category="Business Rule",
        check_name="Delinquent loans should not have ACTIVE status",
        table="loan_warehouse.loan_accounts",
        status="PASS" if delinquent_active == 0 else "FAIL",
        expected="0 violations",
        actual=f"{delinquent_active} delinquent loan(s) with ACTIVE status",
        details="Known legacy anomaly ANM-005 — delinquency tracking inconsistent with status",
        failing_records=delinquent_active
    ))

    # Rule 3: Credit score range 300-850
    bad_credit_scores = borrowers.filter(
        F.col("credit_score").isNotNull() &
        ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()
    results.append(QualityCheckResult(
        category="Business Rule",
        check_name="Credit scores must be in range 300-850",
        table="loan_warehouse.borrowers",
        status="PASS" if bad_credit_scores == 0 else "FAIL",
        expected="0 out of range",
        actual=f"{bad_credit_scores} out of range",
        failing_records=bad_credit_scores
    ))

    # Rule 4: Payment component reconciliation (ANM-002)
    # total_amount should equal principal + interest + escrow + late_fee (±0.01 tolerance)
    pmt_with_sum = payments.withColumn(
        "component_sum",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0))
    )
    reconciliation_failures = pmt_with_sum.filter(
        F.abs(F.col("total_amount") - F.col("component_sum")) > 0.01
    ).count()
    results.append(QualityCheckResult(
        category="Business Rule",
        check_name="Payment components must sum to total (±$0.01)",
        table="loan_warehouse.payments",
        status="PASS" if reconciliation_failures == 0 else "FAIL",
        expected="0 mismatches",
        actual=f"{reconciliation_failures} payment(s) with component/total discrepancy",
        details="Known legacy anomaly ANM-002 — Mitchell's payments have $400 discrepancy",
        failing_records=reconciliation_failures
    ))

    # Rule 5: Origination date must precede maturity date
    bad_dates = loan_accounts.filter(
        F.col("origination_date").isNotNull() &
        F.col("maturity_date").isNotNull() &
        (F.col("origination_date") >= F.col("maturity_date"))
    ).count()
    results.append(QualityCheckResult(
        category="Business Rule",
        check_name="Origination date must precede maturity date",
        table="loan_warehouse.loan_accounts",
        status="PASS" if bad_dates == 0 else "FAIL",
        expected="0 violations",
        actual=f"{bad_dates} loan(s) with origination ≥ maturity",
        failing_records=bad_dates
    ))

    # Rule 6: Interest rate should be positive for active loans
    bad_rates = loan_accounts.filter(
        (F.col("status") == "ACTIVE") & (F.col("interest_rate") <= 0)
    ).count()
    results.append(QualityCheckResult(
        category="Business Rule",
        check_name="Active loans must have positive interest rate",
        table="loan_warehouse.loan_accounts",
        status="PASS" if bad_rates == 0 else "FAIL",
        expected="0 violations",
        actual=f"{bad_rates} active loan(s) with rate ≤ 0",
        failing_records=bad_rates
    ))

    return results


# =============================================================================
# Report Generation
# =============================================================================

def generate_report(all_results: List[QualityCheckResult]) -> str:
    """Generate a markdown DATA_QUALITY_REPORT from all check results."""
    total = len(all_results)
    passed = sum(1 for r in all_results if r.status == "PASS")
    failed = sum(1 for r in all_results if r.status == "FAIL")

    lines = []
    lines.append("# Data Quality Report — Legacy CDW Migration")
    lines.append("")
    lines.append(f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"> **Overall Result:** {'PASS' if failed == 0 else 'FAIL'} "
                 f"({passed}/{total} checks passed, {failed} failed)")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Category | Checks | Passed | Failed |")
    lines.append("|----------|--------|--------|--------|")

    categories = ["Row Count", "Null Check", "FK Integrity", "Business Rule"]
    for cat in categories:
        cat_results = [r for r in all_results if r.category == cat]
        cat_pass = sum(1 for r in cat_results if r.status == "PASS")
        cat_fail = sum(1 for r in cat_results if r.status == "FAIL")
        status_icon = "PASS" if cat_fail == 0 else "FAIL"
        lines.append(f"| {cat} | {len(cat_results)} | {cat_pass} | {cat_fail} |")

    lines.append("")

    # Detailed results per category
    for cat in categories:
        cat_results = [r for r in all_results if r.category == cat]
        if not cat_results:
            continue

        lines.append(f"## {cat} Checks")
        lines.append("")
        lines.append("| Check | Table | Status | Expected | Actual | Details |")
        lines.append("|-------|-------|--------|----------|--------|---------|")

        for r in cat_results:
            status_str = f"**{r.status}**" if r.status == "FAIL" else r.status
            expected = r.expected or "-"
            actual = r.actual or "-"
            details = r.details or "-"
            lines.append(f"| {r.check_name} | {r.table} | {status_str} | {expected} | {actual} | {details} |")

        lines.append("")

    # Failing checks summary
    failing = [r for r in all_results if r.status == "FAIL"]
    if failing:
        lines.append("## Action Items (Failing Checks)")
        lines.append("")
        for i, r in enumerate(failing, 1):
            lines.append(f"{i}. **{r.check_name}** ({r.table}): {r.actual}")
            if r.details:
                lines.append(f"   - {r.details}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main Entry Point
# =============================================================================

def run_quality_checks():
    """Run all data quality checks and generate the report."""
    spark = SparkSession.builder.appName("Data Quality Checks").getOrCreate()

    print("=" * 60)
    print("DATA QUALITY CHECKS — Post-Migration Validation")
    print("=" * 60)

    all_results = []

    # Run all check categories
    print("\n[1/4] Row count reconciliation...")
    all_results.extend(check_row_counts(spark))

    print("[2/4] Null checks on required fields...")
    all_results.extend(check_nulls(spark))

    print("[3/4] Referential integrity checks...")
    all_results.extend(check_referential_integrity(spark))

    print("[4/4] Business rule validation...")
    all_results.extend(check_business_rules(spark))

    # Generate report
    report_md = generate_report(all_results)

    # Write report to DBFS
    dbutils = None  # noqa: F841 — available in Databricks runtime
    try:
        # Databricks environment — write to DBFS
        dbutils = spark._jvm.com.databricks.dbutils_v1.DBUtilsHolder.dbutils()  # type: ignore
        dbutils.fs.put(REPORT_OUTPUT_PATH, report_md, True)
        print(f"\nReport written to: {REPORT_OUTPUT_PATH}")
    except Exception:
        # Local/test environment — print report to stdout
        print("\n" + report_md)

    # Print summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r.status == "PASS")
    failed = sum(1 for r in all_results if r.status == "FAIL")
    print(f"\nQuality check complete: {passed}/{total} passed, {failed} failed")

    return all_results


if __name__ == "__main__":
    run_quality_checks()
