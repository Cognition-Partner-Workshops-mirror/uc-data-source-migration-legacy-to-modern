"""
Data Quality Framework for Loan Migration Pipeline

Runs post-ingestion validation checks across all migrated tables:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts and borrowers/loan_products
  4. Referential integrity between payments and loan_accounts
  5. Business rule validation:
     - Active loans must have balance > 0
     - Closed loans must have a maturity_date
     - Payment amounts must equal sum of components
     - Credit scores within valid range
  6. Generates DATA_QUALITY_REPORT.md with pass/fail results

Usage:
  spark-submit data_quality_checks.py

Or import and call run_all_checks(spark) from a Databricks notebook.
"""

import os
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TARGET_SCHEMA = "loan_warehouse"
REPORT_OUTPUT_PATH = "/dbfs/migration-reports/DATA_QUALITY_REPORT.md"

# Source file paths (used for row count reconciliation)
SOURCE_PATHS = {
    "borrowers": "/mnt/legacy-extracts/CDW_BORR_MSTR/",
    "loan_products": "/mnt/legacy-extracts/CDW_LN_PROD/",
    "loan_accounts": "/mnt/legacy-extracts/CDW_LN_ACCT/",
    "payments": "/mnt/legacy-extracts/CDW_PMT_HIST/",
}


class CheckResult:
    """Container for a single data quality check result."""

    def __init__(self, category: str, check_name: str, passed: bool,
                 detail: str, severity: str = "ERROR"):
        self.category = category
        self.check_name = check_name
        self.passed = passed
        self.detail = detail
        self.severity = severity  # ERROR, WARNING, INFO
        self.timestamp = datetime.now().isoformat()

    def __repr__(self):
        status = "PASS" if self.passed else f"FAIL ({self.severity})"
        return f"[{status}] {self.category}/{self.check_name}: {self.detail}"


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def check_row_counts(spark: SparkSession) -> list:
    """
    1. Row Count Reconciliation
    Compare source extract row counts to target Delta table row counts.
    Quarantined rows are accounted for separately.
    """
    results = []

    for table_name, source_path in SOURCE_PATHS.items():
        target_table = f"{TARGET_SCHEMA}.{table_name}"
        quarantine_table = f"{TARGET_SCHEMA}._quarantine_{table_name}"

        # Target count
        try:
            target_count = spark.table(target_table).count()
        except Exception as e:
            results.append(CheckResult(
                "Row Count", f"{table_name}_target_exists",
                False, f"Target table {target_table} not found: {e}"
            ))
            continue

        # Source count
        try:
            source_count = (
                spark.read.format("csv")
                .option("header", "true")
                .load(source_path)
                .count()
            )
        except Exception:
            # If source files not accessible, compare against quarantine only
            source_count = None

        # Quarantine count
        try:
            quarantine_count = spark.table(quarantine_table).count()
        except Exception:
            quarantine_count = 0

        if source_count is not None:
            expected = source_count
            actual = target_count + quarantine_count
            passed = expected == actual
            results.append(CheckResult(
                "Row Count", f"{table_name}_reconciliation",
                passed,
                f"source={source_count}, target={target_count}, "
                f"quarantined={quarantine_count}, "
                f"expected_total={expected}, actual_total={actual}"
            ))
        else:
            results.append(CheckResult(
                "Row Count", f"{table_name}_target_populated",
                target_count > 0,
                f"target={target_count}, quarantined={quarantine_count} "
                f"(source files not accessible for reconciliation)",
                severity="WARNING"
            ))

    return results


