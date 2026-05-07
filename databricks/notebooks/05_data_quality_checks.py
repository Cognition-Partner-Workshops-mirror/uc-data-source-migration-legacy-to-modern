# Databricks notebook source

# MAGIC %md
# MAGIC # Data Quality Checks
# MAGIC
# MAGIC This notebook runs post-ingestion validation checks across all four migrated
# MAGIC tables and generates a quality report.
# MAGIC
# MAGIC ### Checks Performed
# MAGIC 1. **Row count reconciliation** — source vs target for each table
# MAGIC 2. **Null checks** — required fields must not be NULL
# MAGIC 3. **Referential integrity** — FK relationships between tables
# MAGIC 4. **Business rules** — domain-specific validations
# MAGIC
# MAGIC ### Dependencies
# MAGIC - **Must run after:** All four ingestion notebooks (01-04)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("source_dir", "/mnt/legacy", "Legacy Source Directory")
dbutils.widgets.dropdown("source_format", "csv", ["csv", "parquet"], "Source Format")
dbutils.widgets.text("target_db", "loan_warehouse", "Target Database")

source_dir = dbutils.widgets.get("source_dir")
source_format = dbutils.widgets.get("source_format")
target_db = dbutils.widgets.get("target_db")

print(f"Source dir:  {source_dir}")
print(f"Format:      {source_format}")
print(f"Target DB:   {target_db}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check Framework
# MAGIC
# MAGIC A lightweight framework to collect check results and generate a report.

# COMMAND ----------

from pyspark.sql import functions as F
from datetime import datetime

results = []


def add_result(category, check_name, passed, detail, severity="ERROR"):
    status = "PASS" if passed else "FAIL"
    results.append({
        "category": category,
        "check_name": check_name,
        "passed": passed,
        "detail": detail,
        "severity": severity,
    })
    print(f"  [{status}] {category} / {check_name}: {detail}")

started_at = datetime.utcnow().isoformat()
print(f"Quality checks started at {started_at}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check 1: Row Count Reconciliation
# MAGIC
# MAGIC Compare the number of rows in each legacy source file against the
# MAGIC corresponding modern target table. They should match (assuming no
# MAGIC records were routed to the error path).

# COMMAND ----------

print("=" * 60)
print("ROW COUNT RECONCILIATION")
print("=" * 60)

table_map = {
    "cdw_borr_mstr": "borrowers",
    "cdw_ln_prod": "loan_products",
    "cdw_ln_acct": "loan_accounts",
    "cdw_pmt_hist": "payments",
}

for source_name, target_name in table_map.items():
    source_path = f"{source_dir}/{source_name}"
    target_table = f"{target_db}.{target_name}"

    try:
        source_df = spark.read.option("header", "true").format(source_format).load(source_path)
        source_count = source_df.count()
    except Exception as e:
        add_result("Row Count", f"{source_name} source readable", False, f"Cannot read: {e}")
        continue

    try:
        target_df = spark.table(target_table)
        target_count = target_df.count()
    except Exception as e:
        add_result("Row Count", f"{target_name} target readable", False, f"Cannot read: {e}")
        continue

    match = source_count == target_count
    add_result("Row Count", f"{source_name} → {target_name}", match,
               f"Source={source_count}, Target={target_count}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check 2: Null Checks on Required Fields
# MAGIC
# MAGIC Verify that columns marked as NOT NULL in the modern schema have no
# MAGIC NULL values. NULLs here indicate either bad source data or a
# MAGIC transformation bug.

# COMMAND ----------

print("=" * 60)
print("NULL CHECKS ON REQUIRED FIELDS")
print("=" * 60)

REQUIRED_FIELDS = {
    "borrowers": ["external_id", "first_name", "last_name"],
    "loan_products": ["code", "name", "type", "term_months", "rate_type"],
    "loan_accounts": [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date",
    ],
    "payments": ["loan_account_id", "payment_date", "total_amount", "type", "status"],
}

for table_name, columns in REQUIRED_FIELDS.items():
    full_table = f"{target_db}.{table_name}"
    try:
        df = spark.table(full_table)
        total_rows = df.count()
    except Exception:
        add_result("Null Check", f"{table_name} table exists", False, f"Table not found")
        continue

    for col_name in columns:
        if col_name not in df.columns:
            add_result("Null Check", f"{table_name}.{col_name}", False, "Column not found")
            continue

        null_count = df.filter(F.col(col_name).isNull()).count()
        passed = null_count == 0
        add_result("Null Check", f"{table_name}.{col_name} NOT NULL", passed,
                   f"{null_count}/{total_rows} nulls",
                   severity="ERROR" if not passed else "INFO")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check 3: Referential Integrity
# MAGIC
# MAGIC Verify that all FK values in child tables exist in their parent tables.
# MAGIC Orphan rows indicate either missing parent data or an FK resolution bug.

# COMMAND ----------

print("=" * 60)
print("REFERENTIAL INTEGRITY")
print("=" * 60)

fk_checks = [
    {
        "name": "loan_accounts.borrower_id → borrowers",
        "child_table": "loan_accounts",
        "child_col": "borrower_id",
        "parent_table": "borrowers",
        "parent_col": "borrower_id",
    },
    {
        "name": "loan_accounts.product_id → loan_products",
        "child_table": "loan_accounts",
        "child_col": "product_id",
        "parent_table": "loan_products",
        "parent_col": "product_id",
    },
    {
        "name": "payments.loan_account_id → loan_accounts",
        "child_table": "payments",
        "child_col": "loan_account_id",
        "parent_table": "loan_accounts",
        "parent_col": "loan_account_id",
    },
]

for check in fk_checks:
    try:
        child_df = spark.table(f"{target_db}.{check['child_table']}")
        parent_df = spark.table(f"{target_db}.{check['parent_table']}")

        child_keys = child_df.select(F.col(check["child_col"]).alias("_fk")).distinct()
        parent_keys = parent_df.select(F.col(check["parent_col"]).alias("_pk")).distinct()

        orphans = child_keys.join(parent_keys, child_keys["_fk"] == parent_keys["_pk"], "left_anti")
        orphan_count = orphans.count()

        add_result("Referential Integrity", check["name"], orphan_count == 0,
                   f"{orphan_count} orphan rows")
    except Exception as e:
        add_result("Referential Integrity", check["name"], False, f"Error: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check 4: Business Rule Validations
# MAGIC
# MAGIC Domain-specific rules that validate the migrated data makes business sense:
# MAGIC - Active loans should have positive balances
# MAGIC - Delinquency days should not be negative
# MAGIC - LTV should be in a reasonable range
# MAGIC - Origination date must be before maturity date
# MAGIC - Interest rates should be in a reasonable range
# MAGIC - Payment amounts should be positive
# MAGIC - Payment component sums should match total
# MAGIC - Credit scores should be in valid range (300-850)

# COMMAND ----------

print("=" * 60)
print("BUSINESS RULE VALIDATIONS")
print("=" * 60)

# --- Loan Accounts ---
try:
    loans_df = spark.table(f"{target_db}.loan_accounts")

    # Active loans must have balance > 0
    active_zero = loans_df.filter(
        (F.col("status") == "Active") & (F.col("current_balance") <= 0)
    ).count()
    add_result("Business Rule", "Active loans have balance > 0", active_zero == 0,
               f"{active_zero} active loans with balance <= 0", "WARNING")

    # Delinquency days >= 0
    neg_dlq = loans_df.filter(F.col("delinquency_days") < 0).count()
    add_result("Business Rule", "Delinquency days >= 0", neg_dlq == 0,
               f"{neg_dlq} loans with negative delinquency days")

    # LTV in valid range (0-200)
    bad_ltv = loans_df.filter(
        (F.col("ltv_percent").isNotNull()) &
        ((F.col("ltv_percent") < 0) | (F.col("ltv_percent") > 200))
    ).count()
    add_result("Business Rule", "LTV percent in range (0-200)", bad_ltv == 0,
               f"{bad_ltv} loans with out-of-range LTV", "WARNING")

    # Origination < maturity
    bad_dates = loans_df.filter(F.col("origination_date") >= F.col("maturity_date")).count()
    add_result("Business Rule", "Origination date < maturity date", bad_dates == 0,
               f"{bad_dates} loans with origination >= maturity")

    # Interest rate 0-30%
    bad_rates = loans_df.filter(
        (F.col("interest_rate") <= 0) | (F.col("interest_rate") > 30)
    ).count()
    add_result("Business Rule", "Interest rate in range (0-30%)", bad_rates == 0,
               f"{bad_rates} loans with out-of-range rate", "WARNING")

    # Closed loans have maturity date
    closed = loans_df.filter(F.col("status") == "Closed")
    closed_count = closed.count()
    if closed_count > 0:
        no_mat = closed.filter(F.col("maturity_date").isNull()).count()
        add_result("Business Rule", "Closed loans have maturity_date", no_mat == 0,
                   f"{no_mat}/{closed_count} closed loans missing maturity_date", "WARNING")
    else:
        add_result("Business Rule", "Closed loans have maturity_date", True,
                   "No closed loans in dataset (skipped)", "INFO")

except Exception as e:
    add_result("Business Rule", "Loan accounts accessible", False, str(e))

# --- Payments ---
try:
    payments_df = spark.table(f"{target_db}.payments")

    # Payment amounts > 0
    zero_pmt = payments_df.filter(F.col("total_amount") <= 0).count()
    add_result("Business Rule", "Payment amounts > 0", zero_pmt == 0,
               f"{zero_pmt} payments with amount <= 0", "WARNING")

    # Component sum matches total (tolerance 0.02)
    pmt_with_sum = payments_df.withColumn(
        "_sum",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0)),
    )
    mismatch = pmt_with_sum.filter(F.abs(F.col("_sum") - F.col("total_amount")) > 0.02).count()
    add_result("Business Rule", "Payment components sum to total", mismatch == 0,
               f"{mismatch} payments where components ≠ total (tol=0.02)", "WARNING")

    # received_date <= processed_date
    bad_recv = payments_df.filter(
        (F.col("received_date").isNotNull()) &
        (F.col("processed_date").isNotNull()) &
        (F.col("received_date") > F.col("processed_date"))
    ).count()
    add_result("Business Rule", "received_date <= processed_date", bad_recv == 0,
               f"{bad_recv} payments where received > processed", "WARNING")

except Exception as e:
    add_result("Business Rule", "Payments accessible", False, str(e))

# --- Borrowers ---
try:
    borr_df = spark.table(f"{target_db}.borrowers")

    # Credit score 300-850
    bad_credit = borr_df.filter(
        (F.col("credit_score").isNotNull()) &
        ((F.col("credit_score") < 300) | (F.col("credit_score") > 850))
    ).count()
    add_result("Business Rule", "Credit score in range (300-850)", bad_credit == 0,
               f"{bad_credit} borrowers with out-of-range score", "WARNING")

    # Annual income >= 0
    neg_inc = borr_df.filter(
        (F.col("annual_income").isNotNull()) & (F.col("annual_income") < 0)
    ).count()
    add_result("Business Rule", "Annual income >= 0", neg_inc == 0,
               f"{neg_inc} borrowers with negative income")

except Exception as e:
    add_result("Business Rule", "Borrowers accessible", False, str(e))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary Report
# MAGIC
# MAGIC Generates the final quality report as a displayable table and markdown file.

# COMMAND ----------

finished_at = datetime.utcnow().isoformat()

total = len(results)
passed = sum(1 for r in results if r["passed"])
failed = total - passed

print("=" * 60)
print("DATA QUALITY SUMMARY")
print("=" * 60)
print(f"Total checks:  {total}")
print(f"Passed:        {passed}")
print(f"Failed:        {failed}")
print(f"Pass rate:     {passed/total*100:.1f}%" if total > 0 else "N/A")

# Display as table
results_df = spark.createDataFrame(results)
display(results_df.select("category", "check_name", "passed", "severity", "detail"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Generate Markdown Report

# COMMAND ----------

lines = [
    "# Data Quality Report",
    "",
    f"**Run started:** {started_at}",
    f"**Run finished:** {finished_at}",
    "",
    "## Summary",
    "",
    "| Metric | Count |",
    "|--------|-------|",
    f"| Total checks | {total} |",
    f"| Passed | {passed} |",
    f"| Failed | {failed} |",
    f"| Pass rate | {passed/total*100:.1f}% |" if total > 0 else "",
    "",
    "## Detailed Results",
    "",
    "| Category | Check | Result | Severity | Detail |",
    "|----------|-------|--------|----------|--------|",
]

for r in results:
    status = "PASS" if r["passed"] else "**FAIL**"
    lines.append(f"| {r['category']} | {r['check_name']} | {status} | {r['severity']} | {r['detail']} |")

failed_checks = [r for r in results if not r["passed"]]
if failed_checks:
    lines += ["", "## Failed Checks Detail", ""]
    for r in failed_checks:
        lines.append(f"- **[{r['severity']}] {r['category']} / {r['check_name']}**: {r['detail']}")

lines += ["", "---", f"*Generated by 05_data_quality_checks notebook on {finished_at}*"]

report_md = "\n".join(lines)
print(report_md)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save Report to DBFS
# MAGIC
# MAGIC The report is saved as a markdown file that can be downloaded or viewed.

# COMMAND ----------

report_path = "/mnt/migration/DATA_QUALITY_REPORT.md"

try:
    dbutils.fs.put(report_path, report_md, overwrite=True)
    print(f"✓ Report saved to {report_path}")
except Exception:
    # Fallback: write locally
    local_path = "/tmp/DATA_QUALITY_REPORT.md"
    with open(local_path, "w") as f:
        f.write(report_md)
    print(f"✓ Report saved locally to {local_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Final Status

# COMMAND ----------

if failed > 0:
    print(f"⚠️ DATA QUALITY: {failed} checks FAILED out of {total} total")
    print("Review the failed checks above and investigate the root cause.")
else:
    print(f"✓ DATA QUALITY: ALL {total} checks PASSED")
