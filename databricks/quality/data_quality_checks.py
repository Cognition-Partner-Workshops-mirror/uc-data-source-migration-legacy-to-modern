"""
Data Quality Framework for the legacy CDW to Delta Lake migration.

Runs post-ingestion validation checks across all migrated tables:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between loan_accounts <-> borrowers / loan_products,
     and payments <-> loan_accounts
  4. Business rule validation (balance > 0 for active loans, closed date rules, etc.)

Usage (Databricks notebook or spark-submit):
    spark-submit data_quality_checks.py \
        --source-base /mnt/landing \
        --source-format csv

The module produces a list of CheckResult objects that can be fed into
``generate_report.py`` to create a DATA_QUALITY_REPORT.md.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    category: str          # reconciliation | null_check | referential | business_rule
    table: str
    check_name: str
    passed: bool
    detail: str
    expected: Optional[str] = None
    actual: Optional[str] = None


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------

def check_row_counts(spark, source_base, source_format="csv") -> List[CheckResult]:
    """Compare row counts between source files and target Delta tables."""

    tables = [
        ("cdw_borr_mstr", "loan_warehouse.borrowers"),
        ("cdw_ln_prod", "loan_warehouse.loan_products"),
        ("cdw_ln_acct", "loan_warehouse.loan_accounts"),
        ("cdw_pmt_hist", "loan_warehouse.payments"),
    ]
    results = []
    for subfolder, target_table in tables:
        source_path = f"{source_base}/{subfolder}"
        try:
            if source_format == "parquet":
                src_df = spark.read.parquet(source_path)
            else:
                src_df = spark.read.option("header", "true").csv(source_path)
            src_count = src_df.count()
        except Exception as exc:
            results.append(CheckResult(
                category="reconciliation",
                table=target_table,
                check_name=f"row_count_{subfolder}",
                passed=False,
                detail=f"Could not read source: {exc}",
            ))
            continue

        try:
            tgt_count = spark.table(target_table).count()
        except Exception as exc:
            results.append(CheckResult(
                category="reconciliation",
                table=target_table,
                check_name=f"row_count_{subfolder}",
                passed=False,
                detail=f"Could not read target table: {exc}",
            ))
            continue

        passed = src_count == tgt_count
        results.append(CheckResult(
            category="reconciliation",
            table=target_table,
            check_name=f"row_count_{subfolder}",
            passed=passed,
            detail=f"Source={src_count}, Target={tgt_count}",
            expected=str(src_count),
            actual=str(tgt_count),
        ))

    return results


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": [
        "external_id", "first_name", "last_name", "status",
    ],
    "loan_warehouse.loan_products": [
        "code", "name", "type", "term_months", "rate_type",
    ],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "status",
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount", "type", "status",
    ],
}


def check_required_nulls(spark) -> List[CheckResult]:
    """Verify that required columns contain no NULL values."""

    results = []
    for table, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table)
        except Exception as exc:
            results.append(CheckResult(
                category="null_check",
                table=table,
                check_name="table_accessible",
                passed=False,
                detail=f"Could not read table: {exc}",
            ))
            continue

        for col_name in columns:
            if col_name not in df.columns:
                results.append(CheckResult(
                    category="null_check",
                    table=table,
                    check_name=f"not_null_{col_name}",
                    passed=False,
                    detail=f"Column '{col_name}' not found in table",
                ))
                continue

            null_count = df.filter(F.col(col_name).isNull()).count()
            passed = null_count == 0
            results.append(CheckResult(
                category="null_check",
                table=table,
                check_name=f"not_null_{col_name}",
                passed=passed,
                detail=f"NULL count = {null_count}",
                expected="0",
                actual=str(null_count),
            ))

    return results


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark) -> List[CheckResult]:
    """Verify FK relationships between tables."""

    results = []

    # loan_accounts.borrower_id -> borrowers.borrower_id
    try:
        loans = spark.table("loan_warehouse.loan_accounts")
        borrowers = spark.table("loan_warehouse.borrowers")

        orphan_borrowers = loans.join(
            borrowers,
            loans["borrower_id"] == borrowers["borrower_id"],
            "left_anti",
        ).count()

        results.append(CheckResult(
            category="referential",
            table="loan_warehouse.loan_accounts",
            check_name="fk_borrower_id",
            passed=orphan_borrowers == 0,
            detail=f"Orphan loan_accounts with no matching borrower: {orphan_borrowers}",
            expected="0",
            actual=str(orphan_borrowers),
        ))
    except Exception as exc:
        results.append(CheckResult(
            category="referential",
            table="loan_warehouse.loan_accounts",
            check_name="fk_borrower_id",
            passed=False,
            detail=f"Error: {exc}",
        ))

    # loan_accounts.product_id -> loan_products.product_id
    try:
        products = spark.table("loan_warehouse.loan_products")

        orphan_products = loans.join(
            products,
            loans["product_id"] == products["product_id"],
            "left_anti",
        ).count()

        results.append(CheckResult(
            category="referential",
            table="loan_warehouse.loan_accounts",
            check_name="fk_product_id",
            passed=orphan_products == 0,
            detail=f"Orphan loan_accounts with no matching product: {orphan_products}",
            expected="0",
            actual=str(orphan_products),
        ))
    except Exception as exc:
        results.append(CheckResult(
            category="referential",
            table="loan_warehouse.loan_accounts",
            check_name="fk_product_id",
            passed=False,
            detail=f"Error: {exc}",
        ))

    # payments.loan_account_id -> loan_accounts.loan_account_id
    try:
        payments = spark.table("loan_warehouse.payments")

        orphan_payments = payments.join(
            loans,
            payments["loan_account_id"] == loans["loan_account_id"],
            "left_anti",
        ).count()

        results.append(CheckResult(
            category="referential",
            table="loan_warehouse.payments",
            check_name="fk_loan_account_id",
            passed=orphan_payments == 0,
            detail=f"Orphan payments with no matching loan account: {orphan_payments}",
            expected="0",
            actual=str(orphan_payments),
        ))
    except Exception as exc:
        results.append(CheckResult(
            category="referential",
            table="loan_warehouse.payments",
            check_name="fk_loan_account_id",
            passed=False,
            detail=f"Error: {exc}",
        ))

    return results


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------

def check_business_rules(spark) -> List[CheckResult]:
    """Validate domain-specific business rules."""

    results = []

    try:
        loans = spark.table("loan_warehouse.loan_accounts")
    except Exception as exc:
        results.append(CheckResult(
            category="business_rule",
            table="loan_warehouse.loan_accounts",
            check_name="table_accessible",
            passed=False,
            detail=f"Could not read table: {exc}",
        ))
        return results

    # Rule 1: Active loans must have current_balance > 0
    active_zero_bal = loans.filter(
        (F.col("status") == "Active") & (F.col("current_balance") <= 0)
    ).count()
    results.append(CheckResult(
        category="business_rule",
        table="loan_warehouse.loan_accounts",
        check_name="active_loan_positive_balance",
        passed=active_zero_bal == 0,
        detail=f"Active loans with balance <= 0: {active_zero_bal}",
        expected="0",
        actual=str(active_zero_bal),
    ))

    # Rule 2: Closed loans should have a maturity_date on or before today
    # (relaxed: just check that maturity_date is not null for closed loans)
    closed_no_maturity = loans.filter(
        (F.col("status") == "Closed") & F.col("maturity_date").isNull()
    ).count()
    results.append(CheckResult(
        category="business_rule",
        table="loan_warehouse.loan_accounts",
        check_name="closed_loan_has_maturity_date",
        passed=closed_no_maturity == 0,
        detail=f"Closed loans missing maturity_date: {closed_no_maturity}",
        expected="0",
        actual=str(closed_no_maturity),
    ))

    # Rule 3: interest_rate must be between 0 and 100
    bad_rates = loans.filter(
        (F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)
    ).count()
    results.append(CheckResult(
        category="business_rule",
        table="loan_warehouse.loan_accounts",
        check_name="interest_rate_range",
        passed=bad_rates == 0,
        detail=f"Loans with interest_rate outside 0-100: {bad_rates}",
        expected="0",
        actual=str(bad_rates),
    ))

    # Rule 4: origination_date must be before maturity_date
    bad_dates = loans.filter(
        F.col("origination_date") >= F.col("maturity_date")
    ).count()
    results.append(CheckResult(
        category="business_rule",
        table="loan_warehouse.loan_accounts",
        check_name="origination_before_maturity",
        passed=bad_dates == 0,
        detail=f"Loans where origination_date >= maturity_date: {bad_dates}",
        expected="0",
        actual=str(bad_dates),
    ))

    # Rule 5: LTV percent should be between 0 and 200 (generous upper bound)
    bad_ltv = loans.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    results.append(CheckResult(
        category="business_rule",
        table="loan_warehouse.loan_accounts",
        check_name="ltv_percent_range",
        passed=bad_ltv == 0,
        detail=f"Loans with LTV outside 0-200: {bad_ltv}",
        expected="0",
        actual=str(bad_ltv),
    ))

    # Rule 6: Delinquency days for active non-default loans should be >= 0
    bad_dlq = loans.filter(
        (F.col("delinquency_days").isNotNull())
        & (F.col("delinquency_days") < 0)
    ).count()
    results.append(CheckResult(
        category="business_rule",
        table="loan_warehouse.loan_accounts",
        check_name="delinquency_days_non_negative",
        passed=bad_dlq == 0,
        detail=f"Loans with negative delinquency_days: {bad_dlq}",
        expected="0",
        actual=str(bad_dlq),
    ))

    # Rule 7: Payment amounts should be positive for posted payments
    try:
        payments = spark.table("loan_warehouse.payments")
        bad_pmt_amt = payments.filter(
            (F.col("status") == "Posted") & (F.col("total_amount") <= 0)
        ).count()
        results.append(CheckResult(
            category="business_rule",
            table="loan_warehouse.payments",
            check_name="posted_payment_positive_amount",
            passed=bad_pmt_amt == 0,
            detail=f"Posted payments with total_amount <= 0: {bad_pmt_amt}",
            expected="0",
            actual=str(bad_pmt_amt),
        ))
    except Exception as exc:
        results.append(CheckResult(
            category="business_rule",
            table="loan_warehouse.payments",
            check_name="posted_payment_positive_amount",
            passed=False,
            detail=f"Error: {exc}",
        ))

    # Rule 8: Payment component sum should approximate total_amount
    try:
        payments = spark.table("loan_warehouse.payments")
        tolerance = 0.02  # 2 cents tolerance for rounding
        component_check = payments.withColumn(
            "_component_sum",
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0)),
        ).filter(
            F.abs(F.col("_component_sum") - F.col("total_amount")) > tolerance
        )
        mismatch_count = component_check.count()
        results.append(CheckResult(
            category="business_rule",
            table="loan_warehouse.payments",
            check_name="payment_component_sum_matches_total",
            passed=mismatch_count == 0,
            detail=f"Payments where components != total (tolerance={tolerance}): {mismatch_count}",
            expected="0",
            actual=str(mismatch_count),
        ))
    except Exception as exc:
        results.append(CheckResult(
            category="business_rule",
            table="loan_warehouse.payments",
            check_name="payment_component_sum_matches_total",
            passed=False,
            detail=f"Error: {exc}",
        ))

    return results


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------

def run_all_checks(spark, source_base, source_format="csv") -> List[CheckResult]:
    """Execute all data quality checks and return combined results."""

    all_results = []

    print("=" * 70)
    print("  DATA QUALITY CHECKS")
    print("=" * 70)

    print("\n--- Row Count Reconciliation ---")
    all_results.extend(check_row_counts(spark, source_base, source_format))

    print("\n--- Null Checks on Required Fields ---")
    all_results.extend(check_required_nulls(spark))

    print("\n--- Referential Integrity ---")
    all_results.extend(check_referential_integrity(spark))

    print("\n--- Business Rule Validation ---")
    all_results.extend(check_business_rules(spark))

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    failed = total - passed

    print("\n" + "=" * 70)
    print(f"  QUALITY CHECK SUMMARY: {passed}/{total} passed, {failed} failed")
    print("=" * 70)

    for r in all_results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.table}.{r.check_name}: {r.detail}")

    return all_results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run data quality checks")
    parser.add_argument("--source-base", default="/mnt/landing")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--output-json", default="/tmp/dq_results.json")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("DataQualityChecks").getOrCreate()
    results = run_all_checks(spark, args.source_base, args.source_format)

    # Write JSON for report generation
    with open(args.output_json, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    print(f"\nResults written to {args.output_json}")

    failed = [r for r in results if not r.passed]
    if failed:
        print(f"\n{len(failed)} check(s) FAILED.")
        sys.exit(1)
    else:
        print("\nAll checks PASSED.")