def check_null_required_fields(spark: SparkSession) -> list:
    """
    2. Null Checks on Required Fields
    Verify that NOT NULL columns have no null values in the target tables.
    """
    results = []

    required_field_map = {
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

    for table_name, required_cols in required_field_map.items():
        target_table = f"{TARGET_SCHEMA}.{table_name}"
        try:
            df = spark.table(target_table)
        except Exception:
            results.append(CheckResult(
                "Null Check", f"{table_name}_table_exists",
                False, f"Table {target_table} not found"
            ))
            continue

        for col_name in required_cols:
            null_count = df.filter(F.col(col_name).isNull()).count()
            results.append(CheckResult(
                "Null Check", f"{table_name}.{col_name}",
                null_count == 0,
                f"{null_count} null values found in {table_name}.{col_name}"
            ))

    return results


def check_referential_integrity(spark: SparkSession) -> list:
    """
    3. Referential Integrity
    Verify that FK columns in child tables reference valid parent records.
    """
    results = []

    # loan_accounts.borrower_id -> borrowers.borrower_id
    try:
        loan_accts = spark.table(f"{TARGET_SCHEMA}.loan_accounts")
        borrowers = spark.table(f"{TARGET_SCHEMA}.borrowers")

        orphaned_borrower_refs = (
            loan_accts
            .join(borrowers, loan_accts["borrower_id"] == borrowers["borrower_id"], "left_anti")
            .count()
        )
        results.append(CheckResult(
            "Referential Integrity", "loan_accounts.borrower_id -> borrowers",
            orphaned_borrower_refs == 0,
            f"{orphaned_borrower_refs} loan accounts reference non-existent borrowers"
        ))
    except Exception as e:
        results.append(CheckResult(
            "Referential Integrity", "loan_accounts.borrower_id -> borrowers",
            False, f"Check failed: {e}"
        ))

    # loan_accounts.product_id -> loan_products.product_id
    try:
        loan_accts = spark.table(f"{TARGET_SCHEMA}.loan_accounts")
        products = spark.table(f"{TARGET_SCHEMA}.loan_products")

        orphaned_product_refs = (
            loan_accts
            .join(products, loan_accts["product_id"] == products["product_id"], "left_anti")
            .count()
        )
        results.append(CheckResult(
            "Referential Integrity", "loan_accounts.product_id -> loan_products",
            orphaned_product_refs == 0,
            f"{orphaned_product_refs} loan accounts reference non-existent products"
        ))
    except Exception as e:
        results.append(CheckResult(
            "Referential Integrity", "loan_accounts.product_id -> loan_products",
            False, f"Check failed: {e}"
        ))

    # payments.loan_account_id -> loan_accounts.loan_account_id
    try:
        payments = spark.table(f"{TARGET_SCHEMA}.payments")
        loan_accts = spark.table(f"{TARGET_SCHEMA}.loan_accounts")

        orphaned_payment_refs = (
            payments
            .join(loan_accts, payments["loan_account_id"] == loan_accts["loan_account_id"], "left_anti")
            .count()
        )
        results.append(CheckResult(
            "Referential Integrity", "payments.loan_account_id -> loan_accounts",
            orphaned_payment_refs == 0,
            f"{orphaned_payment_refs} payments reference non-existent loan accounts"
        ))
    except Exception as e:
        results.append(CheckResult(
            "Referential Integrity", "payments.loan_account_id -> loan_accounts",
            False, f"Check failed: {e}"
        ))

    return results


def check_business_rules(spark: SparkSession) -> list:
    """
    4. Business Rule Validation
    Verify domain-specific invariants hold after migration.
    """
    results = []

    # --- Loan Account Rules ---
    try:
        loans = spark.table(f"{TARGET_SCHEMA}.loan_accounts")

        # Rule: Active loans must have current_balance > 0
        active_zero_balance = (
            loans
            .filter(F.col("status") == "Active")
            .filter(F.col("current_balance") <= 0)
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "active_loans_positive_balance",
            active_zero_balance == 0,
            f"{active_zero_balance} active loans have balance <= 0"
        ))

        # Rule: Closed loans should have maturity_date populated
        closed_no_maturity = (
            loans
            .filter(F.col("status") == "Closed")
            .filter(F.col("maturity_date").isNull())
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "closed_loans_have_maturity_date",
            closed_no_maturity == 0,
            f"{closed_no_maturity} closed loans missing maturity_date"
        ))

        # Rule: original_amount must be > 0
        invalid_orig_amt = (
            loans
            .filter(F.col("original_amount") <= 0)
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "positive_original_amount",
            invalid_orig_amt == 0,
            f"{invalid_orig_amt} loans have original_amount <= 0"
        ))

        # Rule: interest_rate must be between 0 and 100
        invalid_rate = (
            loans
            .filter((F.col("interest_rate") < 0) | (F.col("interest_rate") > 100))
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "interest_rate_valid_range",
            invalid_rate == 0,
            f"{invalid_rate} loans have interest_rate outside [0, 100]"
        ))

        # Rule: LTV percent should be between 0 and 200 (if populated)
        invalid_ltv = (
            loans
            .filter(F.col("ltv_percent").isNotNull())
            .filter((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "ltv_percent_valid_range",
            invalid_ltv == 0,
            f"{invalid_ltv} loans have ltv_percent outside [0, 200]"
        ))

        # Rule: delinquency_days must be >= 0
        negative_dlq = (
            loans
            .filter(F.col("delinquency_days") < 0)
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "non_negative_delinquency_days",
            negative_dlq == 0,
            f"{negative_dlq} loans have negative delinquency_days"
        ))

        # Rule: origination_date should be before maturity_date
        bad_date_order = (
            loans
            .filter(F.col("origination_date") >= F.col("maturity_date"))
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "origination_before_maturity",
            bad_date_order == 0,
            f"{bad_date_order} loans have origination_date >= maturity_date"
        ))

        # Rule: status must be one of the known expanded values
        valid_statuses = ["Active", "Closed", "Default", "Forbearance"]
        unknown_status = (
            loans
            .filter(~F.col("status").isin(valid_statuses))
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "loan_status_valid_values",
            unknown_status == 0,
            f"{unknown_status} loans have unknown status values"
        ))

    except Exception as e:
        results.append(CheckResult(
            "Business Rule", "loan_accounts_checks",
            False, f"Loan account checks failed: {e}"
        ))

    # --- Borrower Rules ---
    try:
        borrowers = spark.table(f"{TARGET_SCHEMA}.borrowers")

        # Rule: credit_score should be between 300 and 850 (if populated)
        invalid_credit = (
            borrowers
            .filter(F.col("credit_score").isNotNull())
            .filter((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "credit_score_valid_range",
            invalid_credit == 0,
            f"{invalid_credit} borrowers have credit_score outside [300, 850]"
        ))

        # Rule: annual_income should be >= 0 (if populated)
        negative_income = (
            borrowers
            .filter(F.col("annual_income").isNotNull())
            .filter(F.col("annual_income") < 0)
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "non_negative_annual_income",
            negative_income == 0,
            f"{negative_income} borrowers have negative annual_income"
        ))

    except Exception as e:
        results.append(CheckResult(
            "Business Rule", "borrower_checks",
            False, f"Borrower checks failed: {e}"
        ))

    # --- Payment Rules ---
    try:
        payments = spark.table(f"{TARGET_SCHEMA}.payments")

        # Rule: total_amount must be > 0
        invalid_pmt_amt = (
            payments
            .filter(F.col("total_amount") <= 0)
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "positive_payment_amount",
            invalid_pmt_amt == 0,
            f"{invalid_pmt_amt} payments have total_amount <= 0"
        ))

        # Rule: payment type must be one of the known expanded values
        valid_types = ["Regular", "Extra", "Partial", "Prepayment"]
        unknown_type = (
            payments
            .filter(~F.col("type").isin(valid_types))
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "payment_type_valid_values",
            unknown_type == 0,
            f"{unknown_type} payments have unknown type values"
        ))

        # Rule: payment status must be one of the known expanded values
        valid_pmt_statuses = ["Posted", "Reversed", "NSF", "Pending"]
        unknown_pmt_status = (
            payments
            .filter(~F.col("status").isin(valid_pmt_statuses))
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "payment_status_valid_values",
            unknown_pmt_status == 0,
            f"{unknown_pmt_status} payments have unknown status values"
        ))

        # Rule: component amounts should sum close to total_amount (tolerance 0.01)
        component_mismatch = (
            payments
            .filter(
                F.col("principal_amount").isNotNull() &
                F.col("interest_amount").isNotNull()
            )
            .withColumn(
                "_component_sum",
                F.coalesce(F.col("principal_amount"), F.lit(0))
                + F.coalesce(F.col("interest_amount"), F.lit(0))
                + F.coalesce(F.col("escrow_amount"), F.lit(0))
                + F.coalesce(F.col("late_fee"), F.lit(0))
            )
            .filter(
                F.abs(F.col("_component_sum") - F.col("total_amount")) > 0.02
            )
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "payment_component_sum_matches_total",
            component_mismatch == 0,
            f"{component_mismatch} payments where component sum differs "
            f"from total_amount by > $0.02",
            severity="WARNING"
        ))

        # Rule: received_date should be on or before processed_date
        bad_recv_proc = (
            payments
            .filter(
                F.col("received_date").isNotNull() &
                F.col("processed_date").isNotNull()
            )
            .filter(F.col("received_date") > F.col("processed_date"))
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "received_before_processed_date",
            bad_recv_proc == 0,
            f"{bad_recv_proc} payments have received_date after processed_date",
            severity="WARNING"
        ))

    except Exception as e:
        results.append(CheckResult(
            "Business Rule", "payment_checks",
            False, f"Payment checks failed: {e}"
        ))

    # --- Loan Product Rules ---
    try:
        products = spark.table(f"{TARGET_SCHEMA}.loan_products")

        # Rule: min_amount should be <= max_amount (if both populated)
        invalid_range = (
            products
            .filter(
                F.col("min_amount").isNotNull() &
                F.col("max_amount").isNotNull()
            )
            .filter(F.col("min_amount") > F.col("max_amount"))
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "product_min_lte_max_amount",
            invalid_range == 0,
            f"{invalid_range} products have min_amount > max_amount"
        ))

        # Rule: term_months should be > 0
        invalid_term = (
            products
            .filter(F.col("term_months") <= 0)
            .count()
        )
        results.append(CheckResult(
            "Business Rule", "product_positive_term_months",
            invalid_term == 0,
            f"{invalid_term} products have term_months <= 0"
        ))

    except Exception as e:
        results.append(CheckResult(
            "Business Rule", "product_checks",
            False, f"Product checks failed: {e}"
        ))

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results: list, output_path: str = REPORT_OUTPUT_PATH) -> str:
    """Generate a Markdown quality report from check results."""

    now = datetime.now().isoformat()
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {now}",
        f"**Pipeline:** Legacy CDW to Modern Loan Warehouse (Databricks/Delta Lake)",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Checks | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Pass Rate | {(passed/total*100):.1f}% |" if total > 0 else "| Pass Rate | N/A |",
        "",
    ]

    # Group results by category
    categories = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    for category, checks in categories.items():
        cat_passed = sum(1 for c in checks if c.passed)
        cat_total = len(checks)
        lines.append(f"## {category} ({cat_passed}/{cat_total} passed)")
        lines.append("")
        lines.append("| Check | Status | Severity | Detail |")
        lines.append("|-------|--------|----------|--------|")

        for check in checks:
            status = "PASS" if check.passed else "FAIL"
            sev = check.severity if not check.passed else "-"
            lines.append(
                f"| {check.check_name} | {status} | {sev} | {check.detail} |"
            )

        lines.append("")

    # Failed checks summary at the end
    failed_checks = [r for r in results if not r.passed]
    if failed_checks:
        lines.append("## Action Items")
        lines.append("")
        for i, check in enumerate(failed_checks, 1):
            lines.append(
                f"{i}. **[{check.severity}]** `{check.category}/{check.check_name}`: "
                f"{check.detail}"
            )
        lines.append("")
    else:
        lines.append("## Action Items")
        lines.append("")
        lines.append("No action items. All checks passed.")
        lines.append("")

    lines.append("---")
    lines.append(f"*Report generated by `databricks/quality/data_quality_checks.py`*")

    report_content = "\n".join(lines)

    # Write the report
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report_content)
        print(f"[QUALITY] Report written to {output_path}")
    except Exception as e:
        print(f"[QUALITY] WARNING: Could not write report to {output_path}: {e}")
        print(f"[QUALITY] Report content follows:\n{report_content}")

    return report_content


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_all_checks(spark: SparkSession, output_path: str = REPORT_OUTPUT_PATH) -> str:
    """Run all data quality checks and generate the report."""

    print("=" * 70)
    print("[QUALITY] Starting data quality checks")
    print("=" * 70)

    all_results = []

    print("\n[QUALITY] Running row count reconciliation...")
    all_results.extend(check_row_counts(spark))

    print("[QUALITY] Running null checks on required fields...")
    all_results.extend(check_null_required_fields(spark))

    print("[QUALITY] Running referential integrity checks...")
    all_results.extend(check_referential_integrity(spark))

    print("[QUALITY] Running business rule validation...")
    all_results.extend(check_business_rules(spark))

    # Print summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    failed = total - passed
    print(f"\n[QUALITY] Checks complete: {passed}/{total} passed, {failed} failed")

    for r in all_results:
        if not r.passed:
            print(f"  FAIL: {r}")

    # Generate report
    report = generate_report(all_results, output_path)

    return report


if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_DataQuality").getOrCreate()
    try:
        run_all_checks(spark)
    finally:
        spark.stop()
