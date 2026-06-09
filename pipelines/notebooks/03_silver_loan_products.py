# Databricks notebook source
# MAGIC %md
# MAGIC # 03 - Silver Layer: Loan Product Transformation
# MAGIC
# MAGIC Transforms `bronze.cdw_ln_prod` → `silver.loan_products`
# MAGIC
# MAGIC **Transformations applied:**
# MAGIC - Parse term months → IntegerType
# MAGIC - Parse min/max amounts (comma-separated) → DecimalType
# MAGIC - Convert status code to boolean `is_active` (ACT → true)
# MAGIC - Parse effective/expiration dates → DateType

# COMMAND ----------

import sys
sys.path.insert(0, "../")

from config.pipeline_config import (
    BRONZE_CATALOG,
    BRONZE_SCHEMA,
    SILVER_CATALOG,
    SILVER_SCHEMA,
)
from utils.transformations import (
    parse_legacy_date,
    parse_legacy_amount,
    parse_legacy_integer,
    status_to_boolean,
)
from utils.data_quality import (
    check_null_required_fields,
    check_numeric_parseable,
    check_date_parseable,
    log_quality_summary,
    QUALITY_ISSUE_SCHEMA,
)
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

# COMMAND ----------

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Bronze Loan Products

# COMMAND ----------

bronze_products = spark.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.cdw_ln_prod")
print(f"Bronze loan product records: {bronze_products.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data Quality Checks

# COMMAND ----------

all_issues = spark.createDataFrame([], QUALITY_ISSUE_SCHEMA)

# Required fields
required = ["PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD", "PROD_TERM_MOS", "PROD_RT_TYP"]
null_issues = check_null_required_fields(
    bronze_products, "CDW_LN_PROD", "PROD_CD", required
)
all_issues = all_issues.union(null_issues)

# Numeric fields
numeric_fields = ["PROD_TERM_MOS", "PROD_MIN_AMT", "PROD_MAX_AMT"]
numeric_issues = check_numeric_parseable(
    bronze_products, "CDW_LN_PROD", "PROD_CD", numeric_fields
)
all_issues = all_issues.union(numeric_issues)

# Date fields
date_fields = ["PROD_EFF_DT", "PROD_EXP_DT"]
date_issues = check_date_parseable(
    bronze_products, "CDW_LN_PROD", "PROD_CD", date_fields
)
all_issues = all_issues.union(date_issues)

log_quality_summary(all_issues, "Silver Loan Products - Pre-Transform")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Apply Transformations

# COMMAND ----------

silver_products = bronze_products.select(
    # Direct copies
    F.trim(F.col("PROD_CD")).alias("code"),
    F.trim(F.col("PROD_DESC_TXT")).alias("name"),
    F.trim(F.col("PROD_TYP_CD")).alias("type"),

    # Numeric parsing
    parse_legacy_integer(F.col("PROD_TERM_MOS")).alias("term_months"),
    F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
    parse_legacy_amount(F.col("PROD_MIN_AMT")).alias("min_amount"),
    parse_legacy_amount(F.col("PROD_MAX_AMT")).alias("max_amount"),

    # Status to boolean: ACT → true, else false
    status_to_boolean(F.col("PROD_STAT_CD")).alias("is_active"),

    # Date parsing
    parse_legacy_date(F.col("PROD_EFF_DT")).alias("effective_date"),
    parse_legacy_date(F.col("PROD_EXP_DT")).alias("expiration_date"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Silver Loan Products

# COMMAND ----------

target_table = f"{SILVER_CATALOG}.{SILVER_SCHEMA}.loan_products"

(
    silver_products.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(target_table)
)

row_count = spark.table(target_table).count()
print(f"Silver loan_products written: {row_count} rows → {target_table}")
silver_products.show(truncate=False)
