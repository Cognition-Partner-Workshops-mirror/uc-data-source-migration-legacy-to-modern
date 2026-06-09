# Databricks notebook source
# MAGIC %md
# MAGIC # 06 - Gold Layer: Final Normalized Tables
# MAGIC
# MAGIC Resolves foreign keys from silver layer string IDs to auto-increment BIGINT
# MAGIC surrogate keys, producing the final normalized modern schema.
# MAGIC
# MAGIC **Gold tables produced:**
# MAGIC - `gold.borrowers` — final borrower records with surrogate PK
# MAGIC - `gold.loan_products` — final product catalog with surrogate PK
# MAGIC - `gold.loan_accounts` — loans with FK references to borrowers.id and loan_products.id
# MAGIC - `gold.payments` — payment records with FK reference to loan_accounts.id
# MAGIC
# MAGIC This matches the target schema defined in `data/modern-schema/modern_tables.sql`.

# COMMAND ----------

import sys
sys.path.insert(0, "../")

from config.pipeline_config import (
    SILVER_CATALOG,
    SILVER_SCHEMA,
    GOLD_CATALOG,
    GOLD_SCHEMA,
)
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

# COMMAND ----------

spark = SparkSession.builder.getOrCreate()
spark.sql(f"CREATE CATALOG IF NOT EXISTS {GOLD_CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {GOLD_CATALOG}.{GOLD_SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold Borrowers
# MAGIC
# MAGIC Assign surrogate BIGINT keys via monotonically_increasing_id.
# MAGIC The `external_id` column preserves the legacy BORR_ID for traceability.

# COMMAND ----------

silver_borrowers = spark.table(f"{SILVER_CATALOG}.{SILVER_SCHEMA}.borrowers")

# Assign surrogate PK (auto-increment equivalent for Spark)
gold_borrowers = silver_borrowers.withColumn(
    "id", F.monotonically_increasing_id() + 1
).select(
    "id",
    "external_id",
    "first_name",
    "last_name",
    "middle_initial",
    "ssn_hash",
    "date_of_birth",
    "address_line1",
    "address_line2",
    "city",
    "state",
    "zip_code",
    "phone",
    "email",
    "credit_score",
    "employment_status",
    "annual_income",
    "status",
    "created_at",
    "updated_at",
)

# Write gold borrowers
target = f"{GOLD_CATALOG}.{GOLD_SCHEMA}.borrowers"
(
    gold_borrowers.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(target)
)
print(f"Gold borrowers: {spark.table(target).count()} rows → {target}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold Loan Products
# MAGIC
# MAGIC Assign surrogate keys; `code` preserves legacy PROD_CD.

# COMMAND ----------

silver_products = spark.table(f"{SILVER_CATALOG}.{SILVER_SCHEMA}.loan_products")

gold_products = silver_products.withColumn(
    "id", F.monotonically_increasing_id() + 1
).select(
    "id",
    "code",
    "name",
    "type",
    "term_months",
    "rate_type",
    "min_amount",
    "max_amount",
    "is_active",
    "effective_date",
    "expiration_date",
)

target = f"{GOLD_CATALOG}.{GOLD_SCHEMA}.loan_products"
(
    gold_products.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(target)
)
print(f"Gold loan_products: {spark.table(target).count()} rows → {target}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold Loan Accounts
# MAGIC
# MAGIC Resolve `borrower_external_id` → `borrower_id` (BIGINT FK) and
# MAGIC `product_code` → `product_id` (BIGINT FK) via lookup joins.

# COMMAND ----------

silver_accounts = spark.table(f"{SILVER_CATALOG}.{SILVER_SCHEMA}.loan_accounts")

# Lookup tables for FK resolution
borrower_lookup = gold_borrowers.select(
    F.col("id").alias("borrower_id"),
    F.col("external_id").alias("_borr_ext_id"),
)
product_lookup = gold_products.select(
    F.col("id").alias("product_id"),
    F.col("code").alias("_prod_code"),
)

# Resolve FKs via join
accounts_with_fks = (
    silver_accounts
    .join(borrower_lookup, silver_accounts["borrower_external_id"] == borrower_lookup["_borr_ext_id"], "left")
    .join(product_lookup, silver_accounts["product_code"] == product_lookup["_prod_code"], "left")
)

# Assign surrogate PK and select final columns
gold_accounts = accounts_with_fks.withColumn(
    "id", F.monotonically_increasing_id() + 1
).select(
    "id",
    "account_number",
    "borrower_id",
    "product_id",
    "original_amount",
    "current_balance",
    "interest_rate",
    "term_months",
    "monthly_payment",
    "origination_date",
    "maturity_date",
    "first_payment_date",
    "next_payment_date",
    "status",
    F.coalesce(F.col("delinquency_days"), F.lit(0)).alias("delinquency_days"),
    F.coalesce(F.col("escrow_balance"), F.lit(0).cast("decimal(10,2)")).alias("escrow_balance"),
    "ltv_percent",
    "property_address",
    "property_city",
    "property_state",
    "property_zip",
    "property_type",
    "appraised_value",
    "created_at",
    "updated_at",
)

target = f"{GOLD_CATALOG}.{GOLD_SCHEMA}.loan_accounts"
(
    gold_accounts.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(target)
)
print(f"Gold loan_accounts: {spark.table(target).count()} rows → {target}")

# Verify FK resolution succeeded (no nulls in borrower_id or product_id)
null_fks = gold_accounts.filter(
    F.col("borrower_id").isNull() | F.col("product_id").isNull()
).count()
if null_fks > 0:
    print(f"⚠ WARNING: {null_fks} loan accounts have unresolved FK references")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold Payments
# MAGIC
# MAGIC Resolve `loan_account_number` → `loan_account_id` (BIGINT FK).

# COMMAND ----------

silver_payments = spark.table(f"{SILVER_CATALOG}.{SILVER_SCHEMA}.payments")

# Lookup for loan account FK resolution
account_lookup = gold_accounts.select(
    F.col("id").alias("loan_account_id"),
    F.col("account_number").alias("_acct_nbr"),
)

# Resolve FK
payments_with_fk = silver_payments.join(
    account_lookup,
    silver_payments["loan_account_number"] == account_lookup["_acct_nbr"],
    "left"
)

# Assign surrogate PK and select final columns
gold_payments = payments_with_fk.withColumn(
    "id", F.monotonically_increasing_id() + 1
).select(
    "id",
    "loan_account_id",
    "payment_date",
    "total_amount",
    "principal_amount",
    "interest_amount",
    "escrow_amount",
    F.coalesce(F.col("late_fee"), F.lit(0).cast("decimal(10,2)")).alias("late_fee"),
    "type",
    "status",
    "received_date",
    "processed_date",
    "created_at",
    "updated_at",
)

target = f"{GOLD_CATALOG}.{GOLD_SCHEMA}.payments"
(
    gold_payments.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(target)
)
print(f"Gold payments: {spark.table(target).count()} rows → {target}")

# Verify FK resolution
null_fks = gold_payments.filter(F.col("loan_account_id").isNull()).count()
if null_fks > 0:
    print(f"⚠ WARNING: {null_fks} payments have unresolved loan_account_id FK")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Final Summary
# MAGIC
# MAGIC Print row counts across all gold tables to confirm migration completeness.

# COMMAND ----------

print("\n" + "=" * 60)
print("GOLD LAYER MIGRATION SUMMARY")
print("=" * 60)
for table in ["borrowers", "loan_products", "loan_accounts", "payments"]:
    t = f"{GOLD_CATALOG}.{GOLD_SCHEMA}.{table}"
    count = spark.table(t).count()
    print(f"  {t}: {count} rows")
print("=" * 60)
