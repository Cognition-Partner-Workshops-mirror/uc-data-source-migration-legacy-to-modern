"""
Data Quality Framework — Post-Ingestion Validation

Runs after all four ingestion scripts complete. Checks:
  1. Row count reconciliation (source vs. target)
  2. Null checks on required fields
  3. Referential integrity between tables
  4. Business rule validation
  5. Generates DATA_QUALITY_REPORT.md

Usage:
    spark-submit data_quality_checks.py
    -- or run as a Databricks notebook
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, IntegerType
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_COUNTS = {
    "CDW_BORR_MSTR": "/mnt/legacy-cdw/CDW_BORR_MSTR",
    "CDW_LN_PROD": "/mnt/legacy-cdw/CDW_LN_PROD",
    "CDW_LN_ACCT": "/mnt/legacy-cdw/CDW_LN_ACCT",
    "CDW_PMT_HIST": "/mnt/legacy-cdw/CDW_PMT_HIST",
}

TARGET_TABLES = {
    "CDW_BORR_MSTR": "loan_warehouse.borrowers",
    "CDW_LN_PROD": "loan_warehouse.loan_products",
    "CDW_LN_ACCT": "loan_warehouse.loan_accounts",
    "CDW_PMT_HIST": "loan_warehouse.payments",
}

DQ_LOG_TABLE = "loan_warehouse.data_quality_log"
REPORT_PATH = "/mnt/reports/DATA_QUALITY_REPORT.md"


# ---------------------------------------------------------------------------
# Check Result Model
# ---------------------------------------------------------------------------
@dataclass
class CheckResult:
    category: str
    check_name: str
    table: str
    status: str  # PASS, FAIL, WARN
    details: str
    count: Optional[int] = None


# ---------------------------------------------------------------------------
# 1. Row Count Reconciliation
# ---------------------------------------------------------------------------
def check_row_counts(spark: SparkSession, source_format: str = "csv") -> list:
    """Compare source row counts to target row counts."""
    results = []
    for source_table, source_path in SOURCE_COUNTS.items():
        target_table = TARGET_TABLES[source_table]
        try:
            if source_format == "csv":
                source_count = (
                    spark.read.option("header", "true").csv(source_path).count()
                )
            else:
                source_count = spark.read.parquet(source_path).count()

            target_count = spark.table(target_table).count()

            if source_count == target_count:
                status = "PASS"
                details = f"Source={source_count}, Target={target_count}"
            elif target_count > source_count:
                status = "WARN"
                details = (
                    f"Target ({target_count}) > Source ({source_count}). "
                    f"Possible duplicates from prior runs."
                )
            else:
                status = "FAIL"
                details = (
                    f"Source={source_count}, Target={target_count}. "
                    f"Missing {source_count - target_count} rows."
                )

            results.append(CheckResult(
                category="Row Count Reconciliation",
                check_name=f"{source_table} → {target_table}",
                table=target_table,
                status=status,
                details=details,
                count=target_count,
            ))
        except Exception as e:
            results.append(CheckResult(
                category="Row Count Reconciliation",
                check_name=f"{source_table} → {target_table}",
                table=target_table,
                status="FAIL",
                details=f"Error reading source/target: {str(e)}",
            ))

    return results


# ---------------------------------------------------------------------------
# 2. Null Checks on Required Fields
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": [
        "external_id", "first_name", "last_name", "ssn_hash", "status",
        "created_at", "updated_at",
    ],
    "loan_warehouse.loan_products": [
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "effective_date",
    ],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id", "original_amount",
        "current_balance", "interest_rate", "term_months", "monthly_payment",
        "origination_date", "maturity_date", "status", "created_at", "updated_at",
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount",
        "principal_amount", "interest_amount", "type", "status",
        "created_at", "updated_at",
    ],
}


def check_null_required(spark: SparkSession) -> list:
    """Check that required fields have no null values."""
    results = []
    for table, columns in REQUIRED_FIELDS.items():
        try:
            df = spark.table(table)
            total = df.count()
            for col_name in columns:
                null_count = df.filter(F.col(col_name).isNull()).count()
                if null_count == 0:
                    status = "PASS"
                    details = f"No nulls in {col_name} ({total} rows checked)"
                else:
                    status = "FAIL"
                    details = (
                        f"{null_count}/{total} rows have null {col_name} "
                        f"({null_count / total * 100:.1f}%)"
                    )
                results.append(CheckResult(
                    category="Null Required Fields",
                    check_name=f"{table}.{col_name}",
                    table=table,
                    status=status,
                    details=details,
                    count=null_count,
                ))
        except Exception as e:
            results.append(CheckResult(
                category="Null Required Fields",
                check_name=f"{table}",
                table=table,
                status="FAIL",
                details=f"Error: {str(e)}",
            ))
    return results


# ---------------------------------------------------------------------------
# 3. Referential Integrity
# ---------------------------------------------------------------------------
def check_referential_integrity(spark: SparkSession) -> list:
    """Check FK relationships between tables."""
    results = []

    # loan_accounts.borrower_id → borrowers.borrower_id
    try:
        loans = spark.table("loan_warehouse.loan_accounts")
        borrowers = spark.table("loan_warehouse.borrowers")
        orphan_count = (
            loans.join(borrowers, loans["borrower_id"] == borrowers["borrower_id"], "left_anti")
            .count()
        )
        if orphan_count == 0:
            results.append(CheckResult(
                "Referential Integrity",
                "loan_accounts.borrower_id → borrowers",
                "loan_warehouse.loan_accounts",
                "PASS",
                "All loan accounts reference valid borrowers",
            ))
        else:
            results.append(CheckResult(
                "Referential Integrity",
                "loan_accounts.borrower_id → borrowers",
                "loan_warehouse.loan_accounts",
                "FAIL",
                f"{orphan_count} loan accounts reference non-existent borrowers",
                count=orphan_count,
            ))
    except Exception as e:
        results.append(CheckResult(
            "Referential Integrity",
            "loan_accounts.borrower_id → borrowers",
            "loan_warehouse.loan_accounts",
            "FAIL",
            f"Error: {str(e)}",
        ))

    # loan_accounts.product_id → loan_products.product_id
    try:
        products = spark.table("loan_warehouse.loan_products")
        orphan_count = (
            loans.join(products, loans["product_id"] == products["product_id"], "left_anti")
            .count()
        )
        if orphan_count == 0:
            results.append(CheckResult(
                "Referential Integrity",
                "loan_accounts.product_id → loan_products",
                "loan_warehouse.loan_accounts",
                "PASS",
                "All loan accounts reference valid products",
            ))
        else:
            results.append(CheckResult(
                "Referential Integrity",
                "loan_accounts.product_id → loan_products",
                "loan_warehouse.loan_accounts",
                "FAIL",
                f"{orphan_count} loan accounts reference non-existent products",
                count=orphan_count,
            ))
    except Exception as e:
        results.append(CheckResult(
            "Referential Integrity",
            "loan_accounts.product_id → loan_products",
            "loan_warehouse.loan_accounts",
            "FAIL",
            f"Error: {str(e)}",
        ))

    # payments.loan_account_id → loan_accounts.loan_account_id
    try:
        payments = spark.table("loan_warehouse.payments")
        orphan_count = (
            payments.join(
                loans, payments["loan_account_id"] == loans["loan_account_id"], "left_anti"
            ).count()
        )
        if orphan_count == 0:
            results.append(CheckResult(
                "Referential Integrity",
                "payments.loan_account_id → loan_accounts",
                "loan_warehouse.payments",
                "PASS",
                "All payments reference valid loan accounts",
            ))
        else:
            results.append(CheckResult(
                "Referential Integrity",
                "payments.loan_account_id → loan_accounts",
                "loan_warehouse.payments",
                "FAIL",
                f"{orphan_count} payments reference non-existent loan accounts",
                count=orphan_count,
            ))
    except Exception as e:
        results.append(CheckResult(
            "Referential Integrity",
            "payments.loan_account_id → loan_accounts",
            "loan_warehouse.payments",
            "FAIL",
            f"Error: {str(e)}",
        ))

    return results


# ---------------------------------------------------------------------------
# 4. Business Rule Validation
# ---------------------------------------------------------------------------
def check_business_rules(spark: SparkSession) -> list:
    """Validate business-level data constraints."""
    results = []

    try:
        loans = spark.table("loan_warehouse.loan_accounts")

        # Active loans must have positive balance
        active_zero_bal = loans.filter(
            (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
        ).count()
        results.append(CheckResult(
            "Business Rules",
            "Active loans have positive balance",
            "loan_warehouse.loan_accounts",
            "PASS" if active_zero_bal == 0 else "FAIL",
            f"{active_zero_bal} active loans have balance <= 0"
            if active_zero_bal > 0 else "All active loans have positive balance",
            count=active_zero_bal,
        ))

        # Interest rate must be positive
        bad_rate = loans.filter(F.col("interest_rate") <= 0).count()
        results.append(CheckResult(
            "Business Rules",
            "Interest rates are positive",
            "loan_warehouse.loan_accounts",
            "PASS" if bad_rate == 0 else "FAIL",
            f"{bad_rate} loans have non-positive interest rate"
            if bad_rate > 0 else "All interest rates are positive",
            count=bad_rate,
        ))

        # Origination date must be before maturity date
        bad_dates = loans.filter(
            F.col("origination_date") >= F.col("maturity_date")
        ).count()
        results.append(CheckResult(
            "Business Rules",
            "Origination date < maturity date",
            "loan_warehouse.loan_accounts",
            "PASS" if bad_dates == 0 else "FAIL",
            f"{bad_dates} loans have origination >= maturity date"
            if bad_dates > 0 else "All origination dates precede maturity dates",
            count=bad_dates,
        ))

        # Delinquency days consistency with status
        delinquent_active = loans.filter(
            (F.col("delinquency_days") > 0) & (F.col("status") == "ACTIVE")
        ).count()
        results.append(CheckResult(
            "Business Rules",
            "Delinquent loans not marked Active",
            "loan_warehouse.loan_accounts",
            "PASS" if delinquent_active == 0 else "WARN",
            f"{delinquent_active} loans are delinquent but still ACTIVE"
            if delinquent_active > 0
            else "No delinquent-but-active inconsistencies",
            count=delinquent_active,
        ))

        # LTV should be between 0 and 200
        bad_ltv = loans.filter(
            (F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200)
        ).count()
        results.append(CheckResult(
            "Business Rules",
            "LTV percent in valid range (0-200)",
            "loan_warehouse.loan_accounts",
            "PASS" if bad_ltv == 0 else "WARN",
            f"{bad_ltv} loans have LTV outside 0-200% range"
            if bad_ltv > 0 else "All LTV values within valid range",
            count=bad_ltv,
        ))
    except Exception as e:
        results.append(CheckResult(
            "Business Rules", "Loan validation", "loan_warehouse.loan_accounts",
            "FAIL", f"Error: {str(e)}",
        ))

    try:
        payments = spark.table("loan_warehouse.payments")

        # Payment total must be positive for posted payments
        bad_pmt = payments.filter(
            (F.col("status") == "POSTED") & (F.col("total_amount") <= 0)
        ).count()
        results.append(CheckResult(
            "Business Rules",
            "Posted payments have positive total",
            "loan_warehouse.payments",
            "PASS" if bad_pmt == 0 else "FAIL",
            f"{bad_pmt} posted payments have total <= 0"
            if bad_pmt > 0 else "All posted payments have positive totals",
            count=bad_pmt,
        ))

        # Payment components should sum to total (within tolerance)
        amt = lambda c: F.coalesce(F.col(c), F.lit(0).cast(DecimalType(10, 2)))
        recon = payments.withColumn(
            "component_sum",
            amt("principal_amount") + amt("interest_amount")
            + amt("escrow_amount") + amt("late_fee")
        ).withColumn(
            "delta", F.abs(F.col("component_sum") - F.col("total_amount"))
        )
        bad_recon = recon.filter(F.col("delta") > 0.02).count()
        results.append(CheckResult(
            "Business Rules",
            "Payment components sum to total",
            "loan_warehouse.payments",
            "PASS" if bad_recon == 0 else "WARN",
            f"{bad_recon} payments have component sum != total (delta > $0.02)"
            if bad_recon > 0 else "All payment components balance",
            count=bad_recon,
        ))

    except Exception as e:
        results.append(CheckResult(
            "Business Rules", "Payment validation", "loan_warehouse.payments",
            "FAIL", f"Error: {str(e)}",
        ))

    try:
        borrowers = spark.table("loan_warehouse.borrowers")

        # Credit score in valid range
        bad_score = borrowers.filter(
            F.col("credit_score").isNotNull()
            & (~F.col("credit_score").between(300, 850))
        ).count()
        results.append(CheckResult(
            "Business Rules",
            "Credit scores in 300-850 range",
            "loan_warehouse.borrowers",
            "PASS" if bad_score == 0 else "WARN",
            f"{bad_score} borrowers have credit score outside 300-850"
            if bad_score > 0 else "All credit scores within valid range",
            count=bad_score,
        ))

    except Exception as e:
        results.append(CheckResult(
            "Business Rules", "Borrower validation", "loan_warehouse.borrowers",
            "FAIL", f"Error: {str(e)}",
        ))

    return results


# ---------------------------------------------------------------------------
# 5. Report Generation
# ---------------------------------------------------------------------------
def generate_report(results: list, output_path: str = None) -> str:
    """Generate a Markdown data quality report from check results."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    warned = sum(1 for r in results if r.status == "WARN")

    lines = [
        "# Data Quality Report",
        "",
        f"> **Generated:** {now}",
        f"> **Pipeline Run:** Post-ingestion validation",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total Checks | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Warnings | {warned} |",
        f"| Pass Rate | {passed/total*100:.1f}% |" if total > 0 else "",
        "",
        "---",
        "",
    ]

    # Group by category
    categories = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    for category, checks in categories.items():
        lines.append(f"## {category}")
        lines.append("")
        lines.append("| Check | Table | Status | Details |")
        lines.append("|-------|-------|--------|---------|")
        for c in checks:
            icon = {"PASS": "PASS", "FAIL": "**FAIL**", "WARN": "WARN"}[c.status]
            lines.append(f"| {c.check_name} | {c.table} | {icon} | {c.details} |")
        lines.append("")

    # DQ Log anomalies summary
    lines.append("## Anomalies from Ingestion Pipeline")
    lines.append("")
    lines.append("See `loan_warehouse.data_quality_log` for full anomaly details.")
    lines.append("")

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w") as f:
            f.write(report)

    return report


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def run(spark: SparkSession, report_path: str = None) -> str:
    """Run all quality checks and generate report."""
    print("Running data quality checks...")

    all_results = []
    all_results.extend(check_row_counts(spark))
    all_results.extend(check_null_required(spark))
    all_results.extend(check_referential_integrity(spark))
    all_results.extend(check_business_rules(spark))

    report = generate_report(all_results, report_path)

    passed = sum(1 for r in all_results if r.status == "PASS")
    failed = sum(1 for r in all_results if r.status == "FAIL")
    warned = sum(1 for r in all_results if r.status == "WARN")
    print(f"Quality checks complete: {passed} passed, {failed} failed, {warned} warnings")

    if failed > 0:
        print("CRITICAL: Quality checks have failures. Review report.")
        for r in all_results:
            if r.status == "FAIL":
                print(f"  FAIL: {r.check_name} — {r.details}")

    return report


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Data Quality Checks").getOrCreate()
    report = run(spark, REPORT_PATH)
    print(report)
