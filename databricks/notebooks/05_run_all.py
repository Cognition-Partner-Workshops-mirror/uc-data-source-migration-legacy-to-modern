# Databricks notebook source

# MAGIC %md
# MAGIC # Full Migration Pipeline Orchestrator
# MAGIC
# MAGIC This notebook runs all four ingestion notebooks in the correct dependency
# MAGIC order. It can be scheduled as a single Databricks job or run interactively.
# MAGIC
# MAGIC ### Execution Order
# MAGIC | Step | Notebook | Source Table | Target Table | Dependencies |
# MAGIC |------|----------|-------------|--------------|-------------|
# MAGIC | 1 | `01_ingest_borrowers` | CDW_BORR_MSTR | borrowers | None |
# MAGIC | 2 | `02_ingest_loan_products` | CDW_LN_PROD | loan_products | None |
# MAGIC | 3 | `03_ingest_loan_accounts` | CDW_LN_ACCT | loan_accounts | borrowers, loan_products |
# MAGIC | 4 | `04_ingest_payments` | CDW_PMT_HIST | payments | loan_accounts |
# MAGIC
# MAGIC Steps 1 and 2 have no FK dependencies and could theoretically run in
# MAGIC parallel. Steps 3 and 4 must run sequentially after their dependencies.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("base_source_path", "/mnt/legacy-extract", "Base Source Path")
dbutils.widgets.dropdown("file_format", "csv", ["csv", "parquet"], "File Format")
dbutils.widgets.text("quarantine_base", "/mnt/quarantine", "Quarantine Base Path")

base_source_path = dbutils.widgets.get("base_source_path").rstrip("/")
file_format = dbutils.widgets.get("file_format")
quarantine_base = dbutils.widgets.get("quarantine_base").rstrip("/")

print(f"Base source:  {base_source_path}")
print(f"File format:  {file_format}")
print(f"Quarantine:   {quarantine_base}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Ingest Borrowers
# MAGIC Dimension table with no FK dependencies. Must complete before loan accounts.

# COMMAND ----------

dbutils.notebook.run("./01_ingest_borrowers", 600, {
    "source_path": f"{base_source_path}/cdw_borr_mstr/",
    "file_format": file_format,
    "target_table": "loan_warehouse.borrowers",
    "quarantine_path": f"{quarantine_base}/borrowers/",
})
print("Borrower ingestion complete.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — Ingest Loan Products
# MAGIC Small reference/dimension table. Must complete before loan accounts.

# COMMAND ----------

dbutils.notebook.run("./02_ingest_loan_products", 600, {
    "source_path": f"{base_source_path}/cdw_ln_prod/",
    "file_format": file_format,
    "target_table": "loan_warehouse.loan_products",
    "quarantine_path": f"{quarantine_base}/loan_products/",
})
print("Loan product ingestion complete.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — Ingest Loan Accounts
# MAGIC Fact table that resolves FKs to `borrowers` and `loan_products`.
# MAGIC Denormalized borrower fields are dropped during transformation.

# COMMAND ----------

dbutils.notebook.run("./03_ingest_loan_accounts", 1200, {
    "source_path": f"{base_source_path}/cdw_ln_acct/",
    "file_format": file_format,
    "target_table": "loan_warehouse.loan_accounts",
    "borrower_table": "loan_warehouse.borrowers",
    "product_table": "loan_warehouse.loan_products",
    "quarantine_path": f"{quarantine_base}/loan_accounts/",
})
print("Loan account ingestion complete.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Ingest Payments
# MAGIC High-volume fact table that resolves FKs to `loan_accounts`.

# COMMAND ----------

dbutils.notebook.run("./04_ingest_payments", 1200, {
    "source_path": f"{base_source_path}/cdw_pmt_hist/",
    "file_format": file_format,
    "target_table": "loan_warehouse.payments",
    "loan_table": "loan_warehouse.loan_accounts",
    "quarantine_path": f"{quarantine_base}/payments/",
})
print("Payment ingestion complete.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Pipeline Complete
# MAGIC All four tables have been ingested. Run the **Data Quality Framework**
# MAGIC notebook next to validate the loaded data.
# MAGIC
# MAGIC ```
# MAGIC Next step: Run databricks/notebooks/06_data_quality_checks.py
# MAGIC ```
