# Databricks notebook source
# MAGIC %md
# MAGIC # Legacy CDW → Modern Data Platform Migration Pipeline
# MAGIC
# MAGIC **Orchestrator notebook** — runs all pipeline stages in order:
# MAGIC 1. Bronze: Raw ingestion from legacy CDW tables
# MAGIC 2. Silver: Cleansed, typed, validated transformations
# MAGIC 3. Gold: Normalized tables with resolved foreign keys
# MAGIC
# MAGIC ## Architecture (Medallion Pattern)
# MAGIC ```
# MAGIC ┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
# MAGIC │   BRONZE        │     │   SILVER          │     │   GOLD           │
# MAGIC │                 │     │                   │     │                  │
# MAGIC │ cdw_borr_mstr   │────▶│ borrowers         │────▶│ borrowers        │
# MAGIC │ cdw_ln_prod     │────▶│ loan_products     │────▶│ loan_products    │
# MAGIC │ cdw_ln_acct     │────▶│ loan_accounts     │────▶│ loan_accounts    │
# MAGIC │ cdw_pmt_hist    │────▶│ payments          │────▶│ payments         │
# MAGIC │                 │     │                   │     │                  │
# MAGIC │ Raw VARCHAR     │     │ Typed + Validated │     │ Normalized + FK  │
# MAGIC │ 1:1 copy        │     │ Quality checked   │     │ Surrogate keys   │
# MAGIC └─────────────────┘     └──────────────────┘     └──────────────────┘
# MAGIC ```
# MAGIC
# MAGIC ## Usage
# MAGIC - **Full refresh:** Run this notebook end-to-end
# MAGIC - **Incremental:** Run individual stage notebooks with appropriate filters
# MAGIC - **Databricks Workflow:** Configure as a multi-task job with dependencies

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

# Notebook paths relative to this orchestrator
NOTEBOOKS = [
    "01_bronze_ingestion",
    "02_silver_borrowers",
    "03_silver_loan_products",
    "04_silver_loan_accounts",
    "05_silver_payments",
    "06_gold_final_tables",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Execute Pipeline Stages

# COMMAND ----------

from datetime import datetime

pipeline_start = datetime.now()
print(f"Pipeline started at: {pipeline_start.isoformat()}")
print("=" * 60)

results = {}
for notebook in NOTEBOOKS:
    stage_start = datetime.now()
    print(f"\n▶ Running: {notebook}")
    try:
        # dbutils.notebook.run() executes each stage as a child notebook
        # timeout_seconds: 1 hour per stage
        result = dbutils.notebook.run(f"./{notebook}", timeout_seconds=3600)
        elapsed = (datetime.now() - stage_start).total_seconds()
        results[notebook] = {"status": "SUCCESS", "elapsed_s": elapsed}
        print(f"  ✓ Completed in {elapsed:.1f}s")
    except Exception as e:
        elapsed = (datetime.now() - stage_start).total_seconds()
        results[notebook] = {"status": "FAILED", "elapsed_s": elapsed, "error": str(e)}
        print(f"  ✗ FAILED after {elapsed:.1f}s: {e}")
        # Fail fast: stop pipeline on first failure
        raise RuntimeError(f"Pipeline stage '{notebook}' failed: {e}") from e

# COMMAND ----------

# MAGIC %md
# MAGIC ## Pipeline Summary

# COMMAND ----------

pipeline_end = datetime.now()
total_elapsed = (pipeline_end - pipeline_start).total_seconds()

print("\n" + "=" * 60)
print("PIPELINE EXECUTION SUMMARY")
print("=" * 60)
print(f"Start:    {pipeline_start.isoformat()}")
print(f"End:      {pipeline_end.isoformat()}")
print(f"Duration: {total_elapsed:.1f}s")
print()
for notebook, info in results.items():
    status_icon = "✓" if info["status"] == "SUCCESS" else "✗"
    print(f"  {status_icon} {notebook}: {info['status']} ({info['elapsed_s']:.1f}s)")
print("=" * 60)

# Return success for workflow integration
dbutils.notebook.exit("SUCCESS")
