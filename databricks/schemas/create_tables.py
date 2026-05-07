"""
Databricks notebook / script to create all Delta Lake tables for the
loan data warehouse.

Usage (in Databricks):
    %run ./create_tables

Or from a Databricks job:
    spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")
    exec(open("databricks/schemas/create_tables.py").read())
"""

from databricks.schemas.borrowers import BORROWERS_DDL
from databricks.schemas.loan_accounts import LOAN_ACCOUNTS_DDL
from databricks.schemas.loan_products import LOAN_PRODUCTS_DDL
from databricks.schemas.payments import PAYMENTS_DDL

# Order matters: dimension tables first, then fact tables that reference them.
TABLE_DDL_STATEMENTS = [
    ("loan_warehouse database", "CREATE DATABASE IF NOT EXISTS loan_warehouse"),
    ("borrowers", BORROWERS_DDL),
    ("loan_products", LOAN_PRODUCTS_DDL),
    ("loan_accounts", LOAN_ACCOUNTS_DDL),
    ("payments", PAYMENTS_DDL),
]


def create_all_tables(spark):
    """Execute all DDL statements to create the loan warehouse tables."""
    results = []
    for table_name, ddl in TABLE_DDL_STATEMENTS:
        try:
            spark.sql(ddl)
            results.append((table_name, "SUCCESS"))
            print(f"[OK]   Created: {table_name}")
        except Exception as e:
            results.append((table_name, f"FAILED: {e}"))
            print(f"[FAIL] {table_name}: {e}")
    return results


if __name__ == "__main__":
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("LoanWarehouse_CreateTables").getOrCreate()
    create_all_tables(spark)
