"""
Data Quality Framework for the Legacy CDW → Delta Lake Migration.

Runs post-ingestion validation checks against the Delta Lake tables and
produces a structured report. Checks include:
  - Row count reconciliation (source vs target)
  - Null checks on required fields
  - Referential integrity between tables
  - Business rule validation
  - Payment component sum consistency

Usage (Databricks notebook):
    %run ./data_quality_checks

    report = run_all_checks(spark, source_counts={
        "CDW_BORR_MSTR": 5,
        "CDW_LN_PROD": 4,
        "CDW_LN_ACCT": 5,
        "CDW_PMT_HIST": 12,
    })
    print(report.to_markdown())
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class CheckStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class CheckResult:
    category: str
    check_name: str
    status: CheckStatus
    details: str
    affected_rows: int = 0
    table: str = ""


@dataclass
class QualityReport:
    results: list = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.FAIL)

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.WARN)

    def add(self, result: CheckResult):
        self.results.append(result)

    def to_markdown(self) -> str:
        lines = [
            "# Data Quality Report",
            "",
            f"**Total Checks:** {len(self.results)}  ",
            f"**Passed:** {self.pass_count}  ",
            f"**Failed:** {self.fail_count}  ",
            f"**Warnings:** {self.warn_count}  ",
            "",
            "## Results",
            "",
            "| Category | Check | Table | Status | Affected Rows | Details |",
            "|----------|-------|-------|--------|---------------|---------|",
        ]
        for r in self.results:
            icon = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN"}[r.status.value]
            lines.append(
                f"| {r.category} | {r.check_name} | {r.table} | {icon} | "
                f"{r.affected_rows} | {r.details} |"
            )
        lines.append("")

        # Detailed failures
        failures = [r for r in self.results if r.status == CheckStatus.FAIL]
        if failures:
            lines.append("## Failed Checks — Details")
            lines.append("")
            for r in failures:
                lines.append(f"### {r.check_name} ({r.table})")
                lines.append(f"- **Affected rows:** {r.affected_rows}")
                lines.append(f"- **Details:** {r.details}")
                lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def check_row_counts(
    spark: SparkSession,
    report: QualityReport,
    source_counts: dict,
):
    """Reconcile row counts between source extracts and target Delta tables."""
    target_map = {
        "CDW_BORR_MSTR": "loan_warehouse.borrowers",
        "CDW_LN_PROD": "loan_warehouse.loan_products",
        "CDW_LN_ACCT": "loan_warehouse.loan_accounts",
        "CDW_PMT_HIST": "loan_warehouse.payments",
    }
    for source_name, target_table in target_map.items():
        expected = source_counts.get(source_name)
        if expected is None:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"Count reconciliation: {source_name}",
                status=CheckStatus.WARN,
                details=f"No source count provided for {source_name}",
                table=target_table,
            ))
            continue

        actual = spark.table(target_table).count()
        if actual == expected:
            report.add(CheckResult(
                category="Row Count",
                check_name=f"Count reconciliation: {source_name}",
                status=CheckStatus.PASS,
                details=f"Source: {expected}, Target: {actual}",
                table=target_table,
            ))
        else:
            diff = expected - actual
            report.add(CheckResult(
                category="Row Count",
                check_name=f"Count reconciliation: {source_name}",
                status=CheckStatus.FAIL if diff > 0 else CheckStatus.WARN,
                details=f"Source: {expected}, Target: {actual}, Delta: {diff}",
                affected_rows=abs(diff),
                table=target_table,
            ))


def check_required_nulls(spark: SparkSession, report: QualityReport):
    """Check for nulls in columns that should never be null."""
    required_fields = {
        "loan_warehouse.borrowers": [
            "external_id", "first_name", "last_name", "status",
        ],
        "loan_warehouse.loan_products": [
            "code", "name", "type", "term_months", "rate_type",
        ],
        "loan_warehouse.loan_accounts": [
            "account_number", "original_amount", "current_balance",
            "interest_rate", "term_months", "monthly_payment",
            "origination_date", "maturity_date", "status",
        ],
        "loan_warehouse.payments": [
            "legacy_sequence_nbr", "payment_date", "total_amount",
            "principal_amount", "interest_amount", "type", "status",
        ],
    }

    for table, columns in required_fields.items():
        df = spark.table(table)
        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            if null_count == 0:
                report.add(CheckResult(
                    category="Null Check",
                    check_name=f"NOT NULL: {col_name}",
                    status=CheckStatus.PASS,
                    details=f"No nulls found in {col_name}",
                    table=table,
                ))
            else:
                report.add(CheckResult(
                    category="Null Check",
                    check_name=f"NOT NULL: {col_name}",
                    status=CheckStatus.FAIL,
                    details=f"{null_count} null values in required column {col_name}",
                    affected_rows=null_count,
                    table=table,
                ))


def check_referential_integrity(spark: SparkSession, report: QualityReport):
    """Check FK relationships between tables."""
    # loan_accounts.borrower_id → borrowers.borrower_id
    loans = spark.table("loan_warehouse.loan_accounts")
    borrowers = spark.table("loan_warehouse.borrowers")

    orphan_loans = loans.join(
        borrowers,
        loans["borrower_id"] == borrowers["borrower_id"],
        "left_anti",
    ).count()

    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.borrower_id → borrowers",
        status=CheckStatus.PASS if orphan_loans == 0 else CheckStatus.FAIL,
        details=f"{orphan_loans} loans with no matching borrower" if orphan_loans > 0 else "All loans have valid borrower references",
        affected_rows=orphan_loans,
        table="loan_warehouse.loan_accounts",
    ))

    # loan_accounts.product_id → loan_products.product_id
    products = spark.table("loan_warehouse.loan_products")
    orphan_products = loans.join(
        products,
        loans["product_id"] == products["product_id"],
        "left_anti",
    ).count()

    report.add(CheckResult(
        category="Referential Integrity",
        check_name="loan_accounts.product_id → loan_products",
        status=CheckStatus.PASS if orphan_products == 0 else CheckStatus.FAIL,
        details=f"{orphan_products} loans with no matching product" if orphan_products > 0 else "All loans have valid product references",
        affected_rows=orphan_products,
        table="loan_warehouse.loan_accounts",
    ))

    # payments.loan_account_id → loan_accounts.loan_account_id
    payments = spark.table("loan_warehouse.payments")
    orphan_payments = payments.join(
        loans,
        payments["loan_account_id"] == loans["loan_account_id"],
        "left_anti",
    ).count()

    report.add(CheckResult(
        category="Referential Integrity",
        check_name="payments.loan_account_id → loan_accounts",
        status=CheckStatus.PASS if orphan_payments == 0 else CheckStatus.FAIL,
        details=f"{orphan_payments} payments with no matching loan" if orphan_payments > 0 else "All payments have valid loan references",
        affected_rows=orphan_payments,
        table="loan_warehouse.payments",
    ))


def check_business_rules(spark: SparkSession, report: QualityReport):
    """Validate domain-specific business rules."""
    loans = spark.table("loan_warehouse.loan_accounts")
    payments = spark.table("loan_warehouse.payments")
    borrowers = spark.table("loan_warehouse.borrowers")

    # Rule 1: Active loans must have positive balance
    active_zero_balance = loans.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loans have positive balance",
        status=CheckStatus.PASS if active_zero_balance == 0 else CheckStatus.FAIL,
        details=f"{active_zero_balance} active loans with balance <= 0" if active_zero_balance > 0 else "All active loans have positive balance",
        affected_rows=active_zero_balance,
        table="loan_warehouse.loan_accounts",
    ))

    # Rule 2: Closed loans should have a maturity date in the past or current balance near 0
    closed_with_balance = loans.filter(
        (F.col("status") == "CLOSED") & (F.col("current_balance") > 100)
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="Closed loans have near-zero balance",
        status=CheckStatus.PASS if closed_with_balance == 0 else CheckStatus.WARN,
        details=f"{closed_with_balance} closed loans still have balance > $100" if closed_with_balance > 0 else "All closed loans have near-zero balance",
        affected_rows=closed_with_balance,
        table="loan_warehouse.loan_accounts",
    ))

    # Rule 3: Delinquency days should be 0 for active loans (data quality concern)
    delinquent_active = loans.filter(
        (F.col("status") == "ACTIVE") & (F.col("delinquency_days") > 0)
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="Active loan delinquency consistency",
        status=CheckStatus.PASS if delinquent_active == 0 else CheckStatus.WARN,
        details=f"{delinquent_active} active loans have delinquency_days > 0 — review status accuracy" if delinquent_active > 0 else "No delinquency/status mismatches",
        affected_rows=delinquent_active,
        table="loan_warehouse.loan_accounts",
    ))

    # Rule 4: Payment component amounts should sum to total
    payments_with_sum = payments.withColumn(
        "_comp_sum",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0)),
    )
    sum_mismatch = payments_with_sum.filter(
        F.abs(F.col("_comp_sum") - F.col("total_amount")) > 0.01
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="Payment component sum matches total",
        status=CheckStatus.PASS if sum_mismatch == 0 else CheckStatus.FAIL,
        details=f"{sum_mismatch} payments where principal+interest+escrow+late_fee != total_amount" if sum_mismatch > 0 else "All payment components sum to total",
        affected_rows=sum_mismatch,
        table="loan_warehouse.payments",
    ))

    # Rule 5: Credit scores should be in valid range (300–850)
    invalid_scores = borrowers.filter(
        F.col("credit_score").isNotNull()
        & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="Credit scores in valid range (300-850)",
        status=CheckStatus.PASS if invalid_scores == 0 else CheckStatus.WARN,
        details=f"{invalid_scores} borrowers with credit score outside 300-850" if invalid_scores > 0 else "All credit scores in valid range",
        affected_rows=invalid_scores,
        table="loan_warehouse.borrowers",
    ))

    # Rule 6: Interest rates should be positive and reasonable (0-30%)
    bad_rates = loans.filter(
        (F.col("interest_rate") <= 0) | (F.col("interest_rate") > 30)
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="Interest rates in valid range (0-30%)",
        status=CheckStatus.PASS if bad_rates == 0 else CheckStatus.FAIL,
        details=f"{bad_rates} loans with interest rate outside 0-30%" if bad_rates > 0 else "All interest rates in valid range",
        affected_rows=bad_rates,
        table="loan_warehouse.loan_accounts",
    ))

    # Rule 7: Origination date should be before maturity date
    bad_dates = loans.filter(
        F.col("origination_date") >= F.col("maturity_date")
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="Origination date before maturity date",
        status=CheckStatus.PASS if bad_dates == 0 else CheckStatus.FAIL,
        details=f"{bad_dates} loans where origination >= maturity" if bad_dates > 0 else "All loans have valid date ordering",
        affected_rows=bad_dates,
        table="loan_warehouse.loan_accounts",
    ))

    # Rule 8: LTV should not exceed 200%
    high_ltv = loans.filter(
        F.col("ltv_percent").isNotNull() & (F.col("ltv_percent") > 200)
    ).count()

    report.add(CheckResult(
        category="Business Rule",
        check_name="LTV ratio <= 200%",
        status=CheckStatus.PASS if high_ltv == 0 else CheckStatus.WARN,
        details=f"{high_ltv} loans with LTV > 200%" if high_ltv > 0 else "All LTV ratios within bounds",
        affected_rows=high_ltv,
        table="loan_warehouse.loan_accounts",
    ))


def check_valid_status_codes(spark: SparkSession, report: QualityReport):
    """Verify all status fields contain only expected values after expansion."""
    checks = [
        ("loan_warehouse.loan_accounts", "status", {"ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE", "UNKNOWN"}),
        ("loan_warehouse.borrowers", "status", {"ACTIVE", "INACTIVE", "UNKNOWN"}),
        ("loan_warehouse.payments", "type", {"REGULAR", "EXTRA", "PARTIAL", "PREPAYMENT", "UNKNOWN"}),
        ("loan_warehouse.payments", "status", {"POSTED", "REVERSED", "NSF", "PENDING", "UNKNOWN"}),
    ]

    for table, col_name, valid_values in checks:
        df = spark.table(table)
        distinct_values = {row[col_name] for row in df.select(col_name).distinct().collect() if row[col_name] is not None}
        invalid = distinct_values - valid_values

        if not invalid:
            report.add(CheckResult(
                category="Status Codes",
                check_name=f"Valid {col_name} values",
                status=CheckStatus.PASS,
                details=f"All values in {valid_values}",
                table=table,
            ))
        else:
            bad_count = df.filter(F.col(col_name).isin(list(invalid))).count()
            report.add(CheckResult(
                category="Status Codes",
                check_name=f"Valid {col_name} values",
                status=CheckStatus.FAIL,
                details=f"Unexpected values: {invalid}",
                affected_rows=bad_count,
                table=table,
            ))


def check_duplicates(spark: SparkSession, report: QualityReport):
    """Check for duplicate records on natural keys."""
    dup_checks = [
        ("loan_warehouse.borrowers", "external_id"),
        ("loan_warehouse.loan_products", "code"),
        ("loan_warehouse.loan_accounts", "account_number"),
        ("loan_warehouse.payments", "legacy_sequence_nbr"),
    ]

    for table, key_col in dup_checks:
        df = spark.table(table)
        total = df.count()
        distinct = df.select(key_col).distinct().count()
        dups = total - distinct

        report.add(CheckResult(
            category="Duplicates",
            check_name=f"Unique {key_col}",
            status=CheckStatus.PASS if dups == 0 else CheckStatus.FAIL,
            details=f"{dups} duplicate records on {key_col}" if dups > 0 else f"All {total} records have unique {key_col}",
            affected_rows=dups,
            table=table,
        ))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all_checks(
    spark: SparkSession,
    source_counts: Optional[dict] = None,
) -> QualityReport:
    """
    Run the full data quality suite and return a report.

    Args:
        spark: Active SparkSession.
        source_counts: Dict mapping source table name to expected row count.
                       e.g. {"CDW_BORR_MSTR": 5, "CDW_LN_PROD": 4, ...}
    """
    report = QualityReport()

    print("=" * 60)
    print("DATA QUALITY CHECK SUITE")
    print("=" * 60)

    if source_counts:
        print("\n[1/6] Row count reconciliation...")
        check_row_counts(spark, report, source_counts)

    print("\n[2/6] Required field null checks...")
    check_required_nulls(spark, report)

    print("\n[3/6] Referential integrity...")
    check_referential_integrity(spark, report)

    print("\n[4/6] Business rule validation...")
    check_business_rules(spark, report)

    print("\n[5/6] Status code validation...")
    check_valid_status_codes(spark, report)

    print("\n[6/6] Duplicate detection...")
    check_duplicates(spark, report)

    print("\n" + "=" * 60)
    print(f"COMPLETE: {report.pass_count} passed, {report.fail_count} failed, {report.warn_count} warnings")
    print("=" * 60)

    return report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("DataQualityChecks").getOrCreate()

    # These counts should match the legacy CDW source extraction counts
    source_counts = {
        "CDW_BORR_MSTR": 5,
        "CDW_LN_PROD": 4,
        "CDW_LN_ACCT": 5,
        "CDW_PMT_HIST": 12,
    }

    report = run_all_checks(spark, source_counts)
    markdown = report.to_markdown()
    print(markdown)

    # Write report to DBFS
    dbutils.fs.put(  # noqa: F821 — dbutils is available in Databricks runtime
        "dbfs:/mnt/loan-warehouse/reports/DATA_QUALITY_REPORT.md",
        markdown,
        overwrite=True,
    )
    print("Report written to dbfs:/mnt/loan-warehouse/reports/DATA_QUALITY_REPORT.md")
