"""
Shared transformation utilities for the legacy CDW to Delta Lake migration.

Provides reusable UDFs and helper functions for common transformation patterns:
  - Date parsing: MM/DD/YYYY string → DateType / TimestampType
  - Amount parsing: Comma-formatted string ("285,000") → DecimalType
  - Status code expansion: ACT → ACTIVE, CLO → CLOSED, etc.
  - Null/malformed value handling with logging
"""

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    TimestampType,
    BooleanType,
)

# =============================================================================
# Date Parsing Functions
# =============================================================================

def parse_date_col(col_name, alias=None):
    """
    Parse a MM/DD/YYYY string column to DateType.

    Returns null for empty/malformed values (logged separately by quality checks).
    Uses to_date with the MM/dd/yyyy format pattern supported by Spark.
    """
    target_name = alias or col_name
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(target_name)


def parse_timestamp_col(col_name, alias=None):
    """
    Parse a MM/DD/YYYY string column to TimestampType.

    Interprets the date as midnight (00:00:00) on the given day.
    Used for created_at/updated_at fields where only date was stored in legacy.
    """
    target_name = alias or col_name
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(target_name)


# =============================================================================
# Amount / Numeric Parsing Functions
# =============================================================================

def parse_amount_col(col_name, alias=None, precision=12, scale=2):
    """
    Parse a comma-formatted amount string (e.g., "285,000" or "1,487.02") to DecimalType.

    Steps:
      1. Strip leading/trailing whitespace
      2. Remove commas
      3. Cast to decimal with specified precision and scale
    Returns null for empty/malformed values.
    """
    target_name = alias or col_name
    return (
        F.regexp_replace(F.trim(F.col(col_name)), ",", "")
        .cast(DecimalType(precision, scale))
        .alias(target_name)
    )


def parse_int_col(col_name, alias=None):
    """
    Parse a string column to IntegerType.

    Handles leading/trailing whitespace. Returns null for non-numeric values.
    """
    target_name = alias or col_name
    return F.trim(F.col(col_name)).cast(IntegerType()).alias(target_name)


def parse_rate_col(col_name, alias=None):
    """
    Parse an interest rate string (e.g., "5.250") to Decimal(5,3).

    Used for LN_INT_RT and similar rate fields.
    """
    target_name = alias or col_name
    return (
        F.trim(F.col(col_name))
        .cast(DecimalType(5, 3))
        .alias(target_name)
    )


def parse_percent_col(col_name, alias=None):
    """
    Parse a percentage string (e.g., "82.5") to Decimal(5,2).

    Used for LTV percentages and similar ratio fields.
    """
    target_name = alias or col_name
    return (
        F.trim(F.col(col_name))
        .cast(DecimalType(5, 2))
        .alias(target_name)
    )


# =============================================================================
# Status Code Expansion Mappings
# =============================================================================

# Borrower status codes (CDW_BORR_MSTR.BORR_STAT_CD)
BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
}

# Loan status codes (CDW_LN_ACCT.LN_STAT_CD)
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Product status codes (CDW_LN_PROD.PROD_STAT_CD) → boolean
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}

# Payment type codes (CDW_PMT_HIST.PMT_TYP_CD)
PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

# Payment status codes (CDW_PMT_HIST.PMT_STAT_CD)
PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

# Property type codes (CDW_LN_ACCT.PROP_TYP_CD)
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


def expand_status_col(col_name, mapping, alias=None):
    """
    Expand a status code abbreviation to its full readable value using a CASE expression.

    Unknown codes are preserved as-is with a 'UNKNOWN:' prefix so they can be flagged
    by downstream data quality checks rather than silently dropped.
    """
    target_name = alias or col_name
    # Build a chained when/otherwise expression from the mapping dict
    expr = F.col(col_name)
    case_expr = None
    for code, expanded in mapping.items():
        condition = F.upper(F.trim(expr)) == code
        if case_expr is None:
            case_expr = F.when(condition, F.lit(expanded))
        else:
            case_expr = case_expr.when(condition, F.lit(expanded))

    # Preserve unknown codes with a prefix for traceability
    case_expr = case_expr.otherwise(
        F.concat(F.lit("UNKNOWN:"), F.coalesce(F.trim(expr), F.lit("NULL")))
    )
    return case_expr.alias(target_name)


def expand_status_to_bool(col_name, mapping, alias=None):
    """
    Expand a status code to a Boolean value (used for product active/inactive status).

    Returns null for unknown codes.
    """
    target_name = alias or col_name
    expr = F.col(col_name)
    case_expr = None
    for code, value in mapping.items():
        condition = F.upper(F.trim(expr)) == code
        if case_expr is None:
            case_expr = F.when(condition, F.lit(value))
        else:
            case_expr = case_expr.when(condition, F.lit(value))
    case_expr = case_expr.otherwise(F.lit(None).cast(BooleanType()))
    return case_expr.alias(target_name)


# =============================================================================
# ETL Metadata Columns
# =============================================================================

def add_etl_metadata(df, source_system):
    """
    Add standard ETL metadata columns to a DataFrame.

    Adds:
      - _ingestion_ts: current timestamp at time of processing
      - _source_system: identifier for the source legacy table
    """
    return df.withColumn(
        "_ingestion_ts", F.current_timestamp()
    ).withColumn(
        "_source_system", F.lit(source_system)
    )


# =============================================================================
# Error Logging / Bad Record Handling
# =============================================================================

def tag_malformed_rows(df, checks, tag_col="_quality_flags"):
    """
    Tag rows that have data quality issues instead of dropping them.

    Args:
        df: Input DataFrame
        checks: List of (condition_expr, flag_label) tuples.
                 condition_expr should be True when the row is BAD.
        tag_col: Name of the output column containing a comma-separated list of flags.

    Returns:
        DataFrame with an additional tag_col containing quality issue flags.
        Clean rows will have null in the tag_col.
    """
    # Build an array of flags for each failed check
    flag_exprs = [
        F.when(cond, F.lit(label))
        for cond, label in checks
    ]
    # Collect non-null flags into a comma-separated string
    flags_array = F.array_compact(F.array(*flag_exprs))
    return df.withColumn(
        tag_col,
        F.when(F.size(flags_array) > 0, F.array_join(flags_array, ",")).otherwise(F.lit(None))
    )
