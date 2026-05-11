"""
Configuration module for the legacy CDW → Delta Lake migration pipeline.

Contains all lookup dictionaries, file paths, schema definitions, and
transformation constants used across ingestion scripts.
"""

from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
)

# =============================================================================
# Source file paths (CSV/Parquet exported from legacy CDW tables)
# Adjust these to match your Databricks workspace mount or volume paths.
# =============================================================================
SOURCE_PATHS = {
    "borrowers": "/mnt/legacy_export/CDW_BORR_MSTR/",
    "loan_products": "/mnt/legacy_export/CDW_LN_PROD/",
    "loan_accounts": "/mnt/legacy_export/CDW_LN_ACCT/",
    "payments": "/mnt/legacy_export/CDW_PMT_HIST/",
}

# Target Delta Lake database and table names
TARGET_DATABASE = "loan_warehouse"
TARGET_TABLES = {
    "borrowers": f"{TARGET_DATABASE}.borrowers",
    "loan_products": f"{TARGET_DATABASE}.loan_products",
    "loan_accounts": f"{TARGET_DATABASE}.loan_accounts",
    "payments": f"{TARGET_DATABASE}.payments",
}

# =============================================================================
# Legacy date format used across all CDW tables (MM/DD/YYYY)
# =============================================================================
LEGACY_DATE_FORMAT = "MM/dd/yyyy"

# =============================================================================
# Status code expansion mappings
# Sourced from data/mappings/column_mappings.md
# =============================================================================

# CDW_BORR_MSTR.BORR_STAT_CD → borrowers.status
BORROWER_STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive",
}

# CDW_LN_ACCT.LN_STAT_CD → loan_accounts.status
LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

# CDW_LN_ACCT.PROP_TYP_CD → loan_accounts.property_type
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

# CDW_LN_PROD.PROD_STAT_CD → loan_products.is_active
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}

# CDW_PMT_HIST.PMT_TYP_CD → payments.type
PAYMENT_TYPE_MAP = {
    "REG": "Regular",
    "EXT": "Extra",
    "PRT": "Partial",
    "PRE": "Prepayment",
}

# CDW_PMT_HIST.PMT_STAT_CD → payments.status
PAYMENT_STATUS_MAP = {
    "PST": "Posted",
    "REV": "Reversed",
    "NSF": "NSF",
    "PND": "Pending",
}

# =============================================================================
# Legacy source schemas (all VARCHAR, matching CDW table structures)
# Used when reading CSV exports to ensure consistent column naming.
# =============================================================================

BORROWER_LEGACY_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_MID_INIT", StringType(), True),
    StructField("BORR_SSN_ENCR", StringType(), True),
    StructField("BORR_DOB_DT", StringType(), True),
    StructField("BORR_ADDR_LN1", StringType(), True),
    StructField("BORR_ADDR_LN2", StringType(), True),
    StructField("BORR_CTY_NM", StringType(), True),
    StructField("BORR_ST_CD", StringType(), True),
    StructField("BORR_ZIP_CD", StringType(), True),
    StructField("BORR_PH_NBR", StringType(), True),
    StructField("BORR_EMAIL_ADDR", StringType(), True),
    StructField("BORR_CRDT_SCR", StringType(), True),
    StructField("BORR_EMP_STAT", StringType(), True),
    StructField("BORR_ANN_INCM", StringType(), True),
    StructField("BORR_CRET_DT", StringType(), True),
    StructField("BORR_UPDT_DT", StringType(), True),
    StructField("BORR_STAT_CD", StringType(), True),
    StructField("BORR_REC_TYP", StringType(), True),
])

LOAN_PRODUCT_LEGACY_SCHEMA = StructType([
    StructField("PROD_CD", StringType(), True),
    StructField("PROD_DESC_TXT", StringType(), True),
    StructField("PROD_TYP_CD", StringType(), True),
    StructField("PROD_TERM_MOS", StringType(), True),
    StructField("PROD_RT_TYP", StringType(), True),
    StructField("PROD_MIN_AMT", StringType(), True),
    StructField("PROD_MAX_AMT", StringType(), True),
    StructField("PROD_STAT_CD", StringType(), True),
    StructField("PROD_EFF_DT", StringType(), True),
    StructField("PROD_EXP_DT", StringType(), True),
])

LOAN_ACCOUNT_LEGACY_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_SSN_LST4", StringType(), True),
    StructField("PROD_CD", StringType(), True),
    StructField("LN_ORIG_AMT", StringType(), True),
    StructField("LN_CURR_BAL", StringType(), True),
    StructField("LN_INT_RT", StringType(), True),
    StructField("LN_TERM_MOS", StringType(), True),
    StructField("LN_PMT_AMT", StringType(), True),
    StructField("LN_ORIG_DT", StringType(), True),
    StructField("LN_MAT_DT", StringType(), True),
    StructField("LN_1ST_PMT_DT", StringType(), True),
    StructField("LN_NXT_PMT_DT", StringType(), True),
    StructField("LN_STAT_CD", StringType(), True),
    StructField("LN_DLQ_DAYS", StringType(), True),
    StructField("LN_ESCROW_BAL", StringType(), True),
    StructField("LN_LTV_PCT", StringType(), True),
    StructField("PROP_ADDR_LN1", StringType(), True),
    StructField("PROP_CTY_NM", StringType(), True),
    StructField("PROP_ST_CD", StringType(), True),
    StructField("PROP_ZIP_CD", StringType(), True),
    StructField("PROP_TYP_CD", StringType(), True),
    StructField("PROP_APRS_VAL", StringType(), True),
    StructField("LN_CRET_DT", StringType(), True),
    StructField("LN_UPDT_DT", StringType(), True),
])

PAYMENT_LEGACY_SCHEMA = StructType([
    StructField("PMT_SEQ_NBR", StringType(), True),
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("PMT_DT", StringType(), True),
    StructField("PMT_AMT", StringType(), True),
    StructField("PMT_PRIN_AMT", StringType(), True),
    StructField("PMT_INT_AMT", StringType(), True),
    StructField("PMT_ESCROW_AMT", StringType(), True),
    StructField("PMT_LATE_FEE", StringType(), True),
    StructField("PMT_TYP_CD", StringType(), True),
    StructField("PMT_STAT_CD", StringType(), True),
    StructField("PMT_RECV_DT", StringType(), True),
    StructField("PMT_PROC_DT", StringType(), True),
    StructField("PMT_CRET_DT", StringType(), True),
    StructField("PMT_UPDT_DT", StringType(), True),
])

# =============================================================================
# Error/quarantine table for records that fail transformation
# =============================================================================
QUARANTINE_TABLE = f"{TARGET_DATABASE}._quarantine"
