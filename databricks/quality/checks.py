"""
Data Quality Checks for the loan warehouse migration.

Each check function returns a dict with:
    - check_name: str
    - category: str (row_count, null_check, referential_integrity, business_rule)
    - passed: bool
    - details: str
    - source_value: optional numeric value
    - target_value: optional numeric value
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# Row Count Reconciliation
# ---------------------------------------------------------------------------

def check_row_count(spark: SparkSession, source_path: str, target_table: str,
                    file_format: str = "csv", tolerance_pct: float = 0.0) -> dict:
    """Verify row counts between source file and target Delta table.

    Args:
        tolerance_pct: Acceptable variance as percentage (0.0 = exact match required)
    """
    if file_format == "csv":
        source_df = spark.read.option("header", "true").csv(source_path)
    else:
        source_df = spark.read.parquet(source_path)

    source_count = source_df.count()
    target_count = spark.table(target_table).count()

    # Account for quarantined records
    quarantine_table = target_table.replace("loan_warehouse.", "loan_warehouse._quarantine_")
    quarantine_count = 0
    try:
        quarantine_count = spark.table(quarantine_table).count()
    except Exception:
        pass  # Quarantine table may not exist if no errors

    effective_target = target_count + quarantine_count
    variance = abs(source_count - effective_target) / max(source_count, 1) * 100

    passed = variance <= tolerance_pct

    return {
        "check_name": f"Row count: {target_table}",
        "category": "row_count",
        "passed": passed,
        "details": (f"Source: {source_count}, Target: {target_count}, "
                    f"Quarantined: {quarantine_count}, Variance: {variance:.2f}%"),
        "source_value": source_count,
        "target_value": effective_target,
    }


# ---------------------------------------------------------------------------
# Null Checks on Required Fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "loan_warehouse.borrowers": ["external_id", "first_name", "last_name", "status"],
    "loan_warehouse.loan_products": ["code", "name", "type", "term_months", "rate_type", "is_active"],
    "loan_warehouse.loan_accounts": [
        "account_number", "borrower_id", "product_id", "original_amount",
        "current_balance", "interest_rate", "term_months", "monthly_payment",
        "origination_date", "maturity_date", "status"
    ],
    "loan_warehouse.payments": [
        "loan_account_id", "payment_date", "total_amount", "type", "status"
    ],
}


def check_nulls(spark: SparkSession, table_name: str) -> list:
    """Check for nulls in required fields for a given table.

    Returns a list of check results (one per required field).
    """
    results = []
    fields = REQUIRED_FIELDS.get(table_name, [])
    df = spark.table(table_name)
    total_rows = df.count()

    for field in fields:
        null_count = df.filter(F.col(field).isNull()).count()
        passed = null_count == 0
        results.append({
            "check_name": f"Null check: {table_name}.{field}",
            "category": "null_check",
            "passed": passed,
            "details": f"{null_count}/{total_rows} records have NULL {field}",
            "source_value": total_rows,
            "target_value": null_count,
        })

    return results


# ---------------------------------------------------------------------------
# Referential Integrity
# ---------------------------------------------------------------------------

def check_referential_integrity(spark: SparkSession) -> list:
    """Validate FK relationships between loan_accounts/payments and parent tables."""
    results = []

    # loan_accounts.borrower_id -> borrowers.id
    loans = spark.table("loan_warehouse.loan_accounts")
    borrowers = spark.table("loan_warehouse.borrowers")

    orphan_borrowers = loans.join(
        borrowers,
        loans["borrower_id"] == borrowers["id"],
        "left_anti"
    ).count()

    results.append({
        "check_name": "FK: loan_accounts.borrower_id -> borrowers.id",
        "category": "referential_integrity",
        "passed": orphan_borrowers == 0,
        "details": f"{orphan_borrowers} loan accounts reference non-existent borrowers",
        "source_value": loans.count(),
        "target_value": orphan_borrowers,
    })

    # loan_accounts.product_id -> loan_products.id
    products = spark.table("loan_warehouse.loan_products")

    orphan_products = loans.join(
        products,
        loans["product_id"] == products["id"],
        "left_anti"
    ).count()

    results.append({
        "check_name": "FK: loan_accounts.product_id -> loan_products.id",
        "category": "referential_integrity",
        "passed": orphan_products == 0,
        "details": f"{orphan_products} loan accounts reference non-existent products",
        "source_value": loans.count(),
        "target_value": orphan_products,
    })

    # payments.loan_account_id -> loan_accounts.id
    payments = spark.table("loan_warehouse.payments")

    orphan_loans = payments.join(
        loans,
        payments["loan_account_id"] == loans["id"],
        "left_anti"
    ).count()

    results.append({
        "check_name": "FK: payments.loan_account_id -> loan_accounts.id",
        "category": "referential_integrity",
        "passed": orphan_loans == 0,
        "details": f"{orphan_loans} payments reference non-existent loan accounts",
        "source_value": payments.count(),
        "target_value": orphan_loans,
    })

    return results


# ---------------------------------------------------------------------------
# Business Rule Validations
# ---------------------------------------------------------------------------

def check_business_rules(spark: SparkSession) -> list:
    """Validate business rules specific to loan data."""
    results = []
    loans = spark.table("loan_warehouse.loan_accounts")
    payments = spark.table("loan_warehouse.payments")

    # Rule 1: Active loans must have positive balance
    active_zero_balance = loans.filter(
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    ).count()
    active_loans = loans.filter(F.col("status") == "ACTIVE").count()

    results.append({
        "check_name": "Business rule: Active loans have positive balance",
        "category": "business_rule",
        "passed": active_zero_balance == 0,
        "details": (f"{active_zero_balance}/{active_loans} active loans "
                    f"have zero or negative balance"),
        "source_value": active_loans,
        "target_value": active_zero_balance,
    })

    # Rule 2: Closed loans should have a maturity date in the past or current balance = 0
    # (Relaxed: we just check that closed loans exist with maturity date set)
    closed_no_maturity = loans.filter(
        (F.col("status") == "CLOSED") & F.col("maturity_date").isNull()
    ).count()
    closed_loans = loans.filter(F.col("status") == "CLOSED").count()

    results.append({
        "check_name": "Business rule: Closed loans have maturity date",
        "category": "business_rule",
        "passed": closed_no_maturity == 0,
        "details": (f"{closed_no_maturity}/{closed_loans} closed loans "
                    f"are missing maturity date"),
        "source_value": closed_loans,
        "target_value": closed_no_maturity,
    })

    # Rule 3: Interest rate should be between 0 and 30%
    invalid_rates = loans.filter(
        (F.col("interest_rate") <= 0) | (F.col("interest_rate") > 30)
    ).count()
    total_loans = loans.count()

    results.append({
        "check_name": "Business rule: Interest rate in valid range (0-30%)",
        "category": "business_rule",
        "passed": invalid_rates == 0,
        "details": f"{invalid_rates}/{total_loans} loans have invalid interest rates",
        "source_value": total_loans,
        "target_value": invalid_rates,
    })

    # Rule 4: Payment amounts should be positive
    invalid_payments = payments.filter(F.col("total_amount") <= 0).count()
    total_payments = payments.count()

    results.append({
        "check_name": "Business rule: Payment amounts are positive",
        "category": "business_rule",
        "passed": invalid_payments == 0,
        "details": f"{invalid_payments}/{total_payments} payments have non-positive amounts",
        "source_value": total_payments,
        "target_value": invalid_payments,
    })

    # Rule 5: Origination date must be before maturity date
    invalid_dates = loans.filter(
        F.col("origination_date") >= F.col("maturity_date")
    ).count()

    results.append({
        "check_name": "Business rule: Origination date before maturity date",
        "category": "business_rule",
        "passed": invalid_dates == 0,
        "details": f"{invalid_dates}/{total_loans} loans have origination >= maturity date",
        "source_value": total_loans,
        "target_value": invalid_dates,
    })

    # Rule 6: Delinquency days should be >= 0
    invalid_delinquency = loans.filter(F.col("delinquency_days") < 0).count()

    results.append({
        "check_name": "Business rule: Delinquency days non-negative",
        "category": "business_rule",
        "passed": invalid_delinquency == 0,
        "details": f"{invalid_delinquency}/{total_loans} loans have negative delinquency days",
        "source_value": total_loans,
        "target_value": invalid_delinquency,
    })

    return results
