# Databricks notebook source
# MAGIC %md
# MAGIC # 01 - Bronze Layer: Raw Ingestion from Legacy CDW
# MAGIC
# MAGIC Reads the four legacy CDW tables as-is (all VARCHAR columns) and persists
# MAGIC them into Delta tables in the bronze layer. No transformations are applied
# MAGIC at this stage — the goal is a faithful copy for lineage and reprocessing.
# MAGIC
# MAGIC **Tables ingested:**
# MAGIC - `CDW_BORR_MSTR` → `bronze.cdw_borr_mstr`
# MAGIC - `CDW_LN_PROD` → `bronze.cdw_ln_prod`
# MAGIC - `CDW_LN_ACCT` → `bronze.cdw_ln_acct`
# MAGIC - `CDW_PMT_HIST` → `bronze.cdw_pmt_hist`

# COMMAND ----------

import sys
sys.path.insert(0, "../")

from config.pipeline_config import (
    BRONZE_CATALOG,
    BRONZE_SCHEMA,
    LEGACY_TABLES,
    LEGACY_JDBC_URL,
    LEGACY_JDBC_DRIVER,
)
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from datetime import datetime

# COMMAND ----------

# Initialize Spark session (uses existing Databricks session when running on cluster)
spark = SparkSession.builder.getOrCreate()

# Create bronze schema if not exists
spark.sql(f"CREATE CATALOG IF NOT EXISTS {BRONZE_CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {BRONZE_CATALOG}.{BRONZE_SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ingest Legacy Tables
# MAGIC
# MAGIC Each table is read via JDBC from the legacy CDW source and written as a
# MAGIC Delta table with ingestion metadata columns (_ingested_at, _source_system).

# COMMAND ----------

def ingest_legacy_table(table_name: str, legacy_table: str) -> None:
    """
    Read a single legacy CDW table and write to bronze Delta table.
    Adds metadata columns for lineage tracking.
    """
    print(f"Ingesting {legacy_table} → {BRONZE_CATALOG}.{BRONZE_SCHEMA}.{legacy_table.lower()}")

    # Read from legacy source via JDBC
    # In production: use Databricks secrets for credentials
    df = (
        spark.read.format("jdbc")
        .option("url", LEGACY_JDBC_URL)
        .option("dbtable", legacy_table)
        .option("driver", LEGACY_JDBC_DRIVER)
        .load()
    )

    # Add ingestion metadata columns for lineage
    df_with_metadata = df.withColumns({
        "_ingested_at": F.current_timestamp(),
        "_source_system": F.lit("CDW_LEGACY"),
        "_source_table": F.lit(legacy_table),
        "_batch_id": F.lit(datetime.now().strftime("%Y%m%d_%H%M%S")),
    })

    # Write to bronze Delta table (overwrite for full refresh; use merge for incremental)
    target_table = f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.{legacy_table.lower()}"
    (
        df_with_metadata.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(target_table)
    )

    row_count = spark.table(target_table).count()
    print(f"  → {row_count} rows written to {target_table}")

# COMMAND ----------

# Ingest all legacy tables into bronze layer
for entity, legacy_table in LEGACY_TABLES.items():
    ingest_legacy_table(entity, legacy_table)

print("\nBronze ingestion complete.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Bronze Tables
# MAGIC Quick row counts and schema validation after ingestion.

# COMMAND ----------

for entity, legacy_table in LEGACY_TABLES.items():
    target = f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.{legacy_table.lower()}"
    count = spark.table(target).count()
    print(f"{target}: {count} rows")
