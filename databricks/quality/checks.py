"""
Data Quality Check Definitions for the CDW Migration.

Each check is a function that takes a SparkSession and returns a CheckResult
with pass/fail status, details, and metrics.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"


@dataclass
class CheckResult:
    name: str
    category: str
    status: CheckStatus
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    details: dict = field(default_factory=dict)


# =============================================================================
# Row Count Reconciliation Checks
# =============================================================================


def check_borrower_row_count(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.borrowers",
) -> CheckResult:
    """Verify source and target borrower row counts match."""
    try:
        if source_path.endswith(".parquet") or source_path.endswith(".parquet/"):
            source_df = spark.read.parquet(source_path)
        else:
            source_df = spark.read.option("header", "true").csv(source_path)

        source_count = source_df.count()
        target_count = spark.table(target_table).count()

        if source_count == target_count:
            return CheckResult(
                name="Borrower Row Count Reconciliation",
                category="Row Count",
                status=CheckStatus.PASSED,
                message=f"Source and target counts match: {source_count}",
                expected=str(source_count),
                actual=str(target_count),
            )
        else:
            return CheckResult(
                name="Borrower Row Count Reconciliation",
                category="Row Count",
                status=CheckStatus.FAILED,
                message=f"Row count mismatch: source={source_count}, target={target_count}",
                expected=str(source_count),
                actual=str(target_count),
                details={"difference": source_count - target_count},
            )
    except Exception as e:
        return CheckResult(
            name="Borrower Row Count Reconciliation",
            category="Row Count",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_loan_products_row_count(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.loan_products",
) -> CheckResult:
    """Verify source and target loan products row counts match."""
    try:
        if source_path.endswith(".parquet") or source_path.endswith(".parquet/"):
            source_df = spark.read.parquet(source_path)
        else:
            source_df = spark.read.option("header", "true").csv(source_path)

        source_count = source_df.count()
        target_count = spark.table(target_table).count()

        if source_count == target_count:
            return CheckResult(
                name="Loan Products Row Count Reconciliation",
                category="Row Count",
                status=CheckStatus.PASSED,
                message=f"Source and target counts match: {source_count}",
                expected=str(source_count),
                actual=str(target_count),
            )
        else:
            return CheckResult(
                name="Loan Products Row Count Reconciliation",
                category="Row Count",
                status=CheckStatus.FAILED,
                message=f"Row count mismatch: source={source_count}, target={target_count}",
                expected=str(source_count),
                actual=str(target_count),
                details={"difference": source_count - target_count},
            )
    except Exception as e:
        return CheckResult(
            name="Loan Products Row Count Reconciliation",
            category="Row Count",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_loan_accounts_row_count(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.loan_accounts",
) -> CheckResult:
    """Verify source and target loan accounts row counts match."""
    try:
        if source_path.endswith(".parquet") or source_path.endswith(".parquet/"):
            source_df = spark.read.parquet(source_path)
        else:
            source_df = spark.read.option("header", "true").csv(source_path)

        source_count = source_df.count()
        target_count = spark.table(target_table).count()

        if source_count == target_count:
            return CheckResult(
                name="Loan Accounts Row Count Reconciliation",
                category="Row Count",
                status=CheckStatus.PASSED,
                message=f"Source and target counts match: {source_count}",
                expected=str(source_count),
                actual=str(target_count),
            )
        else:
            return CheckResult(
                name="Loan Accounts Row Count Reconciliation",
                category="Row Count",
                status=CheckStatus.FAILED,
                message=f"Row count mismatch: source={source_count}, target={target_count}",
                expected=str(source_count),
                actual=str(target_count),
                details={"difference": source_count - target_count},
            )
    except Exception as e:
        return CheckResult(
            name="Loan Accounts Row Count Reconciliation",
            category="Row Count",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_payments_row_count(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.payments",
) -> CheckResult:
    """Verify source and target payments row counts match."""
    try:
        if source_path.endswith(".parquet") or source_path.endswith(".parquet/"):
            source_df = spark.read.parquet(source_path)
        else:
            source_df = spark.read.option("header", "true").csv(source_path)

        source_count = source_df.count()
        target_count = spark.table(target_table).count()

        if source_count == target_count:
            return CheckResult(
                name="Payments Row Count Reconciliation",
                category="Row Count",
                status=CheckStatus.PASSED,
                message=f"Source and target counts match: {source_count}",
                expected=str(source_count),
                actual=str(target_count),
            )
        else:
            return CheckResult(
                name="Payments Row Count Reconciliation",
                category="Row Count",
                status=CheckStatus.FAILED,
                message=f"Row count mismatch: source={source_count}, target={target_count}",
                expected=str(source_count),
                actual=str(target_count),
                details={"difference": source_count - target_count},
            )
    except Exception as e:
        return CheckResult(
            name="Payments Row Count Reconciliation",
            category="Row Count",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


# =============================================================================
# Null Checks on Required Fields
# =============================================================================


def check_borrower_required_fields(
    spark: SparkSession,
    target_table: str = "loan_warehouse.borrowers",
) -> CheckResult:
    """Check that required borrower fields have no NULL values."""
    try:
        df = spark.table(target_table)
        total = df.count()

        required_fields = ["external_id", "first_name", "last_name", "status"]
        null_counts = {}

        for field_name in required_fields:
            null_count = df.filter(F.col(field_name).isNull()).count()
            if null_count > 0:
                null_counts[field_name] = null_count

        if not null_counts:
            return CheckResult(
                name="Borrower Required Fields (Non-Null)",
                category="Null Check",
                status=CheckStatus.PASSED,
                message=f"All {len(required_fields)} required fields have no NULLs across {total} rows",
                expected="0 nulls",
                actual="0 nulls",
            )
        else:
            return CheckResult(
                name="Borrower Required Fields (Non-Null)",
                category="Null Check",
                status=CheckStatus.FAILED,
                message=f"Found NULL values in required fields: {null_counts}",
                expected="0 nulls",
                actual=str(null_counts),
                details={"null_counts": null_counts, "total_rows": total},
            )
    except Exception as e:
        return CheckResult(
            name="Borrower Required Fields (Non-Null)",
            category="Null Check",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_loan_account_required_fields(
    spark: SparkSession,
    target_table: str = "loan_warehouse.loan_accounts",
) -> CheckResult:
    """Check that required loan account fields have no NULL values."""
    try:
        df = spark.table(target_table)
        total = df.count()

        required_fields = [
            "account_number",
            "borrower_id",
            "product_code",
            "original_amount",
            "current_balance",
            "interest_rate",
            "term_months",
            "monthly_payment",
            "origination_date",
            "maturity_date",
            "status",
        ]
        null_counts = {}

        for field_name in required_fields:
            null_count = df.filter(F.col(field_name).isNull()).count()
            if null_count > 0:
                null_counts[field_name] = null_count

        if not null_counts:
            return CheckResult(
                name="Loan Account Required Fields (Non-Null)",
                category="Null Check",
                status=CheckStatus.PASSED,
                message=f"All {len(required_fields)} required fields have no NULLs across {total} rows",
                expected="0 nulls",
                actual="0 nulls",
            )
        else:
            return CheckResult(
                name="Loan Account Required Fields (Non-Null)",
                category="Null Check",
                status=CheckStatus.FAILED,
                message=f"Found NULL values in required fields: {null_counts}",
                expected="0 nulls",
                actual=str(null_counts),
                details={"null_counts": null_counts, "total_rows": total},
            )
    except Exception as e:
        return CheckResult(
            name="Loan Account Required Fields (Non-Null)",
            category="Null Check",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_payment_required_fields(
    spark: SparkSession,
    target_table: str = "loan_warehouse.payments",
) -> CheckResult:
    """Check that required payment fields have no NULL values."""
    try:
        df = spark.table(target_table)
        total = df.count()

        required_fields = [
            "loan_account_number",
            "payment_date",
            "total_amount",
            "type",
            "status",
        ]
        null_counts = {}

        for field_name in required_fields:
            null_count = df.filter(F.col(field_name).isNull()).count()
            if null_count > 0:
                null_counts[field_name] = null_count

        if not null_counts:
            return CheckResult(
                name="Payment Required Fields (Non-Null)",
                category="Null Check",
                status=CheckStatus.PASSED,
                message=f"All {len(required_fields)} required fields have no NULLs across {total} rows",
                expected="0 nulls",
                actual="0 nulls",
            )
        else:
            return CheckResult(
                name="Payment Required Fields (Non-Null)",
                category="Null Check",
                status=CheckStatus.FAILED,
                message=f"Found NULL values in required fields: {null_counts}",
                expected="0 nulls",
                actual=str(null_counts),
                details={"null_counts": null_counts, "total_rows": total},
            )
    except Exception as e:
        return CheckResult(
            name="Payment Required Fields (Non-Null)",
            category="Null Check",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


# =============================================================================
# Referential Integrity Checks
# =============================================================================


def check_loan_borrower_integrity(
    spark: SparkSession,
    loans_table: str = "loan_warehouse.loan_accounts",
    borrowers_table: str = "loan_warehouse.borrowers",
) -> CheckResult:
    """
    Check that every loan account references a valid borrower.
    loan_accounts.borrower_id should exist in borrowers.external_id.
    """
    try:
        loans_df = spark.table(loans_table)
        borrowers_df = spark.table(borrowers_table)

        # Get distinct borrower IDs referenced in loans
        loan_borrower_ids = loans_df.select("borrower_id").distinct()

        # Get valid borrower external IDs
        valid_borrower_ids = borrowers_df.select(
            F.col("external_id").alias("borrower_id")
        ).distinct()

        # Find orphan references
        orphans = loan_borrower_ids.join(valid_borrower_ids, "borrower_id", "left_anti")
        orphan_count = orphans.count()

        if orphan_count == 0:
            return CheckResult(
                name="Loan-to-Borrower Referential Integrity",
                category="Referential Integrity",
                status=CheckStatus.PASSED,
                message="All loan accounts reference valid borrowers",
                expected="0 orphan references",
                actual="0 orphan references",
            )
        else:
            orphan_ids = [row["borrower_id"] for row in orphans.collect()]
            return CheckResult(
                name="Loan-to-Borrower Referential Integrity",
                category="Referential Integrity",
                status=CheckStatus.FAILED,
                message=f"Found {orphan_count} loan accounts referencing non-existent borrowers",
                expected="0 orphan references",
                actual=f"{orphan_count} orphan references",
                details={"orphan_borrower_ids": orphan_ids[:20]},
            )
    except Exception as e:
        return CheckResult(
            name="Loan-to-Borrower Referential Integrity",
            category="Referential Integrity",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_loan_product_integrity(
    spark: SparkSession,
    loans_table: str = "loan_warehouse.loan_accounts",
    products_table: str = "loan_warehouse.loan_products",
) -> CheckResult:
    """
    Check that every loan account references a valid product.
    loan_accounts.product_code should exist in loan_products.code.
    """
    try:
        loans_df = spark.table(loans_table)
        products_df = spark.table(products_table)

        # Get distinct product codes referenced in loans
        loan_product_codes = loans_df.select(
            F.col("product_code").alias("code")
        ).distinct()

        # Get valid product codes
        valid_product_codes = products_df.select("code").distinct()

        # Find orphan references
        orphans = loan_product_codes.join(valid_product_codes, "code", "left_anti")
        orphan_count = orphans.count()

        if orphan_count == 0:
            return CheckResult(
                name="Loan-to-Product Referential Integrity",
                category="Referential Integrity",
                status=CheckStatus.PASSED,
                message="All loan accounts reference valid products",
                expected="0 orphan references",
                actual="0 orphan references",
            )
        else:
            orphan_codes = [row["code"] for row in orphans.collect()]
            return CheckResult(
                name="Loan-to-Product Referential Integrity",
                category="Referential Integrity",
                status=CheckStatus.FAILED,
                message=f"Found {orphan_count} loan accounts referencing non-existent products",
                expected="0 orphan references",
                actual=f"{orphan_count} orphan references",
                details={"orphan_product_codes": orphan_codes[:20]},
            )
    except Exception as e:
        return CheckResult(
            name="Loan-to-Product Referential Integrity",
            category="Referential Integrity",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_payment_loan_integrity(
    spark: SparkSession,
    payments_table: str = "loan_warehouse.payments",
    loans_table: str = "loan_warehouse.loan_accounts",
) -> CheckResult:
    """
    Check that every payment references a valid loan account.
    payments.loan_account_number should exist in loan_accounts.account_number.
    """
    try:
        payments_df = spark.table(payments_table)
        loans_df = spark.table(loans_table)

        # Get distinct loan account numbers referenced in payments
        payment_loan_ids = payments_df.select(
            F.col("loan_account_number").alias("account_number")
        ).distinct()

        # Get valid account numbers
        valid_loan_ids = loans_df.select("account_number").distinct()

        # Find orphan references
        orphans = payment_loan_ids.join(valid_loan_ids, "account_number", "left_anti")
        orphan_count = orphans.count()

        if orphan_count == 0:
            return CheckResult(
                name="Payment-to-Loan Referential Integrity",
                category="Referential Integrity",
                status=CheckStatus.PASSED,
                message="All payments reference valid loan accounts",
                expected="0 orphan references",
                actual="0 orphan references",
            )
        else:
            orphan_ids = [row["account_number"] for row in orphans.collect()]
            return CheckResult(
                name="Payment-to-Loan Referential Integrity",
                category="Referential Integrity",
                status=CheckStatus.FAILED,
                message=f"Found {orphan_count} payments referencing non-existent loan accounts",
                expected="0 orphan references",
                actual=f"{orphan_count} orphan references",
                details={"orphan_account_numbers": orphan_ids[:20]},
            )
    except Exception as e:
        return CheckResult(
            name="Payment-to-Loan Referential Integrity",
            category="Referential Integrity",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


# =============================================================================
# Business Rule Validation
# =============================================================================


def check_active_loan_positive_balance(
    spark: SparkSession,
    target_table: str = "loan_warehouse.loan_accounts",
) -> CheckResult:
    """
    Business rule: Active loans must have a positive current balance.
    Loans with status='ACTIVE' should have current_balance > 0.
    """
    try:
        df = spark.table(target_table)
        active_loans = df.filter(F.col("status") == "ACTIVE")
        total_active = active_loans.count()

        violations = active_loans.filter(F.col("current_balance") <= 0)
        violation_count = violations.count()

        if violation_count == 0:
            return CheckResult(
                name="Active Loans: Positive Balance",
                category="Business Rule",
                status=CheckStatus.PASSED,
                message=f"All {total_active} active loans have positive balance",
                expected="0 violations",
                actual="0 violations",
            )
        else:
            violation_accounts = [
                row["account_number"] for row in violations.select("account_number").collect()
            ]
            return CheckResult(
                name="Active Loans: Positive Balance",
                category="Business Rule",
                status=CheckStatus.FAILED,
                message=f"{violation_count} active loans have zero or negative balance",
                expected="0 violations",
                actual=f"{violation_count} violations",
                details={
                    "total_active_loans": total_active,
                    "violation_accounts": violation_accounts[:20],
                },
            )
    except Exception as e:
        return CheckResult(
            name="Active Loans: Positive Balance",
            category="Business Rule",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_closed_loan_has_closed_date(
    spark: SparkSession,
    target_table: str = "loan_warehouse.loan_accounts",
) -> CheckResult:
    """
    Business rule: Closed loans should have a maturity_date that is in the past
    or the current_balance should be 0 (paid off).
    """
    try:
        df = spark.table(target_table)
        closed_loans = df.filter(F.col("status") == "CLOSED")
        total_closed = closed_loans.count()

        if total_closed == 0:
            return CheckResult(
                name="Closed Loans: Balance Zero or Past Maturity",
                category="Business Rule",
                status=CheckStatus.PASSED,
                message="No closed loans to validate (0 records with CLOSED status)",
                expected="N/A",
                actual="N/A",
            )

        # Closed loans should have balance == 0 or maturity_date in the past
        violations = closed_loans.filter(
            (F.col("current_balance") > 0) & (F.col("maturity_date") > F.current_date())
        )
        violation_count = violations.count()

        if violation_count == 0:
            return CheckResult(
                name="Closed Loans: Balance Zero or Past Maturity",
                category="Business Rule",
                status=CheckStatus.PASSED,
                message=f"All {total_closed} closed loans have zero balance or past maturity date",
                expected="0 violations",
                actual="0 violations",
            )
        else:
            violation_accounts = [
                row["account_number"] for row in violations.select("account_number").collect()
            ]
            return CheckResult(
                name="Closed Loans: Balance Zero or Past Maturity",
                category="Business Rule",
                status=CheckStatus.FAILED,
                message=f"{violation_count} closed loans still have positive balance with future maturity",
                expected="0 violations",
                actual=f"{violation_count} violations",
                details={
                    "total_closed_loans": total_closed,
                    "violation_accounts": violation_accounts[:20],
                },
            )
    except Exception as e:
        return CheckResult(
            name="Closed Loans: Balance Zero or Past Maturity",
            category="Business Rule",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_payment_amount_components(
    spark: SparkSession,
    target_table: str = "loan_warehouse.payments",
) -> CheckResult:
    """
    Business rule: For posted payments, the sum of principal + interest + escrow + late_fee
    should approximately equal the total_amount (within rounding tolerance of $0.02).
    """
    try:
        df = spark.table(target_table)
        posted = df.filter(F.col("status") == "POSTED")
        total_posted = posted.count()

        if total_posted == 0:
            return CheckResult(
                name="Payment Amount Component Sum",
                category="Business Rule",
                status=CheckStatus.PASSED,
                message="No posted payments to validate",
                expected="N/A",
                actual="N/A",
            )

        # Calculate component sum and compare to total
        tolerance = 0.02
        checked = posted.withColumn(
            "component_sum",
            F.coalesce(F.col("principal_amount"), F.lit(0))
            + F.coalesce(F.col("interest_amount"), F.lit(0))
            + F.coalesce(F.col("escrow_amount"), F.lit(0))
            + F.coalesce(F.col("late_fee"), F.lit(0)),
        ).withColumn(
            "difference",
            F.abs(F.col("total_amount") - F.col("component_sum")),
        )

        violations = checked.filter(F.col("difference") > tolerance)
        violation_count = violations.count()

        if violation_count == 0:
            return CheckResult(
                name="Payment Amount Component Sum",
                category="Business Rule",
                status=CheckStatus.PASSED,
                message=f"All {total_posted} posted payments have consistent component sums (tolerance=${tolerance})",
                expected="0 violations",
                actual="0 violations",
            )
        else:
            sample_violations = violations.select(
                "legacy_sequence_id", "total_amount", "component_sum", "difference"
            ).limit(5).collect()
            return CheckResult(
                name="Payment Amount Component Sum",
                category="Business Rule",
                status=CheckStatus.WARNING,
                message=f"{violation_count} posted payments have component sum mismatch > ${tolerance}",
                expected="0 violations",
                actual=f"{violation_count} violations",
                details={
                    "total_posted_payments": total_posted,
                    "tolerance": tolerance,
                    "sample_violations": [row.asDict() for row in sample_violations],
                },
            )
    except Exception as e:
        return CheckResult(
            name="Payment Amount Component Sum",
            category="Business Rule",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_credit_score_range(
    spark: SparkSession,
    target_table: str = "loan_warehouse.borrowers",
) -> CheckResult:
    """
    Business rule: Credit scores should be in valid FICO range (300-850).
    """
    try:
        df = spark.table(target_table)
        with_score = df.filter(F.col("credit_score").isNotNull())
        total_with_score = with_score.count()

        violations = with_score.filter(
            (F.col("credit_score") < 300) | (F.col("credit_score") > 850)
        )
        violation_count = violations.count()

        if violation_count == 0:
            return CheckResult(
                name="Borrower Credit Score Range (300-850)",
                category="Business Rule",
                status=CheckStatus.PASSED,
                message=f"All {total_with_score} borrowers with credit scores are in valid range",
                expected="0 out-of-range scores",
                actual="0 out-of-range scores",
            )
        else:
            return CheckResult(
                name="Borrower Credit Score Range (300-850)",
                category="Business Rule",
                status=CheckStatus.FAILED,
                message=f"{violation_count} borrowers have credit scores outside 300-850 range",
                expected="0 out-of-range scores",
                actual=f"{violation_count} out-of-range scores",
                details={"total_with_score": total_with_score},
            )
    except Exception as e:
        return CheckResult(
            name="Borrower Credit Score Range (300-850)",
            category="Business Rule",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )


def check_loan_status_values(
    spark: SparkSession,
    target_table: str = "loan_warehouse.loan_accounts",
) -> CheckResult:
    """
    Business rule: Loan status should only contain expanded valid values.
    Valid: ACTIVE, CLOSED, DEFAULT, FORBEARANCE
    """
    try:
        df = spark.table(target_table)
        valid_statuses = {"ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE"}

        distinct_statuses = [
            row["status"] for row in df.select("status").distinct().collect()
        ]

        invalid = [s for s in distinct_statuses if s not in valid_statuses]

        if not invalid:
            return CheckResult(
                name="Loan Status Values Valid",
                category="Business Rule",
                status=CheckStatus.PASSED,
                message=f"All loan statuses are valid: {distinct_statuses}",
                expected=str(valid_statuses),
                actual=str(distinct_statuses),
            )
        else:
            return CheckResult(
                name="Loan Status Values Valid",
                category="Business Rule",
                status=CheckStatus.FAILED,
                message=f"Found invalid/unmapped loan statuses: {invalid}",
                expected=str(valid_statuses),
                actual=str(distinct_statuses),
                details={"invalid_statuses": invalid},
            )
    except Exception as e:
        return CheckResult(
            name="Loan Status Values Valid",
            category="Business Rule",
            status=CheckStatus.SKIPPED,
            message=f"Check could not be executed: {e}",
        )
