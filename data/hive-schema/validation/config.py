"""
Configuration for Hive validation automation.
Defines beeline JDBC connection settings, table metadata, and
data_src_ind (DAILY/MOEND) parameters used across all test modules.
"""

import os

# =============================================================================
# Beeline / JDBC Connection Settings
# =============================================================================
# Override via environment variables for different environments.
BEELINE_JDBC_URL = os.getenv(
    "BEELINE_JDBC_URL",
    "jdbc:hive2://localhost:10000"
)
BEELINE_USER = os.getenv("BEELINE_USER", "hive")
BEELINE_PASSWORD = os.getenv("BEELINE_PASSWORD", "")

# Additional beeline CLI flags (e.g. Kerberos principal, SSL, etc.)
BEELINE_EXTRA_ARGS = os.getenv("BEELINE_EXTRA_ARGS", "")

# Timeout in seconds for a single beeline query execution
QUERY_TIMEOUT_SECONDS = int(os.getenv("QUERY_TIMEOUT_SECONDS", "300"))

# =============================================================================
# Data Source Indicator (data_src_ind) values
# =============================================================================
# DAILY ('D'): business-day snapshots loaded every trading day
# MOEND ('M'): month-end snapshots loaded on the last business day of the month
DATA_SRC_IND_DAILY = "D"
DATA_SRC_IND_MOEND = "M"
VALID_DATA_SRC_IND_VALUES = {DATA_SRC_IND_DAILY, DATA_SRC_IND_MOEND}

# =============================================================================
# Database / Table Definitions
# =============================================================================
# Mirrors the synthetic Hive schema in synthetic_hive_tables.hql.
# Each entry: fully-qualified table name -> metadata dict.

TABLES = {
    # --- Source layer ---
    "default.td_contracts": {
        "database": "default",
        "table": "td_contracts",
        "layer": "source",
        "partition_col": "as_of_dt",
        "description": "Raw contract data from legacy Teradata CDW",
    },
    # --- Staging layer ---
    "work_schema.cad_id": {
        "database": "work_schema",
        "table": "cad_id",
        "layer": "staging",
        "partition_col": "as_of_dt",
        "description": "Borrower identification and demographics",
    },
    "work_schema.cad_cb": {
        "database": "work_schema",
        "table": "cad_cb",
        "layer": "staging",
        "partition_col": "as_of_dt",
        "description": "Current balance for active/forbearance contracts",
    },
    "work_schema.cad_nccb": {
        "database": "work_schema",
        "table": "cad_nccb",
        "layer": "staging",
        "partition_col": "as_of_dt",
        "description": "Non-current balance for closed/defaulted contracts",
    },
    # --- Audit layer ---
    "audit.cad_arrg_dim": {
        "database": "audit",
        "table": "cad_arrg_dim",
        "layer": "audit",
        "partition_col": "as_of_dt",
        "description": "Arrangement dimension (product, terms, property)",
    },
    "audit.cad_actg_unit_bal_fact": {
        "database": "audit",
        "table": "cad_actg_unit_bal_fact",
        "layer": "audit",
        "partition_col": "as_of_dt",
        "description": "Current contract balance and payment fact",
    },
    "audit.cad_nc_actg_unit_bal_fact": {
        "database": "audit",
        "table": "cad_nc_actg_unit_bal_fact",
        "layer": "audit",
        "partition_col": "as_of_dt",
        "description": "Non-current contract balance fact (closure/charge-off)",
    },
}

# =============================================================================
# Status Code Expansion Mappings
# =============================================================================
# From column_mappings.md — used to validate staging/audit status transformations.
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
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
# Cross-Layer Row Count Expectations
# =============================================================================
# Source -> staging: every source row should produce exactly one staging row
# (per data_src_ind). Staging -> audit: row counts should match for the same
# as_of_dt and data_src_ind partition.
#
# current contracts:  ln_stat_cd IN ('ACT', 'FRB') -> cad_cb, cad_actg_unit_bal_fact
# non-current:        ln_stat_cd IN ('CLO', 'DFT') -> cad_nccb, cad_nc_actg_unit_bal_fact
CURRENT_STATUS_CODES = {"ACT", "FRB"}
NON_CURRENT_STATUS_CODES = {"CLO", "DFT"}

# =============================================================================
# Report Settings
# =============================================================================
REPORT_OUTPUT_DIR = os.getenv(
    "REPORT_OUTPUT_DIR",
    os.path.join(os.path.dirname(__file__), "reports")
)
