"""
Shared transformation utilities for legacy CDW to modern Delta Lake migration.

This module provides reusable PySpark UDFs and helper functions that handle
the common data quality issues found in the legacy CDW schema:
  - All columns stored as VARCHAR (strings)
  - Dates encoded as MM/DD/YYYY strings
  - Monetary amounts stored with commas (e.g., "285,000")
  - Status/type codes stored as cryptic abbreviations
  - Null and malformed value handling with logging (no silent drops)
"""

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    BooleanType,
    TimestampType,
)


# ---------------------------------------------------------------------------
# Status / type code expansion mappings
# ---------------------------------------------------------------------------
# These dictionaries map legacy abbreviation codes to their full modern values.
# Sourced from data/mappings/column_mappings.md in the repository.

# Loan status codes (CDW_LN_ACCT.LN_STAT_CD)
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Borrower status codes (CDW_BORR_MSTR.BORR_STAT_CD)
BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
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

# Product status to boolean (CDW_LN_PROD.PROD_STAT_CD)
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}

# Property type codes (CDW_LN_ACCT.PROP_TYP_CD)
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

def parse_date_col(col_name: str, alias: str = None) -> F.Column:
    """
    Parse a legacy MM/DD/YYYY date string column to DateType.

    Handles nulls and empty strings gracefully — returns null for unparseable
    values rather than failing the pipeline. Malformed dates are preserved as
    null so they can be caught by the data quality checks downstream.

    Args:
        col_name: Name of the source column containing MM/DD/YYYY strings.
        alias: Optional output column name. Defaults to col_name if not given.

    Returns:
        A PySpark Column expression of DateType.
    """
    output_name = alias or col_name
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(output_name)


def parse_timestamp_col(col_name: str, alias: str = None) -> F.Column:
    """
    Parse a legacy MM/DD/YYYY date string column to TimestampType.

    Used for audit fields (created_at, updated_at) where the modern schema
    expects TIMESTAMP rather than DATE.

    Args:
        col_name: Name of the source column containing MM/DD/YYYY strings.
        alias: Optional output column name. Defaults to col_name if not given.

    Returns:
        A PySpark Column expression of TimestampType.
    """
    output_name = alias or col_name
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(output_name)


# ---------------------------------------------------------------------------
# Amount / numeric parsing helpers
# ---------------------------------------------------------------------------

def parse_amount_col(col_name: str, alias: str = None,
                     precision: int = 12, scale: int = 2) -> F.Column:
    """
    Parse a legacy comma-formatted amount string to DecimalType.

    Legacy amounts are stored as strings with commas (e.g., "285,000" or
    "271,432.56"). This function strips commas and casts to DECIMAL.
    Null or empty values result in null output.

    Args:
        col_name: Name of the source column containing amount strings.
        alias: Optional output column name. Defaults to col_name if not given.
        precision: Total number of digits. Default 12.
        scale: Number of decimal places. Default 2.

    Returns:
        A PySpark Column expression of DecimalType.
    """
    output_name = alias or col_name
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(precision, scale))
        .alias(output_name)
    )


def parse_int_col(col_name: str, alias: str = None) -> F.Column:
    """
    Parse a legacy string column to IntegerType.

    Used for fields like credit score, term months, and delinquency days
    that are stored as VARCHAR in the legacy schema.

    Args:
        col_name: Name of the source column containing integer strings.
        alias: Optional output column name. Defaults to col_name if not given.

    Returns:
        A PySpark Column expression of IntegerType.
    """
    output_name = alias or col_name
    return F.col(col_name).cast(IntegerType()).alias(output_name)


def parse_rate_col(col_name: str, alias: str = None,
                   precision: int = 5, scale: int = 3) -> F.Column:
    """
    Parse a legacy rate/percentage string to DecimalType.

    Used for interest rates (e.g., "4.750") and LTV percentages (e.g., "82.5").

    Args:
        col_name: Name of the source column containing rate strings.
        alias: Optional output column name. Defaults to col_name if not given.
        precision: Total number of digits. Default 5.
        scale: Number of decimal places. Default 3.

    Returns:
        A PySpark Column expression of DecimalType.
    """
    output_name = alias or col_name
    return F.col(col_name).cast(DecimalType(precision, scale)).alias(output_name)


# ---------------------------------------------------------------------------
# Code expansion helpers
# ---------------------------------------------------------------------------

def expand_status_col(col_name: str, mapping: dict, alias: str = None) -> F.Column:
    """
    Expand a legacy abbreviation code to its full modern value using a mapping dict.

    Unknown codes are preserved as-is with a '_UNKNOWN' suffix appended so they
    can be flagged by data quality checks without dropping records.

    Args:
        col_name: Name of the source column containing abbreviation codes.
        mapping: Dictionary mapping legacy codes to modern values.
        alias: Optional output column name. Defaults to col_name if not given.

    Returns:
        A PySpark Column expression with expanded values.
    """
    output_name = alias or col_name
    # Build a CASE WHEN chain from the mapping dictionary
    expr = F.col(col_name)
    result = F.lit(None).cast("string")
    for legacy_code, modern_value in mapping.items():
        result = F.when(expr == legacy_code, F.lit(modern_value)).otherwise(result)
    # Preserve unknown codes with a suffix for downstream flagging
    result = F.when(result.isNotNull(), result).otherwise(
        F.concat(F.col(col_name), F.lit("_UNKNOWN"))
    )
    return result.alias(output_name)


def expand_product_status_col(col_name: str, alias: str = None) -> F.Column:
    """
    Convert legacy product status code to boolean (ACT -> true, INA -> false).

    Args:
        col_name: Name of the source column containing status codes.
        alias: Optional output column name. Defaults to col_name if not given.

    Returns:
        A PySpark Column expression of BooleanType.
    """
    output_name = alias or col_name
    return (
        F.when(F.col(col_name) == "ACT", F.lit(True))
        .when(F.col(col_name) == "INA", F.lit(False))
        .otherwise(F.lit(None).cast(BooleanType()))
        .alias(output_name)
    )


# ---------------------------------------------------------------------------
# Logging / error handling helpers
# ---------------------------------------------------------------------------

def add_validation_flags(df, date_cols=None, amount_cols=None):
    """
    Add boolean flag columns indicating parse failures for key fields.

    This allows downstream quality checks to identify rows with malformed
    data without dropping them from the pipeline. Each flag column is named
    '_is_valid_<original_col>' and is True when the parsed value is not null
    (assuming the source value was not null).

    Args:
        df: Input PySpark DataFrame (after transformations).
        date_cols: List of (source_col, parsed_col) tuples for date validation.
        amount_cols: List of (source_col, parsed_col) tuples for amount validation.

    Returns:
        DataFrame with additional validation flag columns.
    """
    if date_cols:
        for source_col, parsed_col in date_cols:
            flag_name = f"_is_valid_{parsed_col}"
            # Valid if source was null (nothing to parse) or parsed result is not null
            df = df.withColumn(
                flag_name,
                F.when(F.col(source_col).isNull(), F.lit(True))
                .otherwise(F.col(parsed_col).isNotNull())
            )
    if amount_cols:
        for source_col, parsed_col in amount_cols:
            flag_name = f"_is_valid_{parsed_col}"
            df = df.withColumn(
                flag_name,
                F.when(F.col(source_col).isNull(), F.lit(True))
                .otherwise(F.col(parsed_col).isNotNull())
            )
    return df
