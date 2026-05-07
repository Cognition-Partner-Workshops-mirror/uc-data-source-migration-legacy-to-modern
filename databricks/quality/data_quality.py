"""
Data Quality Framework for the CDW-to-Databricks migration.

Runs post-ingestion validation checks and generates a ``DATA_QUALITY_REPORT.md``
summarising pass/fail results across four categories:

1. **Row-count reconciliation** — source vs. target counts per table.
2. **Null checks** — required (NOT NULL) fields must have zero nulls.
3. **Referential integrity** — every FK in loan_accounts/payments resolves.
4. **Business-rule validation** — domain-specific constraints on loan data.

Usage (Databricks notebook / job):
    from quality.data_quality import run_quality_checks
    report = run_quality_checks(spark, source_base_path="dbfs:/mnt/legacy/")
    # report.to_markdown()  — returns the full report string
    # report.write("dbfs:/mnt/reports/DATA_QUALITY_REPORT.md")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

logger = logging.getLogger("quality")


# ── Result types ────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Single quality check result with category, name, pass/fail status, and detail."""
    category: str
    name: str
    passed: bool
    detail: str = ""

    def status_label(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass
class QualityReport:
    """Aggregates all check results and generates markdown report output."""
    checks: list[CheckResult] = field(default_factory=list)
    generated_at: str = ""

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def overall_passed(self) -> bool:
        return self.fail_count == 0

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# Data Quality Report")
        lines.append("")
        lines.append(f"**Generated:** {self.generated_at}  ")
        status = "ALL CHECKS PASSED" if self.overall_passed else "FAILURES DETECTED"
        lines.append(f"**Overall Status:** {status}  ")
        lines.append(f"**Passed:** {self.pass_count}  |  **Failed:** {self.fail_count}  |  **Total:** {len(self.checks)}")
        lines.append("")

        categories = sorted(set(c.category for c in self.checks))
        for cat in categories:
            lines.append(f"## {cat}")
            lines.append("")
            lines.append("| # | Check | Status | Detail |")
            lines.append("|---|-------|--------|--------|")
            cat_checks = [c for c in self.checks if c.category == cat]
            for i, chk in enumerate(cat_checks, 1):
                icon = "PASS" if chk.passed else "**FAIL**"
                lines.append(f"| {i} | {chk.name} | {icon} | {chk.detail} |")
            lines.append("")

        return "\n".join(lines)

    def write(self, path: str) -> None:
        """Write the markdown report to DBFS or local filesystem."""
        with open(path, "w") as f:
            f.write(self.to_markdown())
        logger.info("Quality report written to %s", path)


# ── Check implementations ──────────────────────────────────────────────────

def _count_source(spark: SparkSession, path: str, fmt: str) -> int:
    """Count rows in a source file (CSV/Parquet)."""
    try:
        if fmt == "csv":
            return spark.read.option("header", "true").csv(path).count()
        else:
            return spark.read.parquet(path).count()
    except Exception as e:
        logger.warning("Could not read source at %s: %s", path, e)
        return -1


def check_row_counts(
    spark: SparkSession,
    source_base: str,
    fmt: str = "csv",
) -> list[CheckResult]:
    """Compare row counts between legacy source files and target Delta tables."""
    results: list[CheckResult] = []
    bp = source_base.rstrip("/")

    table_map = {
        "borrowers": f"{bp}/cdw_borr_mstr/",
        "loan_products": f"{bp}/cdw_ln_prod/",
        "loan_accounts": f"{bp}/cdw_ln_acct/",
        "payments": f"{bp}/cdw_pmt_hist/",
    }

    for table, source_path in table_map.items():
        src_count = _count_source(spark, source_path, fmt)
        try:
            tgt_count = spark.table(f"loan_warehouse.{table}").count()
        except Exception:
            tgt_count = -1

        passed = src_count == tgt_count and src_count >= 0
        results.append(CheckResult(
            category="1. Row Count Reconciliation",
            name=f"{table}: source vs target",
            passed=passed,
            detail=f"Source={src_count}, Target={tgt_count}",
        ))

    return results


def check_nulls(spark: SparkSession) -> list[CheckResult]:
    """Check that required (NOT NULL) columns have zero null values."""
    results: list[CheckResult] = []

    required_fields: dict[str, list[str]] = {
        "borrowers": ["external_id", "first_name", "last_name", "status"],
        "loan_products": ["code", "name", "type", "term_months", "rate_type"],
        "loan_accounts": [
            "account_number", "borrower_id", "product_id",
            "original_amount", "current_balance", "interest_rate",
            "term_months", "monthly_payment", "origination_date",
            "maturity_date", "status",
        ],
        "payments": [
            "loan_account_id", "payment_date", "total_amount", "type", "status",
        ],
    }

    for table, columns in required_fields.items():
        try:
            df = spark.table(f"loan_warehouse.{table}")
        except Exception:
            for col_name in columns:
                results.append(CheckResult(
                    category="2. Null Checks",
                    name=f"{table}.{col_name} NOT NULL",
                    passed=False,
                    detail="Table not found",
                ))
            continue

        for col_name in columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            results.append(CheckResult(
                category="2. Null Checks",
                name=f"{table}.{col_name} NOT NULL",
                passed=null_count == 0,
                detail=f"Null count: {null_count}",
            ))

    return results


def check_referential_integrity(spark: SparkSession) -> list[CheckResult]:
    """Verify that every FK in child tables resolves to a parent row."""
    results: list[CheckResult] = []

    # loan_accounts.borrower_id → borrowers.borrower_id
    try:
        loans = spark.table("loan_warehouse.loan_accounts")
        borrowers = spark.table("loan_warehouse.borrowers")
        orphan_borrower = loans.join(
            borrowers,
            loans["borrower_id"] == borrowers["borrower_id"],
            "left_anti",
        ).count()
        results.append(CheckResult(
            category="3. Referential Integrity",
            name="loan_accounts.borrower_id → borrowers",
            passed=orphan_borrower == 0,
            detail=f"Orphaned rows: {orphan_borrower}",
        ))
    except Exception as e:
        results.append(CheckResult(
            category="3. Referential Integrity",
            name="loan_accounts.borrower_id → borrowers",
            passed=False,
            detail=f"Error: {e}",
        ))

    # loan_accounts.product_id → loan_products.product_id
    try:
        products = spark.table("loan_warehouse.loan_products")
        orphan_product = loans.join(
            products,
            loans["product_id"] == products["product_id"],
            "left_anti",
        ).count()
        results.append(CheckResult(
            category="3. Referential Integrity",
            name="loan_accounts.product_id → loan_products",
            passed=orphan_product == 0,
            detail=f"Orphaned rows: {orphan_product}",
        ))
    except Exception as e:
        results.append(CheckResult(
            category="3. Referential Integrity",
            name="loan_accounts.product_id → loan_products",
            passed=False,
            detail=f"Error: {e}",
        ))

    # payments.loan_account_id → loan_accounts.loan_account_id
    try:
        payments = spark.table("loan_warehouse.payments")
        orphan_loan = payments.join(
            loans,
            payments["loan_account_id"] == loans["loan_account_id"],
            "left_anti",
        ).count()
        results.append(CheckResult(
            category="3. Referential Integrity",
            name="payments.loan_account_id → loan_accounts",
            passed=orphan_loan == 0,
            detail=f"Orphaned rows: {orphan_loan}",
        ))
    except Exception as e:
        results.append(CheckResult(
            category="3. Referential Integrity",
            name="payments.loan_account_id → loan_accounts",
            passed=False,
            detail=f"Error: {e}",
        ))

    return results


def check_business_rules(spark: SparkSession) -> list[CheckResult]:
    """Validate domain-specific business rules on the migrated data."""
    results: list[CheckResult] = []

    try:
        loans = spark.table("loan_warehouse.loan_accounts")
    except Exception:
        results.append(CheckResult(
            category="4. Business Rules",
            name="loan_accounts table accessible",
            passed=False,
            detail="Table not found",
        ))
        return results

    # Business Rule 1: Active loans must have a positive balance to be valid
    active_zero_bal = loans.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    ).count()
    results.append(CheckResult(
        category="4. Business Rules",
        name="Active loans have balance > 0",
        passed=active_zero_bal == 0,
        detail=f"Violations: {active_zero_bal}",
    ))

    # Business Rule 2: All loans must have a positive original amount
    negative_orig = loans.filter(F.col("original_amount") <= 0).count()
    results.append(CheckResult(
        category="4. Business Rules",
        name="All loans have positive original_amount",
        passed=negative_orig == 0,
        detail=f"Violations: {negative_orig}",
    ))

    # Business Rule 3: Interest rate must be a valid percentage [0, 100]
    bad_rate = loans.filter(
        (F.col("interest_rate") < 0) | (F.col("interest_rate") > 100)
    ).count()
    results.append(CheckResult(
        category="4. Business Rules",
        name="Interest rates in range [0, 100]",
        passed=bad_rate == 0,
        detail=f"Violations: {bad_rate}",
    ))

    # Business Rule 4: Maturity date must be after origination to be logically valid
    bad_dates = loans.filter(
        F.col("maturity_date") <= F.col("origination_date")
    ).count()
    results.append(CheckResult(
        category="4. Business Rules",
        name="Maturity date > origination date",
        passed=bad_dates == 0,
        detail=f"Violations: {bad_dates}",
    ))

    # Business Rule 5: LTV percent must be in [0, 200] — allows up to 200% for underwater loans
    bad_ltv = loans.filter(
        F.col("ltv_percent").isNotNull()
        & ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    results.append(CheckResult(
        category="4. Business Rules",
        name="LTV percent in range [0, 200]",
        passed=bad_ltv == 0,
        detail=f"Violations: {bad_ltv}",
    ))

    # Business Rule 6: Delinquency days cannot be negative
    bad_dlq = loans.filter(F.col("delinquency_days") < 0).count()
    results.append(CheckResult(
        category="4. Business Rules",
        name="Delinquency days >= 0",
        passed=bad_dlq == 0,
        detail=f"Violations: {bad_dlq}",
    ))

    # Business Rule 7: Loan status must be one of the expanded status values
    valid_statuses = {"ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE"}
    unknown_status = loans.filter(~F.col("status").isin(valid_statuses)).count()
    results.append(CheckResult(
        category="4. Business Rules",
        name="Loan status values are valid",
        passed=unknown_status == 0,
        detail=f"Unknown statuses: {unknown_status}",
    ))

    # Business Rule 8: Payment amounts must be non-negative
    try:
        payments = spark.table("loan_warehouse.payments")
        neg_pmt = payments.filter(F.col("total_amount") < 0).count()
        results.append(CheckResult(
            category="4. Business Rules",
            name="Payment amounts >= 0",
            passed=neg_pmt == 0,
            detail=f"Violations: {neg_pmt}",
        ))
    except Exception:
        results.append(CheckResult(
            category="4. Business Rules",
            name="Payment amounts >= 0",
            passed=False,
            detail="payments table not found",
        ))

    # Business Rule 9: Credit scores must be in FICO range [300, 850]
    try:
        borrowers = spark.table("loan_warehouse.borrowers")
        bad_credit = borrowers.filter(
            F.col("credit_score").isNotNull()
            & ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
        ).count()
        results.append(CheckResult(
            category="4. Business Rules",
            name="Credit scores in range [300, 850]",
            passed=bad_credit == 0,
            detail=f"Violations: {bad_credit}",
        ))
    except Exception:
        results.append(CheckResult(
            category="4. Business Rules",
            name="Credit scores in range [300, 850]",
            passed=False,
            detail="borrowers table not found",
        ))

    # Business Rule 10: Annual income cannot be negative
    try:
        borrowers = spark.table("loan_warehouse.borrowers")
        neg_income = borrowers.filter(
            F.col("annual_income").isNotNull() & (F.col("annual_income") < 0)
        ).count()
        results.append(CheckResult(
            category="4. Business Rules",
            name="Annual income >= 0",
            passed=neg_income == 0,
            detail=f"Violations: {neg_income}",
        ))
    except Exception:
        results.append(CheckResult(
            category="4. Business Rules",
            name="Annual income >= 0",
            passed=False,
            detail="borrowers table not found",
        ))

    return results


# ── Orchestrator ────────────────────────────────────────────────────────────

def run_quality_checks(
    spark: SparkSession,
    source_base_path: str,
    source_format: str = "csv",
    report_output_path: str | None = None,
) -> QualityReport:
    """Execute all quality checks and produce a report.

    Parameters
    ----------
    spark : SparkSession
    source_base_path : str
        Path to the legacy source files (same as used for ingestion).
    source_format : str
        ``"csv"`` or ``"parquet"``.
    report_output_path : str, optional
        If provided, writes the markdown report to this path.

    Returns
    -------
    QualityReport
    """
    report = QualityReport(generated_at=datetime.utcnow().isoformat() + "Z")

    logger.info("Running row-count reconciliation checks …")
    report.checks.extend(check_row_counts(spark, source_base_path, source_format))

    logger.info("Running null checks …")
    report.checks.extend(check_nulls(spark))

    logger.info("Running referential integrity checks …")
    report.checks.extend(check_referential_integrity(spark))

    logger.info("Running business-rule checks …")
    report.checks.extend(check_business_rules(spark))

    logger.info(
        "Quality checks complete — %d passed, %d failed out of %d total",
        report.pass_count,
        report.fail_count,
        len(report.checks),
    )

    if report_output_path:
        report.write(report_output_path)

    return report
