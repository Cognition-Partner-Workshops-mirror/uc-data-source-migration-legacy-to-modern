# Databricks notebook source

# MAGIC %md
# MAGIC # Migration Pipeline Orchestrator
# MAGIC
# MAGIC Runs all ingestion notebooks in the correct order, respecting FK dependencies.
# MAGIC
# MAGIC ```
# MAGIC Step 1: 01_ingest_borrowers      (no dependencies)
# MAGIC Step 2: 02_ingest_loan_products   (no dependencies)
# MAGIC    ↓ (Steps 1 & 2 can run in parallel)
# MAGIC Step 3: 03_ingest_loan_accounts   (depends on borrowers + loan_products)
# MAGIC    ↓
# MAGIC Step 4: 04_ingest_payments        (depends on loan_accounts)
# MAGIC    ↓
# MAGIC Step 5: 05_data_quality_checks    (depends on all tables)
# MAGIC ```
# MAGIC
# MAGIC ### Usage
# MAGIC Set the widgets below, then **Run All** to execute the full pipeline.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC These parameters are passed to each child notebook.

# COMMAND ----------

dbutils.widgets.text("source_dir", "/mnt/legacy", "Legacy Source Directory")
dbutils.widgets.dropdown("source_format", "csv", ["csv", "parquet"], "Source Format")
dbutils.widgets.text("target_db", "loan_warehouse", "Target Database")
dbutils.widgets.text("error_dir", "/mnt/migration/errors", "Error Output Directory")

source_dir = dbutils.widgets.get("source_dir")
source_format = dbutils.widgets.get("source_format")
target_db = dbutils.widgets.get("target_db")
error_dir = dbutils.widgets.get("error_dir")

print(f"Source dir:     {source_dir}")
print(f"Source format:  {source_format}")
print(f"Target DB:      {target_db}")
print(f"Error dir:      {error_dir}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Ingest Borrowers
# MAGIC
# MAGIC No dependencies. Loads the borrower dimension table.

# COMMAND ----------

print("=" * 60)
print("STEP 1: Ingesting Borrowers")
print("=" * 60)

dbutils.notebook.run("01_ingest_borrowers", timeout_seconds=600, arguments={
    "source_path": f"{source_dir}/cdw_borr_mstr",
    "source_format": source_format,
    "target_table": f"{target_db}.borrowers",
    "error_path": f"{error_dir}/borrowers",
})

print("✓ Borrowers ingestion complete")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Ingest Loan Products
# MAGIC
# MAGIC No dependencies. Loads the loan product reference table.

# COMMAND ----------

print("=" * 60)
print("STEP 2: Ingesting Loan Products")
print("=" * 60)

dbutils.notebook.run("02_ingest_loan_products", timeout_seconds=600, arguments={
    "source_path": f"{source_dir}/cdw_ln_prod",
    "source_format": source_format,
    "target_table": f"{target_db}.loan_products",
    "error_path": f"{error_dir}/loan_products",
})

print("✓ Loan Products ingestion complete")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Ingest Loan Accounts
# MAGIC
# MAGIC **Depends on:** borrowers (Step 1), loan_products (Step 2)
# MAGIC
# MAGIC Resolves FK references to borrower_id and product_id.

# COMMAND ----------

print("=" * 60)
print("STEP 3: Ingesting Loan Accounts")
print("=" * 60)

dbutils.notebook.run("03_ingest_loan_accounts", timeout_seconds=600, arguments={
    "source_path": f"{source_dir}/cdw_ln_acct",
    "source_format": source_format,
    "target_table": f"{target_db}.loan_accounts",
    "borrower_table": f"{target_db}.borrowers",
    "product_table": f"{target_db}.loan_products",
    "error_path": f"{error_dir}/loan_accounts",
})

print("✓ Loan Accounts ingestion complete")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Ingest Payments
# MAGIC
# MAGIC **Depends on:** loan_accounts (Step 3)
# MAGIC
# MAGIC Resolves FK references to loan_account_id.

# COMMAND ----------

print("=" * 60)
print("STEP 4: Ingesting Payments")
print("=" * 60)

dbutils.notebook.run("04_ingest_payments", timeout_seconds=600, arguments={
    "source_path": f"{source_dir}/cdw_pmt_hist",
    "source_format": source_format,
    "target_table": f"{target_db}.payments",
    "loan_table": f"{target_db}.loan_accounts",
    "error_path": f"{error_dir}/payments",
})

print("✓ Payments ingestion complete")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Data Quality Checks
# MAGIC
# MAGIC **Depends on:** All tables loaded (Steps 1-4)
# MAGIC
# MAGIC Runs row count reconciliation, null checks, referential integrity,
# MAGIC and business rule validations.

# COMMAND ----------

print("=" * 60)
print("STEP 5: Running Data Quality Checks")
print("=" * 60)

dbutils.notebook.run("05_data_quality_checks", timeout_seconds=600, arguments={
    "source_dir": source_dir,
    "source_format": source_format,
    "target_db": target_db,
})

print("✓ Data Quality Checks complete")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Pipeline Complete
# MAGIC
# MAGIC All five steps have been executed successfully. Review the data quality
# MAGIC report at `/mnt/migration/DATA_QUALITY_REPORT.md` for detailed results.

# COMMAND ----------

print("=" * 60)
print("MIGRATION PIPELINE COMPLETE")
print("=" * 60)
print(f"\nTarget database: {target_db}")
print(f"Tables loaded:   borrowers, loan_products, loan_accounts, payments")
print(f"Quality report:  /mnt/migration/DATA_QUALITY_REPORT.md")
print(f"Error records:   {error_dir}/")
