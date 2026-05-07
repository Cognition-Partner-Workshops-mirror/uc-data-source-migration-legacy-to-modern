# Databricks notebook source
# MAGIC %md
# MAGIC # Post-Ingestion Data Quality Framework
# MAGIC
# MAGIC Runs after all ingestion notebooks complete. Validates the migrated data against:
# MAGIC 1. Row count reconciliation (source vs target)
# MAGIC 2. Null checks on required fields
# MAGIC 3. Referential integrity between tables
# MAGIC 4. Business rule validation
# MAGIC 5. Value range and constraint validation
# MAGIC
# MAGIC Generates a `DATA_QUALITY_REPORT.md` summarizing all check results.

# COMMAND ----------

from pyspark.sql import SparkSession, functions as F
from pyspark.sql import DataFrame
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Quality Check Framework

# COMMAND ----------

@dataclass
class CheckResult:
    category: str
    check_name: str
    table: str
    passed: bool
    message: str
    severity: str = "HIGH"
    detail: Optional[str] = None


class DataQualityRunner:
    """Runs a suite of data quality checks and collects results."""

    def __init__(self, spark_session):
        self.spark = spark_session
        self.results: list[CheckResult] = []

    def add_result(self, result: CheckResult):
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] [{result.severity}] {result.category} | {result.check_name}: {result.message}")
        self.results.append(result)

    # -----------------------------------------------------------------
    # 1. Row Count Reconciliation
    # -----------------------------------------------------------------

    def check_row_count(self, source_path: str, source_format: str,
                        target_table: str, table_label: str):
        """Compare source file row count to target Delta table row count."""
        try:
            source_df = self.spark.read.format(source_format).option("header", "true").load(source_path)
            source_count = source_df.count()
        except Exception as e:
            self.add_result(CheckResult(
                category="Row Count",
                check_name=f"{table_label} source readable",
                table=table_label,
                passed=False,
                message=f"Cannot read source: {e}",
                severity="CRITICAL",
            ))
            return

        target_count = self.spark.table(target_table).count()
        quarantine_table = f"loan_warehouse._quarantine_{table_label.lower().replace(' ', '_')}"
        try:
            quarantine_count = self.spark.table(quarantine_table).count()
        except Exception:
            quarantine_count = 0

        accounted = target_count + quarantine_count
        passed = source_count == accounted

        self.add_result(CheckResult(
            category="Row Count",
            check_name=f"{table_label} reconciliation",
            table=table_label,
            passed=passed,
            message=f"Source={source_count}, Target={target_count}, Quarantine={quarantine_count}, Accounted={accounted}",
            severity="CRITICAL" if not passed else "INFO",
            detail=f"Missing {source_count - accounted} rows" if not passed else None,
        ))

    # -----------------------------------------------------------------
    # 2. Null Checks on Required Fields
    # -----------------------------------------------------------------

    def check_nulls(self, table_name: str, table_label: str,
                    required_columns: list[str]):
        """Check that required columns have no null values."""
        df = self.spark.table(table_name)
        for col_name in required_columns:
            null_count = df.filter(F.col(col_name).isNull()).count()
            passed = null_count == 0
            self.add_result(CheckResult(
                category="Null Check",
                check_name=f"{table_label}.{col_name} NOT NULL",
                table=table_label,
                passed=passed,
                message=f"{null_count} null values" if not passed else "No nulls",
                severity="HIGH" if not passed else "INFO",
            ))

    # -----------------------------------------------------------------
    # 3. Referential Integrity
    # -----------------------------------------------------------------

    def check_referential_integrity(self, child_table: str, child_col: str,
                                     parent_table: str, parent_col: str,
                                     label: str):
        """Check that all child FK values exist in the parent table."""
        child_df = self.spark.table(child_table).select(F.col(child_col).alias("fk_val"))
        parent_df = self.spark.table(parent_table).select(F.col(parent_col).alias("pk_val"))

        orphans = child_df.join(parent_df, child_df["fk_val"] == parent_df["pk_val"], "left_anti")
        orphan_count = orphans.count()
        passed = orphan_count == 0

        self.add_result(CheckResult(
            category="Referential Integrity",
            check_name=label,
            table=child_table.split(".")[-1],
            passed=passed,
            message=f"{orphan_count} orphaned records" if not passed else "All FKs valid",
            severity="CRITICAL" if not passed else "INFO",
        ))

    # -----------------------------------------------------------------
    # 4. Business Rule Validation
    # -----------------------------------------------------------------

    def check_business_rule(self, table_name: str, table_label: str,
                            rule_name: str, condition: str,
                            severity: str = "HIGH"):
        """Check a SQL WHERE condition against a table. Rows matching the condition are violations."""
        df = self.spark.table(table_name)
        violations = df.filter(condition).count()
        total = df.count()
        passed = violations == 0

        self.add_result(CheckResult(
            category="Business Rule",
            check_name=rule_name,
            table=table_label,
            passed=passed,
            message=f"{violations}/{total} rows violate rule" if not passed else f"All {total} rows pass",
            severity=severity if not passed else "INFO",
        ))

    # -----------------------------------------------------------------
    # 5. Value Range Checks
    # -----------------------------------------------------------------

    def check_value_range(self, table_name: str, table_label: str,
                          col_name: str, min_val=None, max_val=None,
                          allowed_values: list[str] = None):
        """Check that column values are within expected range or set."""
        df = self.spark.table(table_name)

        if allowed_values is not None:
            violations = df.filter(
                ~F.col(col_name).isin(allowed_values) & F.col(col_name).isNotNull()
            ).count()
            check_name = f"{table_label}.{col_name} in {allowed_values}"
        else:
            conditions = []
            if min_val is not None:
                conditions.append(F.col(col_name) < min_val)
            if max_val is not None:
                conditions.append(F.col(col_name) > max_val)
            combined = conditions[0]
            for c in conditions[1:]:
                combined = combined | c
            violations = df.filter(combined & F.col(col_name).isNotNull()).count()
            check_name = f"{table_label}.{col_name} range [{min_val}, {max_val}]"

        passed = violations == 0
        self.add_result(CheckResult(
            category="Value Range",
            check_name=check_name,
            table=table_label,
            passed=passed,
            message=f"{violations} values out of range" if not passed else "All values in range",
            severity="MEDIUM" if not passed else "INFO",
        ))

    # -----------------------------------------------------------------
    # 6. Uniqueness Checks
    # -----------------------------------------------------------------

    def check_uniqueness(self, table_name: str, table_label: str,
                         col_name: str):
        """Check that a column has no duplicate values."""
        df = self.spark.table(table_name)
        total = df.count()
        distinct = df.select(col_name).distinct().count()
        duplicates = total - distinct
        passed = duplicates == 0

        self.add_result(CheckResult(
            category="Uniqueness",
            check_name=f"{table_label}.{col_name} unique",
            table=table_label,
            passed=passed,
            message=f"{duplicates} duplicate values" if not passed else "All values unique",
            severity="HIGH" if not passed else "INFO",
        ))

    # -----------------------------------------------------------------
    # Report Generation
    # -----------------------------------------------------------------

    def generate_report(self, output_path: str = "/dbfs/mnt/reports/DATA_QUALITY_REPORT.md"):
        """Generate a markdown summary of all check results."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        lines = [
            "# Data Quality Report",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Total Checks:** {total}",
            f"**Passed:** {passed}",
            f"**Failed:** {failed}",
            "",
            "---",
            "",
            "## Summary Table",
            "",
            "| # | Status | Severity | Category | Check | Table | Message |",
            "|---|--------|----------|----------|-------|-------|---------|",
        ]

        for i, r in enumerate(self.results, 1):
            status = "PASS" if r.passed else "**FAIL**"
            severity = r.severity if not r.passed else "-"
            lines.append(
                f"| {i} | {status} | {severity} | {r.category} | {r.check_name} | {r.table} | {r.message} |"
            )

        # Failed checks detail section
        failed_results = [r for r in self.results if not r.passed]
        if failed_results:
            lines.extend([
                "",
                "---",
                "",
                "## Failed Checks Detail",
                "",
            ])
            for r in failed_results:
                lines.append(f"### [{r.severity}] {r.check_name}")
                lines.append(f"- **Table:** {r.table}")
                lines.append(f"- **Category:** {r.category}")
                lines.append(f"- **Message:** {r.message}")
                if r.detail:
                    lines.append(f"- **Detail:** {r.detail}")
                lines.append("")

        # Category summary
        categories = {}
        for r in self.results:
            cat = r.category
            if cat not in categories:
                categories[cat] = {"passed": 0, "failed": 0}
            if r.passed:
                categories[cat]["passed"] += 1
            else:
                categories[cat]["failed"] += 1

        lines.extend([
            "---",
            "",
            "## Category Summary",
            "",
            "| Category | Passed | Failed | Total |",
            "|----------|--------|--------|-------|",
        ])
        for cat, counts in categories.items():
            lines.append(
                f"| {cat} | {counts['passed']} | {counts['failed']} | {counts['passed'] + counts['failed']} |"
            )

        report_content = "\n".join(lines)

        # Write to DBFS
        with open(output_path, "w") as f:
            f.write(report_content)
        print(f"[REPORT] Written to {output_path}")

        return report_content


# COMMAND ----------

# MAGIC %md
# MAGIC ## Run All Checks

# COMMAND ----------

runner = DataQualityRunner(spark)

# -----------------------------------------------------------------
# Row Count Reconciliation
# -----------------------------------------------------------------
SOURCE_BASE = "dbfs:/mnt/legacy-cdw"
SOURCE_FORMAT = "csv"

runner.check_row_count(f"{SOURCE_BASE}/CDW_BORR_MSTR/", SOURCE_FORMAT, "loan_warehouse.borrowers", "borrowers")
runner.check_row_count(f"{SOURCE_BASE}/CDW_LN_PROD/", SOURCE_FORMAT, "loan_warehouse.loan_products", "loan_products")
runner.check_row_count(f"{SOURCE_BASE}/CDW_LN_ACCT/", SOURCE_FORMAT, "loan_warehouse.loan_accounts", "loan_accounts")
runner.check_row_count(f"{SOURCE_BASE}/CDW_PMT_HIST/", SOURCE_FORMAT, "loan_warehouse.payments", "payments")

# -----------------------------------------------------------------
# Null Checks on Required Fields
# -----------------------------------------------------------------
runner.check_nulls("loan_warehouse.borrowers", "borrowers",
                   ["external_id", "first_name", "last_name"])

runner.check_nulls("loan_warehouse.loan_products", "loan_products",
                   ["code", "name", "type", "term_months", "rate_type"])

runner.check_nulls("loan_warehouse.loan_accounts", "loan_accounts",
                   ["account_number", "borrower_id", "product_id",
                    "original_amount", "current_balance", "interest_rate",
                    "term_months", "monthly_payment", "origination_date", "maturity_date"])

runner.check_nulls("loan_warehouse.payments", "payments",
                   ["loan_account_id", "payment_date", "total_amount", "type", "status"])

# -----------------------------------------------------------------
# Referential Integrity
# -----------------------------------------------------------------
runner.check_referential_integrity(
    "loan_warehouse.loan_accounts", "borrower_id",
    "loan_warehouse.borrowers", "id",
    "loan_accounts.borrower_id -> borrowers.id"
)

runner.check_referential_integrity(
    "loan_warehouse.loan_accounts", "product_id",
    "loan_warehouse.loan_products", "id",
    "loan_accounts.product_id -> loan_products.id"
)

runner.check_referential_integrity(
    "loan_warehouse.payments", "loan_account_id",
    "loan_warehouse.loan_accounts", "id",
    "payments.loan_account_id -> loan_accounts.id"
)

# -----------------------------------------------------------------
# Business Rule Validation
# -----------------------------------------------------------------

# Active loans must have positive balance
runner.check_business_rule(
    "loan_warehouse.loan_accounts", "loan_accounts",
    "Active loans must have positive balance",
    "status = 'ACTIVE' AND current_balance <= 0",
    severity="HIGH",
)

# Origination date must be before maturity date
runner.check_business_rule(
    "loan_warehouse.loan_accounts", "loan_accounts",
    "Origination date before maturity date",
    "origination_date >= maturity_date",
    severity="HIGH",
)

# Monthly payment must be positive for active loans
runner.check_business_rule(
    "loan_warehouse.loan_accounts", "loan_accounts",
    "Active loans must have positive monthly payment",
    "status = 'ACTIVE' AND monthly_payment <= 0",
    severity="HIGH",
)

# Closed loans should have zero or near-zero balance
runner.check_business_rule(
    "loan_warehouse.loan_accounts", "loan_accounts",
    "Closed loans should have balance <= 0.01",
    "status = 'CLOSED' AND current_balance > 0.01",
    severity="MEDIUM",
)

# Delinquency days >= 90 should have DEFAULT status
runner.check_business_rule(
    "loan_warehouse.loan_accounts", "loan_accounts",
    "90+ delinquency days should be DEFAULT status",
    "delinquency_days >= 90 AND status != 'DEFAULT'",
    severity="MEDIUM",
)

# Payment total must be positive
runner.check_business_rule(
    "loan_warehouse.payments", "payments",
    "Payment total must be non-negative",
    "total_amount < 0",
    severity="HIGH",
)

# -----------------------------------------------------------------
# Value Range Checks
# -----------------------------------------------------------------
runner.check_value_range("loan_warehouse.borrowers", "borrowers",
                         "credit_score", min_val=300, max_val=850)

runner.check_value_range("loan_warehouse.loan_accounts", "loan_accounts",
                         "interest_rate", min_val=0, max_val=30)

runner.check_value_range("loan_warehouse.loan_accounts", "loan_accounts",
                         "ltv_percent", min_val=0, max_val=200)

runner.check_value_range("loan_warehouse.loan_accounts", "loan_accounts",
                         "delinquency_days", min_val=0)

runner.check_value_range("loan_warehouse.loan_accounts", "loan_accounts",
                         "status", allowed_values=["ACTIVE", "CLOSED", "DEFAULT", "FORBEARANCE"])

runner.check_value_range("loan_warehouse.payments", "payments",
                         "type", allowed_values=["REGULAR", "EXTRA", "PARTIAL", "PREPAYMENT"])

runner.check_value_range("loan_warehouse.payments", "payments",
                         "status", allowed_values=["POSTED", "REVERSED", "NSF", "PENDING"])

# -----------------------------------------------------------------
# Uniqueness Checks
# -----------------------------------------------------------------
runner.check_uniqueness("loan_warehouse.borrowers", "borrowers", "external_id")
runner.check_uniqueness("loan_warehouse.loan_products", "loan_products", "code")
runner.check_uniqueness("loan_warehouse.loan_accounts", "loan_accounts", "account_number")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Generate Report

# COMMAND ----------

report = runner.generate_report("/dbfs/mnt/reports/DATA_QUALITY_REPORT.md")
print(report)
