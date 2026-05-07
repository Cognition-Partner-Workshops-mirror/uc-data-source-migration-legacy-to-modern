# Databricks notebook source

# MAGIC %md
# MAGIC # Data Quality Checks — Post-Ingestion Validation
# MAGIC
# MAGIC This notebook runs a comprehensive suite of data quality checks after the
# MAGIC CDW-to-Delta migration pipeline completes. It validates:
# MAGIC
# MAGIC 1. **Row count reconciliation** — source vs. target counts match
# MAGIC 2. **Null checks** — required fields have no NULLs
# MAGIC 3. **Referential integrity** — FK relationships are valid
# MAGIC 4. **Business rules** — domain-specific invariants hold
# MAGIC
# MAGIC The output is a structured `DATA_QUALITY_REPORT.md` file.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC Provide the expected source row counts. These should come from the
# MAGIC ingestion pipeline output or be verified against the legacy system.

# COMMAND ----------

dbutils.widgets.text("borrower_count", "5", "Expected Borrower Rows")
dbutils.widgets.text("product_count", "5", "Expected Product Rows")
dbutils.widgets.text("loan_count", "5", "Expected Loan Account Rows")
dbutils.widgets.text("payment_count", "10", "Expected Payment Rows")
dbutils.widgets.text("report_path", "/mnt/reports/DATA_QUALITY_REPORT", "Report Output Path")

source_counts = {
    "borrowers": int(dbutils.widgets.get("borrower_count")),
    "loan_products": int(dbutils.widgets.get("product_count")),
    "loan_accounts": int(dbutils.widgets.get("loan_count")),
    "payments": int(dbutils.widgets.get("payment_count")),
}

report_path = dbutils.widgets.get("report_path")

print("Expected source counts:")
for k, v in source_counts.items():
    print(f"  {k}: {v}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run All Quality Checks
# MAGIC The `run_all_checks` function executes every check category and returns
# MAGIC a `QualityReport` object with pass/fail results.

# COMMAND ----------

from databricks.quality.data_quality_checks import run_all_checks

report = run_all_checks(
    spark,
    source_counts=source_counts,
    output_path=report_path,
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Display Results

# COMMAND ----------

print(report.to_markdown())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check 1 — Row Count Reconciliation
# MAGIC Verifies that the number of rows loaded into each Delta table matches
# MAGIC the expected count from the legacy source. Mismatches indicate rows were
# MAGIC lost or duplicated during ingestion.

# COMMAND ----------

count_results = [r for r in report.results if r.category == "Row Count Reconciliation"]
for r in count_results:
    status = "PASS" if r.passed else "FAIL"
    print(f"[{status}] {r.table}: expected={r.expected_value}, actual={r.actual_value}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check 2 — Null Checks on Required Fields
# MAGIC Required columns (e.g. `external_id`, `account_number`, `payment_date`)
# MAGIC must never be NULL. NULLs in these fields indicate parsing failures or
# MAGIC data corruption.

# COMMAND ----------

null_results = [r for r in report.results if r.category == "Null Checks"]
for r in null_results:
    status = "PASS" if r.passed else "FAIL"
    print(f"[{status}] {r.table}.{r.check_name}: {r.details}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check 3 — Referential Integrity
# MAGIC Validates that:
# MAGIC - Every `loan_accounts.borrower_key` exists in `borrowers.borrower_key`
# MAGIC - Every `loan_accounts.product_key` exists in `loan_products.product_key`
# MAGIC - Every `payments.loan_account_key` exists in `loan_accounts.loan_account_key`
# MAGIC
# MAGIC Orphan records indicate FK resolution failures during ingestion.

# COMMAND ----------

ri_results = [r for r in report.results if r.category == "Referential Integrity"]
for r in ri_results:
    status = "PASS" if r.passed else "FAIL"
    print(f"[{status}] {r.table}.{r.check_name}: {r.details}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check 4 — Business Rule Validation
# MAGIC Domain-specific rules:
# MAGIC - Active loans must have `current_balance > 0`
# MAGIC - Active loans must not have future origination dates
# MAGIC - `maturity_date > origination_date` for all loans
# MAGIC - Interest rate must be positive
# MAGIC - LTV percent in range 0–200%
# MAGIC - Loan status must be a known value (ACTIVE/CLOSED/DEFAULT/FORBEARANCE)
# MAGIC - Payment amounts must be positive
# MAGIC - Payment type and status must be known values
# MAGIC - Credit score in range 300–850
# MAGIC - Annual income must be non-negative

# COMMAND ----------

biz_results = [r for r in report.results if r.category == "Business Rules"]
for r in biz_results:
    status = "PASS" if r.passed else "FAIL"
    print(f"[{status}] {r.table}.{r.check_name}: {r.details}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Overall Verdict

# COMMAND ----------

if report.all_passed:
    print(f"ALL {report.total} CHECKS PASSED — migration data is valid.")
else:
    print(f"QUALITY ISSUES DETECTED: {report.failed}/{report.total} checks failed.")
    print("Review the failed checks above and investigate before promoting data to production.")
    # Optionally raise to fail the Databricks job
    # raise Exception(f"Data quality check failed: {report.failed} checks did not pass")
