"""
Delta Lake schema definition for the loan_products table.

Migrated from legacy CDW_LN_PROD.
No partitioning — small reference/dimension table (< 1000 rows expected).
"""

from pyspark.sql.types import (
    BooleanType,
    DateType,
    DecimalType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

LOAN_PRODUCTS_SCHEMA = StructType([
    StructField("id", LongType(), nullable=False),
    StructField("code", StringType(), nullable=False),
    StructField("name", StringType(), nullable=False),
    StructField("type", StringType(), nullable=False),
    StructField("term_months", IntegerType(), nullable=False),
    StructField("rate_type", StringType(), nullable=False),
    StructField("min_amount", DecimalType(12, 2), nullable=True),
    StructField("max_amount", DecimalType(12, 2), nullable=True),
    StructField("is_active", BooleanType(), nullable=True),
    StructField("effective_date", DateType(), nullable=True),
    StructField("expiration_date", DateType(), nullable=True),
])

LOAN_PRODUCTS_TABLE_NAME = "loan_warehouse.loan_products"
LOAN_PRODUCTS_PARTITION_COLS = []  # small lookup table, no partitioning needed
LOAN_PRODUCTS_PATH = "/mnt/delta/loan_warehouse/loan_products"

LOAN_PRODUCTS_DDL = """
CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    id              BIGINT    NOT NULL,
    code            STRING    NOT NULL,
    name            STRING    NOT NULL,
    type            STRING    NOT NULL,
    term_months     INT       NOT NULL,
    rate_type       STRING    NOT NULL,
    min_amount      DECIMAL(12,2),
    max_amount      DECIMAL(12,2),
    is_active       BOOLEAN,
    effective_date  DATE,
    expiration_date DATE
)
USING DELTA
LOCATION '/mnt/delta/loan_warehouse/loan_products'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
)
"""

COLUMN_MAPPING = {
    "PROD_CD":        "code",
    "PROD_DESC_TXT":  "name",
    "PROD_TYP_CD":    "type",
    "PROD_TERM_MOS":  "term_months",
    "PROD_RT_TYP":    "rate_type",
    "PROD_MIN_AMT":   "min_amount",
    "PROD_MAX_AMT":   "max_amount",
    "PROD_STAT_CD":   "is_active",
    "PROD_EFF_DT":    "effective_date",
    "PROD_EXP_DT":    "expiration_date",
}
