"""
Data Quality Framework for the Legacy CDW to Delta Lake migration.

Runs after ingestion completes and validates:
  1. Row count reconciliation between source CSV/Parquet files and Delta tables
  2. Null checks on required (NOT NULL) fields
  3. Referential integrity between loan_accounts <-> borrowers, loan_products, payments
  4. Business rule validation (e.g., active loan balance > 0, closed date required)
  5. Generates a DATA_QUALITY_REPORT.md summarizing all pass/fail results
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from datetime import datetime
import logging
import os

logger = logging.getLogger("cdw_migration.data_quality")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Check result data class
# ---------------------------------------------------------------------------
class CheckResult:
    """Stores the result of a single data quality check."""

    def __init__(self, category: str, check_name: str, passed: bool,
                 expected: str = "", actual: str = "", details: str = ""):
        self.category = category
        self.check_name = check_name
        self.passed = passed
        self.expected = expected
        self.actual = actual
        self.details = details

    def status_str(self) -> str:
        return "PASS" if self.passed else "FAIL"


# ---------------------------------------------------------------------------
# 1. Row count reconciliation
# ---------------------------------------------------------------------------
def check_row_counts(spark: SparkSession,
                     source_base_path: str = "/mnt/landing/cdw",
                     source_format: str = "csv") -> list:
    """
    Compare row counts between source files and target Delta tables.
    Returns a list of CheckResult objects.
    """
    results = []

    # Mapping of source sub-folder -> target Delta table
    table_map = {
        "CDW_BORR_MSTR": "loan_warehouse.borrowers",
        "CDW_LN_PROD": "loan_warehouse.loan_products",
        "CDW_LN_ACCT": "loan_warehouse.loan_accounts",
        "CDW_PMT_HIST": "loan_warehouse.payments",
    }

    for source_name, target_table in table_map.items():
        source_path = f"{source_base_path}/{source_name}"
        try:
            # Read source row count
            if source_format == "csv":
                src_df = spark.read.option("header", "true").csv(source_path)
            else:
                src_df = spark.read.parquet(source_path)
            src_count = src_df.count()

            # Read target row count from Delta table
            tgt_count = spark.table(target_table).count()

            passed = src_count == tgt_count
            results.append(CheckResult(
                category="Row Count Reconciliation",
                check_name=f"{source_name} -> {target_table}",
                passed=passed,
                expected=str(src_count),
                actual=str(tgt_count),
                details=f"Source: {src_count} rows, Target: {tgt_count} rows"
                        + ("" if passed else f" (DIFF: {abs(src_count - tgt_count)} rows)")
            ))
        except Exception as e:
            # If source files are not available, compare against known seed counts
            results.append(CheckResult(
                category="Row Count Reconciliation",
                check_name=f"{source_name} -> {target_table}",
                passed=False,
                expected="N/A",
                actual="N/A",
                details=f"Could not read source at {source_path}: {str(e)}"
            ))

    return results


def check_row_counts_known(spark: SparkSession) -> list:
    """
    Alternative row count check using known seed data counts when source
    files are not accessible. Based on the data-legacy.sql seed file:
      - CDW_BORR_MSTR: 5 borrowers
      - CDW_LN_PROD: 5 loan products
      - CDW_LN_ACCT: 5 loan accounts
      - CDW_PMT_HIST: 10 payments
    """
    results = []
    expected_counts = {
        "loan_warehouse.borrowers": 5,
        "loan_warehouse.loan_products": 5,
        "loan_warehouse.loan_accounts": 5,
        "loan_warehouse.payments": 10,
    }

    for table, expected in expected_counts.items():
        try:
            actual = spark.table(table).count()
            passed = actual == expected
            results.append(CheckResult(
                category="Row Count Reconciliation",
                check_name=f"{table} count check",
                passed=passed,
                expected=str(expected),
                actual=str(actual),
                details=f"Expected {expected} rows based on seed data, found {actual}"
            ))
        except Exception as e:
            results.append(CheckResult(
                category="Row Count Reconciliation",
                check_name=f"{table} count check",
                passed=False,
                expected=str(expected),
                actual="ERROR",
                details=f"Could not read table: {str(e)}"
            ))

    return results


# ---------------------------------------------------------------------------
# 2. Null checks on required fields
# ---------------------------------------------------------------------------
def check_required_fields(spark: SparkSession) -> list:
    """
    Verify that NOT NULL columns in target tables contain no NULL values.
    Returns a list of CheckResult objects.
    """
    results = []

    # Define required fields per table (based on modern schema DDL)
    required_fields = {
        "loan_warehouse.borrowers": [
            "external_id", "first_name", "last_name",
        ],
        "loan_warehouse.loan_products": [
            "code", "name", "type", "term_months", "rate_type",
        ],
        "loan_warehouse.loan_accounts": [
            "account_number", "borrower_id", "product_id",
            "original_amount", "current_balance", "interest_rate",
            "term_months", "monthly_payment", "origination_date", "maturity_date",
        ],
        "loan_warehouse.payments": [
            "loan_account_id", "payment_date", "total_amount", "type", "status",
        ],
    }

    for table, fields in required_fields.items():
        try:
            df = spark.table(table)
            for field in fields:
                null_count = df.filter(F.col(field).isNull()).count()
                passed = null_count == 0
                results.append(CheckResult(
                    category="Null Checks",
                    check_name=f"{table}.{field} NOT NULL",
                    passed=passed,
                    expected="0 nulls",
                    actual=f"{null_count} nulls",
                    details=f"Found {null_count} NULL values in required field {field}"
                            if not passed else "No NULL values found"
                ))
        except Exception as e:
            results.append(CheckResult(
                category="Null Checks",
                check_name=f"{table} null checks",
                passed=False,
                expected="0 nulls",
                actual="ERROR",
                details=f"Could not read table: {str(e)}"
            ))

    return results


# ---------------------------------------------------------------------------
# 3. Referential integrity checks
# ---------------------------------------------------------------------------
def check_referential_integrity(spark: SparkSession) -> list:
    """
    Verify FK relationships between tables:
      - Every loan_accounts.borrower_id exists in borrowers.borrower_id
      - Every loan_accounts.product_id exists in loan_products.product_id
      - Every payments.loan_account_id exists in loan_accounts.loan_account_id
    """
    results = []

    # --- loan_accounts.borrower_id -> borrowers.borrower_id ---
    try:
        orphan_borrowers = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.loan_accounts la
            LEFT JOIN loan_warehouse.borrowers b
                ON la.borrower_id = b.borrower_id
            WHERE b.borrower_id IS NULL
              AND la.borrower_id IS NOT NULL
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.borrower_id -> borrowers.borrower_id",
            passed=orphan_borrowers == 0,
            expected="0 orphans",
            actual=f"{orphan_borrowers} orphans",
            details=f"{orphan_borrowers} loan accounts reference non-existent borrowers"
                    if orphan_borrowers > 0 else "All borrower references are valid"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.borrower_id -> borrowers",
            passed=False, details=f"Error: {str(e)}"
        ))

    # --- loan_accounts.product_id -> loan_products.product_id ---
    try:
        orphan_products = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.loan_accounts la
            LEFT JOIN loan_warehouse.loan_products lp
                ON la.product_id = lp.product_id
            WHERE lp.product_id IS NULL
              AND la.product_id IS NOT NULL
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.product_id -> loan_products.product_id",
            passed=orphan_products == 0,
            expected="0 orphans",
            actual=f"{orphan_products} orphans",
            details=f"{orphan_products} loan accounts reference non-existent products"
                    if orphan_products > 0 else "All product references are valid"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Referential Integrity",
            check_name="loan_accounts.product_id -> loan_products",
            passed=False, details=f"Error: {str(e)}"
        ))

    # --- payments.loan_account_id -> loan_accounts.loan_account_id ---
    try:
        orphan_payments = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.payments p
            LEFT JOIN loan_warehouse.loan_accounts la
                ON p.loan_account_id = la.loan_account_id
            WHERE la.loan_account_id IS NULL
              AND p.loan_account_id IS NOT NULL
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Referential Integrity",
            check_name="payments.loan_account_id -> loan_accounts.loan_account_id",
            passed=orphan_payments == 0,
            expected="0 orphans",
            actual=f"{orphan_payments} orphans",
            details=f"{orphan_payments} payments reference non-existent loan accounts"
                    if orphan_payments > 0 else "All loan account references are valid"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Referential Integrity",
            check_name="payments.loan_account_id -> loan_accounts",
            passed=False, details=f"Error: {str(e)}"
        ))

    return results


# ---------------------------------------------------------------------------
# 4. Business rule validation
# ---------------------------------------------------------------------------
def check_business_rules(spark: SparkSession) -> list:
    """
    Validate business rules that should hold in the migrated data:
      - Active loans must have current_balance > 0
      - Closed loans should have a maturity_date
      - Loan interest rates must be between 0 and 100
      - Credit scores must be between 300 and 850 (or NULL)
      - Payment amounts must be >= 0
      - Loan origination_date must be before maturity_date
      - Active borrowers should have an email address
    """
    results = []

    # --- Rule 1: Active loans must have balance > 0 ---
    try:
        bad_active = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.loan_accounts
            WHERE status = 'Active'
              AND (current_balance IS NULL OR current_balance <= 0)
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Business Rules",
            check_name="Active loans have balance > 0",
            passed=bad_active == 0,
            expected="0 violations",
            actual=f"{bad_active} violations",
            details=f"{bad_active} active loans have zero or negative balance"
                    if bad_active > 0 else "All active loans have positive balance"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Business Rules",
            check_name="Active loans balance > 0",
            passed=False, details=f"Error: {str(e)}"
        ))

    # --- Rule 2: Closed loans should have a maturity_date ---
    try:
        bad_closed = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.loan_accounts
            WHERE status = 'Closed'
              AND maturity_date IS NULL
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Business Rules",
            check_name="Closed loans have maturity_date",
            passed=bad_closed == 0,
            expected="0 violations",
            actual=f"{bad_closed} violations",
            details=f"{bad_closed} closed loans missing maturity_date"
                    if bad_closed > 0 else "All closed loans have maturity dates"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Business Rules",
            check_name="Closed loans maturity date",
            passed=False, details=f"Error: {str(e)}"
        ))

    # --- Rule 3: Interest rates between 0 and 100 ---
    try:
        bad_rates = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.loan_accounts
            WHERE interest_rate < 0 OR interest_rate > 100
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Business Rules",
            check_name="Interest rates in range [0, 100]",
            passed=bad_rates == 0,
            expected="0 violations",
            actual=f"{bad_rates} violations",
            details=f"{bad_rates} loans have out-of-range interest rates"
                    if bad_rates > 0 else "All interest rates are within valid range"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Business Rules",
            check_name="Interest rate range",
            passed=False, details=f"Error: {str(e)}"
        ))

    # --- Rule 4: Credit scores between 300 and 850 (or NULL) ---
    try:
        bad_scores = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.borrowers
            WHERE credit_score IS NOT NULL
              AND (credit_score < 300 OR credit_score > 850)
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Business Rules",
            check_name="Credit scores in range [300, 850]",
            passed=bad_scores == 0,
            expected="0 violations",
            actual=f"{bad_scores} violations",
            details=f"{bad_scores} borrowers have out-of-range credit scores"
                    if bad_scores > 0 else "All credit scores are within valid range"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Business Rules",
            check_name="Credit score range",
            passed=False, details=f"Error: {str(e)}"
        ))

    # --- Rule 5: Payment amounts must be >= 0 ---
    try:
        bad_payments = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.payments
            WHERE total_amount < 0
               OR principal_amount < 0
               OR interest_amount < 0
               OR escrow_amount < 0
               OR late_fee < 0
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Business Rules",
            check_name="Payment amounts >= 0",
            passed=bad_payments == 0,
            expected="0 violations",
            actual=f"{bad_payments} violations",
            details=f"{bad_payments} payments have negative amounts"
                    if bad_payments > 0 else "All payment amounts are non-negative"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Business Rules",
            check_name="Payment amounts non-negative",
            passed=False, details=f"Error: {str(e)}"
        ))

    # --- Rule 6: Origination date before maturity date ---
    try:
        bad_dates = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.loan_accounts
            WHERE origination_date >= maturity_date
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Business Rules",
            check_name="origination_date < maturity_date",
            passed=bad_dates == 0,
            expected="0 violations",
            actual=f"{bad_dates} violations",
            details=f"{bad_dates} loans have origination_date >= maturity_date"
                    if bad_dates > 0 else "All loans have origination before maturity"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Business Rules",
            check_name="Date ordering",
            passed=False, details=f"Error: {str(e)}"
        ))

    # --- Rule 7: Active borrowers should have an email ---
    try:
        bad_emails = spark.sql("""
            SELECT COUNT(*) AS cnt
            FROM loan_warehouse.borrowers
            WHERE status = 'Active'
              AND (email IS NULL OR TRIM(email) = '')
        """).collect()[0]["cnt"]

        results.append(CheckResult(
            category="Business Rules",
            check_name="Active borrowers have email",
            passed=bad_emails == 0,
            expected="0 violations",
            actual=f"{bad_emails} violations",
            details=f"{bad_emails} active borrowers missing email address"
                    if bad_emails > 0 else "All active borrowers have email addresses"
        ))
    except Exception as e:
        results.append(CheckResult(
            category="Business Rules",
            check_name="Active borrower email",
            passed=False, details=f"Error: {str(e)}"
        ))

    return results


# ---------------------------------------------------------------------------
# 5. Generate DATA_QUALITY_REPORT.md
# ---------------------------------------------------------------------------
def generate_report(all_results: list, output_path: str = None) -> str:
    """
    Generate a markdown report summarizing all data quality check results.
    Returns the report content as a string and optionally writes to a file.
    """
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    failed = total - passed
    overall = "PASS" if failed == 0 else "FAIL"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Data Quality Report",
        "",
        f"**Generated:** {now}",
        f"**Overall Status:** {overall}",
        f"**Checks Run:** {total} | **Passed:** {passed} | **Failed:** {failed}",
        "",
        "---",
        "",
    ]

    # Group results by category
    categories = {}
    for r in all_results:
        categories.setdefault(r.category, []).append(r)

    for category, checks in categories.items():
        cat_passed = sum(1 for c in checks if c.passed)
        cat_total = len(checks)
        lines.append(f"## {category} ({cat_passed}/{cat_total} passed)")
        lines.append("")
        lines.append("| Check | Status | Expected | Actual | Details |")
        lines.append("|-------|--------|----------|--------|---------|")
        for c in checks:
            status_icon = "PASS" if c.passed else "**FAIL**"
            lines.append(
                f"| {c.check_name} | {status_icon} | {c.expected} | {c.actual} | {c.details} |"
            )
        lines.append("")

    # Summary section
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    if failed == 0:
        lines.append("All data quality checks passed. The migration is validated.")
    else:
        lines.append(f"**{failed} check(s) failed.** Review the failures above and "
                      "investigate root causes before promoting data to production.")
    lines.append("")

    report_content = "\n".join(lines)

    # Write report to file if output path is provided
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report_content)
        logger.info("Data quality report written to %s", output_path)

    return report_content


# ---------------------------------------------------------------------------
# Master runner
# ---------------------------------------------------------------------------
def run_all_checks(
    spark: SparkSession,
    source_base_path: str = "/mnt/landing/cdw",
    source_format: str = "csv",
    report_output_path: str = None,
    use_known_counts: bool = False,
) -> dict:
    """
    Execute all data quality checks and generate the report.

    Args:
        spark: Active SparkSession.
        source_base_path: Path to source files (for row count reconciliation).
        source_format: Format of source files ("csv" or "parquet").
        report_output_path: Optional file path for the markdown report.
                            Defaults to /dbfs/tmp/DATA_QUALITY_REPORT.md.
        use_known_counts: If True, use hardcoded expected counts from seed data
                          instead of reading source files.

    Returns:
        Dictionary with overall status, pass/fail counts, and check details.
    """
    logger.info("Starting data quality checks...")

    all_results = []

    # 1. Row count reconciliation
    if use_known_counts:
        all_results.extend(check_row_counts_known(spark))
    else:
        all_results.extend(check_row_counts(spark, source_base_path, source_format))

    # 2. Required field null checks
    all_results.extend(check_required_fields(spark))

    # 3. Referential integrity
    all_results.extend(check_referential_integrity(spark))

    # 4. Business rules
    all_results.extend(check_business_rules(spark))

    # 5. Generate report
    if report_output_path is None:
        report_output_path = "/dbfs/tmp/DATA_QUALITY_REPORT.md"
    report_content = generate_report(all_results, report_output_path)

    # Also print report to stdout for Databricks notebook output
    print(report_content)

    # Return summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    failed = total - passed

    return {
        "status": "PASS" if failed == 0 else "FAIL",
        "total_checks": total,
        "passed": passed,
        "failed": failed,
        "report_path": report_output_path,
        "checks": [
            {
                "category": r.category,
                "name": r.check_name,
                "passed": r.passed,
                "details": r.details,
            }
            for r in all_results
        ],
    }


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_DataQuality_Checks").getOrCreate()

    try:
        base_path = dbutils.widgets.get("source_base_path")  # noqa: F821
    except Exception:
        base_path = "/mnt/landing/cdw"
    try:
        fmt = dbutils.widgets.get("source_format")  # noqa: F821
    except Exception:
        fmt = "csv"
    try:
        report_path = dbutils.widgets.get("report_output_path")  # noqa: F821
    except Exception:
        report_path = "/dbfs/tmp/DATA_QUALITY_REPORT.md"
    try:
        known = dbutils.widgets.get("use_known_counts").lower() == "true"  # noqa: F821
    except Exception:
        known = False

    results = run_all_checks(spark, base_path, fmt, report_path, known)

    # Fail the notebook if any checks failed (useful for job orchestration)
    if results["status"] == "FAIL":
        raise AssertionError(
            f"Data quality validation FAILED: {results['failed']}/{results['total_checks']} checks failed. "
            f"See report at {results['report_path']}"
        )
