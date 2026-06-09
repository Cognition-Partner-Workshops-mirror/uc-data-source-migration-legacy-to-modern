"""
Pipeline configuration for Legacy CDW → Modern data platform migration.

Defines source/target catalog paths, data quality thresholds, and
transformation parameters used across all pipeline notebooks.
"""

# =============================================================================
# Databricks Unity Catalog paths
# =============================================================================
# Bronze layer: raw ingestion from legacy CDW (1:1 copy, string types preserved)
BRONZE_CATALOG = "loan_migration"
BRONZE_SCHEMA = "bronze"

# Silver layer: cleansed, typed, validated data
SILVER_CATALOG = "loan_migration"
SILVER_SCHEMA = "silver"

# Gold layer: business-ready, normalized tables matching modern schema
GOLD_CATALOG = "loan_migration"
GOLD_SCHEMA = "gold"

# Legacy source (JDBC connection to CDW or mounted file path)
LEGACY_SOURCE_FORMAT = "jdbc"
LEGACY_JDBC_URL = "jdbc:h2:mem:legacydb"  # placeholder — override in Databricks secrets
LEGACY_JDBC_DRIVER = "org.h2.Driver"

# =============================================================================
# Table names
# =============================================================================
LEGACY_TABLES = {
    "borrowers": "CDW_BORR_MSTR",
    "loan_products": "CDW_LN_PROD",
    "loan_accounts": "CDW_LN_ACCT",
    "payments": "CDW_PMT_HIST",
}

MODERN_TABLES = {
    "borrowers": "borrowers",
    "loan_products": "loan_products",
    "loan_accounts": "loan_accounts",
    "payments": "payments",
}

# =============================================================================
# Status code expansion mappings
# =============================================================================
BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
    "DEC": "DECEASED",
    "SUS": "SUSPENDED",
}

LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
    "DLQ": "DELINQUENT",
}

PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

# =============================================================================
# Data quality thresholds
# =============================================================================
# Maximum acceptable percentage of null values in required fields
MAX_NULL_PERCENT_CRITICAL = 0.0   # fields like first_name, account_number
MAX_NULL_PERCENT_HIGH = 5.0       # fields like credit_score, dates
MAX_NULL_PERCENT_MEDIUM = 20.0    # fields like middle_initial, address_line2

# Payment component reconciliation tolerance (dollars)
PAYMENT_RECONCILIATION_TOLERANCE = 0.02

# Credit score valid range
CREDIT_SCORE_MIN = 300
CREDIT_SCORE_MAX = 850

# Legacy date format pattern
LEGACY_DATE_FORMAT = "MM/dd/yyyy"
