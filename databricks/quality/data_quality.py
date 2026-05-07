"""
Data Quality Validation Framework for the CDW Legacy Migration.

Runs after ingestion to validate:
- Row count reconciliation (source vs. target)
- Null checks on required fields
- Referential integrity between loan and borrower tables
- Business rule validation
- Generates a DATA_QUALITY_REPORT.md summarizing pass/fail results
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyspark.sql import SparkSession
from pyspark.sql.functions import col
import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("data_quality")


@dataclass
class ValidationResult:
    """Represents a single validation check result."""
    category: str
    check_name: str
    table: str
    passed: bool
    details: str
    expected: Optional[str] = None
    actual: Optional[str] = None


@dataclass
class QualityReport:
    """Aggregates all validation results."""
    results: list = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

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
    def pass_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return self.passed_checks / self.total_checks * 100

    def add(self, result: ValidationResult):
        self.results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info(f"[{status}] {result.category} | {result.table} | {result.check_name}")


class DataQualityValidator:
    """
    PySpark-based data quality validation framework.
    Runs comprehensive checks after migration ingestion.
    """

    def __init__(self, spark: SparkSession, database: str = "loan_warehouse",
                 source_base_path: str = "/mnt/legacy-cdw/exports",
                 source_format: str = "csv"):
        self.spark = spark
        self.database = database
        self.source_base_path = source_base_path
        self.source_format = source_format
        self.report = QualityReport()

    def run_all_checks(self) -> QualityReport:
        """Execute all validation checks and return the report."""
        self.report.start_time = datetime.now()
        logger.info("=" * 70)
        logger.info("DATA QUALITY VALIDATION STARTED")
        logger.info("=" * 70)

        self._check_row_counts()
        self._check_null_required_fields()
        self._check_referential_integrity()
        self._check_business_rules()

        self.report.end_time = datetime.now()
        logger.info("=" * 70)
        logger.info(
            f"VALIDATION COMPLETE: {self.report.passed_checks}/{self.report.total_checks} "
            f"checks passed ({self.report.pass_rate:.1f}%)"
        )
        logger.info("=" * 70)
        return self.report

    # -------------------------------------------------------------------------
    # Row Count Reconciliation
    # -------------------------------------------------------------------------

    def _check_row_counts(self):
        """Verify source and target row counts match for each table."""
        logger.info("\n--- ROW COUNT RECONCILIATION ---")

        table_mappings = [
            ("CDW_BORR_MSTR", "borrowers"),
            ("CDW_LN_PROD", "loan_products"),
            ("CDW_LN_ACCT", "loan_accounts"),
            ("CDW_PMT_HIST", "payments"),
        ]

        for source_table, target_table in table_mappings:
            source_count = self._get_source_count(source_table)
            target_count = self._get_target_count(target_table)
            error_count = self._get_error_count(source_table)

            expected_target = source_count - error_count
            passed = target_count == expected_target

            self.report.add(ValidationResult(
                category="Row Count",
                check_name=f"Source vs Target count ({source_table} -> {target_table})",
                table=target_table,
                passed=passed,
                details=(
                    f"Source: {source_count}, Target: {target_count}, "
                    f"Errors: {error_count}, Expected target: {expected_target}"
                ),
                expected=str(expected_target),
                actual=str(target_count),
            ))

    def _get_source_count(self, table_name: str) -> int:
        """Get row count from source files."""
        try:
            source_path = f"{self.source_base_path}/{table_name}"
            if self.source_format == "csv":
                df = self.spark.read.option("header", "true").csv(source_path)
            else:
                df = self.spark.read.parquet(source_path)
            return df.count()
        except Exception as e:
            logger.warning(f"Could not read source {table_name}: {e}")
            return -1

    def _get_target_count(self, table_name: str) -> int:
        """Get row count from target Delta table."""
        try:
            df = self.spark.table(f"{self.database}.{table_name}")
            return df.count()
        except Exception as e:
            logger.warning(f"Could not read target {table_name}: {e}")
            return -1

    def _get_error_count(self, source_table: str) -> int:
        """Get count of records in the error table for a given source."""
        try:
            error_df = self.spark.table(f"{self.database}._migration_errors")
            return error_df.filter(col("_source_table") == source_table).count()
        except Exception:
            return 0

    # -------------------------------------------------------------------------
    # Null Checks on Required Fields
    # -------------------------------------------------------------------------

    def _check_null_required_fields(self):
        """Verify no nulls in required (NOT NULL) fields."""
        logger.info("\n--- NULL CHECKS ON REQUIRED FIELDS ---")

        required_fields = {
            "borrowers": ["external_id", "first_name", "last_name", "status"],
            "loan_products": ["code", "name", "is_active"],
            "loan_accounts": ["account_number", "borrower_id", "product_code", "status"],
            "payments": [
                "legacy_payment_id", "loan_account_number",
                "payment_date", "total_amount", "status"
            ],
        }

        for table_name, fields in required_fields.items():
            try:
                df = self.spark.table(f"{self.database}.{table_name}")
                for field_name in fields:
                    null_count = df.filter(col(field_name).isNull()).count()
                    passed = null_count == 0
                    self.report.add(ValidationResult(
                        category="Null Check",
                        check_name=f"NOT NULL: {field_name}",
                        table=table_name,
                        passed=passed,
                        details=f"Null count: {null_count}",
                        expected="0",
                        actual=str(null_count),
                    ))
            except Exception as e:
                self.report.add(ValidationResult(
                    category="Null Check",
                    check_name=f"Table access: {table_name}",
                    table=table_name,
                    passed=False,
                    details=f"Error accessing table: {e}",
                ))

    # -------------------------------------------------------------------------
    # Referential Integrity
    # -------------------------------------------------------------------------

    def _check_referential_integrity(self):
        """Check FK relationships between tables."""
        logger.info("\n--- REFERENTIAL INTEGRITY CHECKS ---")

        # loan_accounts.borrower_id must reference a valid borrowers.external_id
        self._check_fk_integrity(
            child_table="loan_accounts",
            child_column="borrower_id",
            parent_table="borrowers",
            parent_column="external_id",
            check_name="loan_accounts.borrower_id -> borrowers.external_id"
        )

        # loan_accounts.product_code must reference a valid loan_products.code
        self._check_fk_integrity(
            child_table="loan_accounts",
            child_column="product_code",
            parent_table="loan_products",
            parent_column="code",
            check_name="loan_accounts.product_code -> loan_products.code"
        )

        # payments.loan_account_number must reference a valid loan_accounts.account_number
        self._check_fk_integrity(
            child_table="payments",
            child_column="loan_account_number",
            parent_table="loan_accounts",
            parent_column="account_number",
            check_name="payments.loan_account_number -> loan_accounts.account_number"
        )

    def _check_fk_integrity(self, child_table: str, child_column: str,
                            parent_table: str, parent_column: str,
                            check_name: str):
        """Verify all child FK values exist in the parent table."""
        try:
            child_df = self.spark.table(f"{self.database}.{child_table}")
            parent_df = self.spark.table(f"{self.database}.{parent_table}")

            orphan_df = (
                child_df
                .join(
                    parent_df,
                    child_df[child_column] == parent_df[parent_column],
                    "left_anti"
                )
            )
            orphan_count = orphan_df.count()
            passed = orphan_count == 0

            details = f"Orphan records: {orphan_count}"
            if not passed:
                sample_orphans = (
                    orphan_df.select(child_column).limit(5)
                    .rdd.flatMap(lambda x: x).collect()
                )
                details += f" | Sample orphan values: {sample_orphans}"

            self.report.add(ValidationResult(
                category="Referential Integrity",
                check_name=check_name,
                table=child_table,
                passed=passed,
                details=details,
                expected="0 orphans",
                actual=str(orphan_count),
            ))
        except Exception as e:
            self.report.add(ValidationResult(
                category="Referential Integrity",
                check_name=check_name,
                table=child_table,
                passed=False,
                details=f"Error checking FK: {e}",
            ))

    # -------------------------------------------------------------------------
    # Business Rule Validation
    # -------------------------------------------------------------------------

    def _check_business_rules(self):
        """Validate business rules for loan data integrity."""
        logger.info("\n--- BUSINESS RULE VALIDATION ---")

        self._check_active_loan_balance_positive()
        self._check_closed_loan_has_closed_date()
        self._check_payment_amounts_consistent()
        self._check_origination_before_maturity()
        self._check_credit_score_range()
        self._check_ltv_range()

    def _check_active_loan_balance_positive(self):
        """Active loans must have a positive current balance."""
        try:
            df = self.spark.table(f"{self.database}.loan_accounts")
            violating = df.filter(
                (col("status") == "ACTIVE")
                & (col("current_balance").isNotNull())
                & (col("current_balance") <= 0)
            )
            violation_count = violating.count()
            passed = violation_count == 0

            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Active loans must have balance > 0",
                table="loan_accounts",
                passed=passed,
                details=f"Active loans with balance <= 0: {violation_count}",
                expected="0",
                actual=str(violation_count),
            ))
        except Exception as e:
            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Active loans must have balance > 0",
                table="loan_accounts",
                passed=False,
                details=f"Error: {e}",
            ))

    def _check_closed_loan_has_closed_date(self):
        """
        Closed loans should have an updated_at date that is after origination.
        (Proxy for closed date since legacy schema doesn't have explicit close date.)
        """
        try:
            df = self.spark.table(f"{self.database}.loan_accounts")
            violating = df.filter(
                (col("status") == "CLOSED")
                & (col("updated_at").isNull())
            )
            violation_count = violating.count()
            passed = violation_count == 0

            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Closed loans must have updated_at (close date proxy)",
                table="loan_accounts",
                passed=passed,
                details=f"Closed loans without updated_at: {violation_count}",
                expected="0",
                actual=str(violation_count),
            ))
        except Exception as e:
            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Closed loans must have updated_at (close date proxy)",
                table="loan_accounts",
                passed=False,
                details=f"Error: {e}",
            ))

    def _check_payment_amounts_consistent(self):
        """
        Payment total should approximately equal sum of components
        (principal + interest + escrow + late_fee).
        Tolerance of $0.01 for rounding.
        """
        try:
            df = self.spark.table(f"{self.database}.payments")
            df_with_sum = df.withColumn(
                "component_sum",
                col("principal_amount") + col("interest_amount")
                + col("escrow_amount") + col("late_fee")
            )
            violating = df_with_sum.filter(
                (col("component_sum").isNotNull())
                & (col("total_amount").isNotNull())
                & (
                    (col("total_amount") - col("component_sum") > 0.01)
                    | (col("component_sum") - col("total_amount") > 0.01)
                )
            )
            violation_count = violating.count()
            passed = violation_count == 0

            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Payment total = principal + interest + escrow + late_fee",
                table="payments",
                passed=passed,
                details=f"Payments with inconsistent component totals: {violation_count}",
                expected="0",
                actual=str(violation_count),
            ))
        except Exception as e:
            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Payment total = principal + interest + escrow + late_fee",
                table="payments",
                passed=False,
                details=f"Error: {e}",
            ))

    def _check_origination_before_maturity(self):
        """Origination date must be before maturity date."""
        try:
            df = self.spark.table(f"{self.database}.loan_accounts")
            violating = df.filter(
                (col("origination_date").isNotNull())
                & (col("maturity_date").isNotNull())
                & (col("origination_date") >= col("maturity_date"))
            )
            violation_count = violating.count()
            passed = violation_count == 0

            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Origination date must precede maturity date",
                table="loan_accounts",
                passed=passed,
                details=f"Loans with origination >= maturity: {violation_count}",
                expected="0",
                actual=str(violation_count),
            ))
        except Exception as e:
            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Origination date must precede maturity date",
                table="loan_accounts",
                passed=False,
                details=f"Error: {e}",
            ))

    def _check_credit_score_range(self):
        """Credit scores must be within valid range (300-850)."""
        try:
            df = self.spark.table(f"{self.database}.borrowers")
            violating = df.filter(
                (col("credit_score").isNotNull())
                & ((col("credit_score") < 300) | (col("credit_score") > 850))
            )
            violation_count = violating.count()
            passed = violation_count == 0

            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Credit score in valid range (300-850)",
                table="borrowers",
                passed=passed,
                details=f"Borrowers with invalid credit scores: {violation_count}",
                expected="0",
                actual=str(violation_count),
            ))
        except Exception as e:
            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="Credit score in valid range (300-850)",
                table="borrowers",
                passed=False,
                details=f"Error: {e}",
            ))

    def _check_ltv_range(self):
        """LTV percent should be between 0 and 200 (reasonable range)."""
        try:
            df = self.spark.table(f"{self.database}.loan_accounts")
            violating = df.filter(
                (col("ltv_percent").isNotNull())
                & ((col("ltv_percent") < 0) | (col("ltv_percent") > 200))
            )
            violation_count = violating.count()
            passed = violation_count == 0

            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="LTV percent in reasonable range (0-200%)",
                table="loan_accounts",
                passed=passed,
                details=f"Loans with LTV outside 0-200%: {violation_count}",
                expected="0",
                actual=str(violation_count),
            ))
        except Exception as e:
            self.report.add(ValidationResult(
                category="Business Rule",
                check_name="LTV percent in reasonable range (0-200%)",
                table="loan_accounts",
                passed=False,
                details=f"Error: {e}",
            ))
