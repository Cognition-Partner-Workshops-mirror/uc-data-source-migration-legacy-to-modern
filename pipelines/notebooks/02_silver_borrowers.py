# Databricks notebook source
# MAGIC %md
# MAGIC # 02 - Silver Layer: Borrower Transformation
# MAGIC
# MAGIC Transforms `bronze.cdw_borr_mstr` → `silver.borrowers`
# MAGIC
# MAGIC **Transformations applied:**
# MAGIC - Parse date strings (MM/DD/YYYY) → proper DateType
# MAGIC - Parse credit score → IntegerType with range validation
# MAGIC - Parse annual income (remove commas) → DecimalType
# MAGIC - Expand status codes (ACT → ACTIVE, INA → INACTIVE, etc.)
# MAGIC - Drop legacy-only field `BORR_REC_TYP`
# MAGIC - Data quality checks: null required fields, credit score range, date parsing

# COMMAND ----------

import sys
sys.path.insert(0, "../")

from config.pipeline_config import (
    BRONZE_CATALOG,
    BRONZE_SCHEMA,
    SILVER_CATALOG,
    SILVER_SCHEMA,
    BORROWER_STATUS_MAP,
    LEGACY_DATE_FORMAT,
)
from utils.transformations import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_integer,
    expand_status_code,
)
from utils.data_quality import (
    check_null_required_fields,
    check_date_parseable,
    check_numeric_parseable,
    check_credit_score_range,
    log_quality_summary,
    QUALITY_ISSUE_SCHEMA,
)
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

# COMMAND ----------

spark = SparkSession.builder.getOrCreate()
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SILVER_CATALOG}.{SILVER_SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Bronze Borrowers

# COMMAND ----------

bronze_borrowers = spark.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.cdw_borr_mstr")
print(f"Bronze borrower records: {bronze_borrowers.count()}")
bronze_borrowers.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data Quality Checks (Pre-Transformation)
# MAGIC
# MAGIC Run validations on raw bronze data to identify and log anomalies
# MAGIC before transformation. Issues are logged but do not block the pipeline;
# MAGIC records with critical issues are quarantined separately.

# COMMAND ----------

# Collect all quality issues
all_issues = spark.createDataFrame([], QUALITY_ISSUE_SCHEMA)

# Check required fields are not null
required_fields = ["BORR_ID", "BORR_FST_NM", "BORR_LST_NM"]
null_issues = check_null_required_fields(
    bronze_borrowers, "CDW_BORR_MSTR", "BORR_ID", required_fields
)
all_issues = all_issues.union(null_issues)

# Check date fields are parseable
date_fields = ["BORR_DOB_DT", "BORR_CRET_DT", "BORR_UPDT_DT"]
date_issues = check_date_parseable(
    bronze_borrowers, "CDW_BORR_MSTR", "BORR_ID", date_fields
)
all_issues = all_issues.union(date_issues)

# Check numeric fields are parseable
numeric_fields = ["BORR_ANN_INCM"]
numeric_issues = check_numeric_parseable(
    bronze_borrowers, "CDW_BORR_MSTR", "BORR_ID", numeric_fields
)
all_issues = all_issues.union(numeric_issues)

# Check credit score range
score_issues = check_credit_score_range(
    bronze_borrowers, "CDW_BORR_MSTR", "BORR_ID", "BORR_CRDT_SCR"
)
all_issues = all_issues.union(score_issues)

# Log summary and persist issues for auditing
log_quality_summary(all_issues, "Silver Borrowers - Pre-Transform")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Apply Transformations
# MAGIC
# MAGIC Map CDW_BORR_MSTR columns to modern `borrowers` schema with proper types.

# COMMAND ----------

silver_borrowers = bronze_borrowers.select(
    # Direct copies
    F.col("BORR_ID").alias("external_id"),
    F.trim(F.col("BORR_FST_NM")).alias("first_name"),
    F.trim(F.col("BORR_LST_NM")).alias("last_name"),
    F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
    F.col("BORR_SSN_ENCR").alias("ssn_hash"),

    # Date parsing: MM/DD/YYYY → DateType
    parse_legacy_date(F.col("BORR_DOB_DT")).alias("date_of_birth"),

    # Address fields — direct copy with trim
    F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
    F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
    F.trim(F.col("BORR_CTY_NM")).alias("city"),
    F.trim(F.col("BORR_ST_CD")).alias("state"),
    F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),
    F.trim(F.col("BORR_PH_NBR")).alias("phone"),
    F.trim(F.col("BORR_EMAIL_ADDR")).alias("email"),

    # Numeric parsing: credit score string → integer
    parse_legacy_integer(F.col("BORR_CRDT_SCR")).alias("credit_score"),

    # Direct copy
    F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),

    # Amount parsing: remove commas → decimal
    parse_legacy_amount(F.col("BORR_ANN_INCM")).alias("annual_income"),

    # Status expansion: ACT → ACTIVE, INA → INACTIVE
    expand_status_code(F.col("BORR_STAT_CD"), BORROWER_STATUS_MAP).alias("status"),

    # Timestamp parsing for audit fields
    parse_legacy_timestamp(F.col("BORR_CRET_DT")).alias("created_at"),
    parse_legacy_timestamp(F.col("BORR_UPDT_DT")).alias("updated_at"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Silver Borrowers

# COMMAND ----------

target_table = f"{SILVER_CATALOG}.{SILVER_SCHEMA}.borrowers"

(
    silver_borrowers.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(target_table)
)

row_count = spark.table(target_table).count()
print(f"Silver borrowers written: {row_count} rows → {target_table}")
silver_borrowers.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Post-Transformation Validation

# COMMAND ----------

# Verify no nulls in critical fields after transformation
result = spark.table(target_table)
null_check = result.select(
    F.count("*").alias("total"),
    F.sum(F.when(F.col("external_id").isNull(), 1).otherwise(0)).alias("null_external_id"),
    F.sum(F.when(F.col("first_name").isNull(), 1).otherwise(0)).alias("null_first_name"),
    F.sum(F.when(F.col("last_name").isNull(), 1).otherwise(0)).alias("null_last_name"),
    F.sum(F.when(F.col("date_of_birth").isNull(), 1).otherwise(0)).alias("null_dob"),
    F.sum(F.when(F.col("credit_score").isNull(), 1).otherwise(0)).alias("null_credit_score"),
)
null_check.show(truncate=False)
