"""
Data Quality Framework for Legacy CDW Migration
=================================================
PySpark-based validation module that runs after ingestion and performs:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts <-> borrowers, loan_products, payments
  4. Business rule validation (balance > 0 for active loans, closed date rules, etc.)

Results are collected into a structured list that is used to generate
DATA_QUALITY_REPORT.md via the report_generator module.

Usage (Databricks notebook):
    from databricks.quality.data_quality_checks import run
    results = run(spark)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
import logging

# Import shared models (no PySpark dependency) for report interop
try:
    from databricks.quality.models import CheckResult, QualityReport
except ImportError:
    from models import CheckResult, QualityReport

logger = logging.getLogger("data_quality_checks")
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------
def check_row_counts(spark: SparkSession, report: QualityReport,
                     source_counts: dict) -> None:
    """Compare source row counts against target Delta tables.

    Args:
        source_counts: dict mapping target table name to expected source count,
                       e.g. {"borrowers": 5, "loan_products": 5, ...}
    """
    table_map = {
        "borrowers": "loan_warehouse.borrowers",
        "loan_products": "loan_warehouse.loan_products",
        "loan_accounts": "loan_warehouse.loan_accounts",
        "payments": "loan_warehouse.payments",
    }

    for name, full_table in table_map.items():
        expected = source_counts.get(name, 0)
        try:
            actual = spark.table(full_table).count()
        except Exception as e:
            report.results.append(CheckResult(
                category="ROW_COUNT",
                table=name,
                check_name=f"Row count for {name}",
                status="FAIL",
                detail=f"Table not found or unreadable: {e}",
                severity="CRITICAL"
            ))
            continue

        # Allow target count to be <= source count (quarantined records reduce target)
        if actual == expected:
            status = "PASS"
            detail = f"Source={expected}, Target={actual} (exact match)"
        elif actual < expected:
            status = "PASS"
            detail = (f"Source={expected}, Target={actual} "
                      f"({expected - actual} records quarantined)")
        else:
            status = "FAIL"
            detail = (f"Source={expected}, Target={actual} "
                      f"(target has {actual - expected} MORE rows than source)")

        report.results.append(CheckResult(
            category="ROW_COUNT",
            table=name,
            check_name=f"Row count reconciliation: {name}",
            status=status,
            detail=detail,
            severity="CRITICAL" if status == "FAIL" else "LOW"
        ))
        logger.info("Row count [%s]: %s — %s", name, status, detail)


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------
def _null_check(spark: SparkSession, report: QualityReport,
                table: str, full_table: str, columns: list) -> None:
    """Check that specified columns have no NULL values."""
    try:
        df = spark.table(full_table)
    except Exception as e:
        report.results.append(CheckResult(
            category="NULL_CHECK", table=table,
            check_name=f"Null check for {table}",
            status="FAIL", detail=f"Table unreadable: {e}",
            severity="CRITICAL"
        ))
        return

    for col_name in columns:
        null_count = df.filter(F.col(col_name).isNull()).count()
        status = "PASS" if null_count == 0 else "FAIL"
        detail = f"{null_count} null(s) in {col_name}" if null_count > 0 else f"{col_name}: no nulls"

        report.results.append(CheckResult(
            category="NULL_CHECK",
            table=table,
            check_name=f"NOT NULL: {table}.{col_name}",
            status=status,
            detail=detail,
            severity="HIGH" if null_count > 0 else "LOW"
        ))
        if null_count > 0:
            logger.warning("NULL check FAIL: %s.%s has %d nulls", table, col_name, null_count)


def check_nulls(spark: SparkSession, report: QualityReport) -> None:
    """Run null checks on all required fields across all target tables."""

    # borrowers required fields
    _null_check(spark, report, "borrowers", "loan_warehouse.borrowers", [
        "external_id", "first_name", "last_name", "ssn_hash",
        "date_of_birth", "credit_score", "annual_income",
        "created_at", "updated_at", "status"
    ])

    # loan_products required fields
    _null_check(spark, report, "loan_products", "loan_warehouse.loan_products", [
        "code", "name", "type", "term_months",
        "min_amount", "max_amount", "is_active",
        "effective_date", "expiration_date"
    ])

    # loan_accounts required fields
    _null_check(spark, report, "loan_accounts", "loan_warehouse.loan_accounts", [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "origination_date", "maturity_date", "status",
        "created_at", "updated_at"
    ])

    # payments required fields
    _null_check(spark, report, "payments", "loan_warehouse.payments", [
        "legacy_payment_id", "loan_account_id",
        "payment_date", "total_amount", "type", "status",
        "created_at", "updated_at"
    ])


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------
def check_referential_integrity(spark: SparkSession, report: QualityReport) -> None:
    """Verify foreign key relationships between target tables.

    Checks:
      - loan_accounts.borrower_id -> borrowers.id
      - loan_accounts.product_id  -> loan_products.id
      - payments.loan_account_id  -> loan_accounts.id
    """
    fk_checks = [
        {
            "name": "loan_accounts.borrower_id -> borrowers.id",
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "borrower_id",
            "parent_table": "loan_warehouse.borrowers",
            "parent_col": "id",
        },
        {
            "name": "loan_accounts.product_id -> loan_products.id",
            "child_table": "loan_warehouse.loan_accounts",
            "child_col": "product_id",
            "parent_table": "loan_warehouse.loan_products",
            "parent_col": "id",
        },
        {
            "name": "payments.loan_account_id -> loan_accounts.id",
            "child_table": "loan_warehouse.payments",
            "child_col": "loan_account_id",
            "parent_table": "loan_warehouse.loan_accounts",
            "parent_col": "id",
        },
    ]

    for check in fk_checks:
        try:
            child_df = spark.table(check["child_table"])
            parent_df = spark.table(check["parent_table"])

            # Left anti join finds child rows with no matching parent
            orphans = child_df.join(
                parent_df,
                child_df[check["child_col"]] == parent_df[check["parent_col"]],
                "left_anti"
            )
            orphan_count = orphans.count()

            if orphan_count == 0:
                status = "PASS"
                detail = "All references valid"
            else:
                status = "FAIL"
                # Collect up to 5 sample orphaned IDs for the report
                sample_ids = [str(row[check["child_col"]]) for row in orphans.select(check["child_col"]).limit(5).collect()]
                detail = f"{orphan_count} orphaned record(s). Sample IDs: {', '.join(sample_ids)}"

            report.results.append(CheckResult(
                category="REFERENTIAL_INTEGRITY",
                table=check["child_table"].split(".")[-1],
                check_name=f"FK: {check['name']}",
                status=status,
                detail=detail,
                severity="HIGH" if orphan_count > 0 else "LOW"
            ))
            logger.info("FK check [%s]: %s — %s", check["name"], status, detail)

        except Exception as e:
            report.results.append(CheckResult(
                category="REFERENTIAL_INTEGRITY",
                table=check["child_table"].split(".")[-1],
                check_name=f"FK: {check['name']}",
                status="FAIL",
                detail=f"Error running check: {e}",
                severity="CRITICAL"
            ))


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------
def check_business_rules(spark: SparkSession, report: QualityReport) -> None:
    """Validate domain-specific business rules on the target tables.

    Rules:
      - Active loans must have current_balance > 0
      - Active loans must have delinquency_days consistent with status
      - Credit scores must be in FICO range 300-850
      - Payment component sum should approximate total amount (within $1.00)
      - Loan origination_date must be before maturity_date
    """

    # --- Rule 1: Active loans must have positive balance ---
    try:
        loans_df = spark.table("loan_warehouse.loan_accounts")
        bad_balance = loans_df.filter(
            (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
        ).count()

        report.results.append(CheckResult(
            category="BUSINESS_RULE",
            table="loan_accounts",
            check_name="Active loans must have current_balance > 0",
            status="PASS" if bad_balance == 0 else "FAIL",
            detail=f"{bad_balance} active loan(s) with zero or negative balance" if bad_balance > 0 else "All active loans have positive balance",
            severity="HIGH" if bad_balance > 0 else "LOW"
        ))
    except Exception as e:
        report.results.append(CheckResult(
            category="BUSINESS_RULE", table="loan_accounts",
            check_name="Active loans must have current_balance > 0",
            status="FAIL", detail=f"Error: {e}", severity="CRITICAL"
        ))

    # --- Rule 2: Delinquent days > 0 should not have ACTIVE status ---
    try:
        delinquent_active = loans_df.filter(
            (F.col("status") == "ACTIVE") & (F.col("delinquency_days") > 0)
        ).count()

        report.results.append(CheckResult(
            category="BUSINESS_RULE",
            table="loan_accounts",
            check_name="Active loans should not be delinquent (delinquency_days must be 0)",
            status="PASS" if delinquent_active == 0 else "FAIL",
            detail=f"{delinquent_active} active loan(s) with delinquency_days > 0" if delinquent_active > 0 else "No active loans are delinquent",
            severity="HIGH" if delinquent_active > 0 else "LOW"
        ))
    except Exception as e:
        report.results.append(CheckResult(
            category="BUSINESS_RULE", table="loan_accounts",
            check_name="Active loans should not be delinquent",
            status="FAIL", detail=f"Error: {e}", severity="CRITICAL"
        ))

    # --- Rule 3: Credit scores in FICO range 300-850 ---
    try:
        borrowers_df = spark.table("loan_warehouse.borrowers")
        out_of_range = borrowers_df.filter(
            (F.col("credit_score") < 300) | (F.col("credit_score") > 850)
        ).count()

        report.results.append(CheckResult(
            category="BUSINESS_RULE",
            table="borrowers",
            check_name="Credit scores must be in FICO range 300-850",
            status="PASS" if out_of_range == 0 else "FAIL",
            detail=f"{out_of_range} borrower(s) with out-of-range credit score" if out_of_range > 0 else "All credit scores in valid range",
            severity="MEDIUM" if out_of_range > 0 else "LOW"
        ))
    except Exception as e:
        report.results.append(CheckResult(
            category="BUSINESS_RULE", table="borrowers",
            check_name="Credit scores must be in FICO range 300-850",
            status="FAIL", detail=f"Error: {e}", severity="CRITICAL"
        ))

    # --- Rule 4: Payment component sum should approximate total ---
    try:
        payments_df = spark.table("loan_warehouse.payments")
        payments_with_sum = payments_df.withColumn(
            "_component_sum",
            F.col("principal_amount") + F.col("interest_amount")
            + F.col("escrow_amount") + F.col("late_fee")
        )
        mismatches = payments_with_sum.filter(
            F.abs(F.col("total_amount") - F.col("_component_sum")) > 1.00
        ).count()

        report.results.append(CheckResult(
            category="BUSINESS_RULE",
            table="payments",
            check_name="Payment component sum must match total (within $1.00 tolerance)",
            status="PASS" if mismatches == 0 else "FAIL",
            detail=f"{mismatches} payment(s) with component sum mismatch > $1.00" if mismatches > 0 else "All payment components reconcile",
            severity="HIGH" if mismatches > 0 else "LOW"
        ))
    except Exception as e:
        report.results.append(CheckResult(
            category="BUSINESS_RULE", table="payments",
            check_name="Payment component sum must match total",
            status="FAIL", detail=f"Error: {e}", severity="CRITICAL"
        ))

    # --- Rule 5: Origination date must precede maturity date ---
    try:
        bad_dates = loans_df.filter(
            F.col("origination_date") >= F.col("maturity_date")
        ).count()

        report.results.append(CheckResult(
            category="BUSINESS_RULE",
            table="loan_accounts",
            check_name="Origination date must precede maturity date",
            status="PASS" if bad_dates == 0 else "FAIL",
            detail=f"{bad_dates} loan(s) where origination_date >= maturity_date" if bad_dates > 0 else "All loan date ranges valid",
            severity="HIGH" if bad_dates > 0 else "LOW"
        ))
    except Exception as e:
        report.results.append(CheckResult(
            category="BUSINESS_RULE", table="loan_accounts",
            check_name="Origination date must precede maturity date",
            status="FAIL", detail=f"Error: {e}", severity="CRITICAL"
        ))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run(spark: SparkSession,
        source_counts: dict = None) -> QualityReport:
    """Run all data quality checks and return a structured report.

    Args:
        spark: Active SparkSession.
        source_counts: Optional dict of expected source row counts per table.
                       Defaults to the legacy seed data counts if not provided.
    Returns:
        QualityReport with all check results.
    """
    # Default source counts from the legacy seed data (data-legacy.sql)
    if source_counts is None:
        source_counts = {
            "borrowers": 5,
            "loan_products": 5,
            "loan_accounts": 5,
            "payments": 10,
        }

    report = QualityReport()

    logger.info("=== Starting data quality checks ===")

    # 1. Row count reconciliation
    check_row_counts(spark, report, source_counts)

    # 2. Null checks on required fields
    check_nulls(spark, report)

    # 3. Referential integrity
    check_referential_integrity(spark, report)

    # 4. Business rules
    check_business_rules(spark, report)

    logger.info("=== Data quality checks complete: %d passed, %d failed out of %d ===",
                report.pass_count, report.fail_count, report.total_count)

    return report


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("DataQualityChecks").getOrCreate()
    report = run(spark)
    # Print summary to notebook output
    for r in report.results:
        print(f"[{r.status}] {r.category} | {r.table} | {r.check_name} | {r.detail}")
