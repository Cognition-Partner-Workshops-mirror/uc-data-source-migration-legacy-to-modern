"""
Delta Lake schema definition for the loan_accounts fact table.

Migrated from legacy CDW_LN_ACCT (denormalized, all-VARCHAR).
Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) are
dropped; referential integrity is enforced via borrower_id FK to borrowers.

Partitioned by: status
  - Loan status is the most common filter predicate in analytics queries
    (e.g., "all active loans", "defaulted loans").
  - Low cardinality (ACTIVE, CLOSED, DEFAULT, FORBEARANCE) keeps partition
    count manageable.
"""

from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

LOAN_ACCOUNTS_SCHEMA = StructType([
    StructField("id", LongType(), nullable=False),
    StructField("account_number", StringType(), nullable=False),
    StructField("borrower_id", LongType(), nullable=False),
    StructField("product_id", LongType(), nullable=False),
    StructField("original_amount", DecimalType(12, 2), nullable=False),
    StructField("current_balance", DecimalType(12, 2), nullable=False),
    StructField("interest_rate", DecimalType(5, 3), nullable=False),
    StructField("term_months", IntegerType(), nullable=False),
    StructField("monthly_payment", DecimalType(10, 2), nullable=False),
    StructField("origination_date", DateType(), nullable=False),
    StructField("maturity_date", DateType(), nullable=False),
    StructField("first_payment_date", DateType(), nullable=True),
    StructField("next_payment_date", DateType(), nullable=True),
    StructField("status", StringType(), nullable=False),
    StructField("delinquency_days", IntegerType(), nullable=True),
    StructField("escrow_balance", DecimalType(10, 2), nullable=True),
    StructField("ltv_percent", DecimalType(5, 2), nullable=True),
    StructField("property_address", StringType(), nullable=True),
    StructField("property_city", StringType(), nullable=True),
    StructField("property_state", StringType(), nullable=True),
    StructField("property_zip", StringType(), nullable=True),
    StructField("property_type", StringType(), nullable=True),
    StructField("appraised_value", DecimalType(12, 2), nullable=True),
    StructField("origination_year", IntegerType(), nullable=False),
    StructField("created_at", TimestampType(), nullable=True),
    StructField("updated_at", TimestampType(), nullable=True),
])

LOAN_ACCOUNTS_TABLE_NAME = "loan_warehouse.loan_accounts"
LOAN_ACCOUNTS_PARTITION_COLS = ["status"]
LOAN_ACCOUNTS_PATH = "/mnt/delta/loan_warehouse/loan_accounts"

LOAN_ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    id                  BIGINT          NOT NULL,
    account_number      STRING          NOT NULL,
    borrower_id         BIGINT          NOT NULL,
    product_id          BIGINT          NOT NULL,
    original_amount     DECIMAL(12,2)   NOT NULL,
    current_balance     DECIMAL(12,2)   NOT NULL,
    interest_rate       DECIMAL(5,3)    NOT NULL,
    term_months         INT             NOT NULL,
    monthly_payment     DECIMAL(10,2)   NOT NULL,
    origination_date    DATE            NOT NULL,
    maturity_date       DATE            NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING          NOT NULL,
    delinquency_days    INT,
    escrow_balance      DECIMAL(10,2),
    ltv_percent         DECIMAL(5,2),
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING,
    appraised_value     DECIMAL(12,2),
    origination_year    INT             NOT NULL,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP
)
USING DELTA
PARTITIONED BY (status)
LOCATION '/mnt/delta/loan_warehouse/loan_accounts'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
)
"""

COLUMN_MAPPING = {
    "LN_ACCT_NBR":   "account_number",
    "BORR_ID":       "borrower_id",       # resolved via borrowers lookup
    "PROD_CD":       "product_id",        # resolved via loan_products lookup
    "LN_ORIG_AMT":   "original_amount",
    "LN_CURR_BAL":   "current_balance",
    "LN_INT_RT":     "interest_rate",
    "LN_TERM_MOS":   "term_months",
    "LN_PMT_AMT":    "monthly_payment",
    "LN_ORIG_DT":    "origination_date",
    "LN_MAT_DT":     "maturity_date",
    "LN_1ST_PMT_DT": "first_payment_date",
    "LN_NXT_PMT_DT": "next_payment_date",
    "LN_STAT_CD":    "status",
    "LN_DLQ_DAYS":   "delinquency_days",
    "LN_ESCROW_BAL": "escrow_balance",
    "LN_LTV_PCT":    "ltv_percent",
    "PROP_ADDR_LN1": "property_address",
    "PROP_CTY_NM":   "property_city",
    "PROP_ST_CD":    "property_state",
    "PROP_ZIP_CD":   "property_zip",
    "PROP_TYP_CD":   "property_type",
    "PROP_APRS_VAL": "appraised_value",
    "LN_CRET_DT":    "created_at",
    "LN_UPDT_DT":    "updated_at",
    # BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 intentionally dropped (denormalized)
}

LOAN_STATUS_CODES = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

PROPERTY_TYPE_CODES = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}
