"""
Delta Lake schema definitions for the loan data warehouse.

Four target tables:
  - borrowers       (dimension, partitioned by status)
  - loan_products   (dimension, unpartitioned — small lookup table)
  - loan_accounts   (fact, partitioned by status)
  - payments        (fact, partitioned by status)
"""

from databricks.schemas.borrowers import (
    BORROWERS_DDL,
    BORROWERS_PARTITION_COLS,
    BORROWERS_PATH,
    BORROWERS_SCHEMA,
    BORROWERS_TABLE_NAME,
)
from databricks.schemas.loan_accounts import (
    LOAN_ACCOUNTS_DDL,
    LOAN_ACCOUNTS_PARTITION_COLS,
    LOAN_ACCOUNTS_PATH,
    LOAN_ACCOUNTS_SCHEMA,
    LOAN_ACCOUNTS_TABLE_NAME,
    LOAN_STATUS_CODES,
    PROPERTY_TYPE_CODES,
)
from databricks.schemas.loan_products import (
    LOAN_PRODUCTS_DDL,
    LOAN_PRODUCTS_PARTITION_COLS,
    LOAN_PRODUCTS_PATH,
    LOAN_PRODUCTS_SCHEMA,
    LOAN_PRODUCTS_TABLE_NAME,
)
from databricks.schemas.payments import (
    PAYMENT_STATUS_CODES,
    PAYMENT_TYPE_CODES,
    PAYMENTS_DDL,
    PAYMENTS_PARTITION_COLS,
    PAYMENTS_PATH,
    PAYMENTS_SCHEMA,
    PAYMENTS_TABLE_NAME,
)

__all__ = [
    "BORROWERS_SCHEMA",
    "BORROWERS_TABLE_NAME",
    "BORROWERS_PARTITION_COLS",
    "BORROWERS_PATH",
    "BORROWERS_DDL",
    "LOAN_PRODUCTS_SCHEMA",
    "LOAN_PRODUCTS_TABLE_NAME",
    "LOAN_PRODUCTS_PARTITION_COLS",
    "LOAN_PRODUCTS_PATH",
    "LOAN_PRODUCTS_DDL",
    "LOAN_ACCOUNTS_SCHEMA",
    "LOAN_ACCOUNTS_TABLE_NAME",
    "LOAN_ACCOUNTS_PARTITION_COLS",
    "LOAN_ACCOUNTS_PATH",
    "LOAN_ACCOUNTS_DDL",
    "LOAN_STATUS_CODES",
    "PROPERTY_TYPE_CODES",
    "PAYMENTS_SCHEMA",
    "PAYMENTS_TABLE_NAME",
    "PAYMENTS_PARTITION_COLS",
    "PAYMENTS_PATH",
    "PAYMENTS_DDL",
    "PAYMENT_TYPE_CODES",
    "PAYMENT_STATUS_CODES",
]
