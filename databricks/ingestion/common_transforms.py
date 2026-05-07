"""
Common transformation utilities for legacy CDW data migration.

All legacy CDW tables use VARCHAR for everything. This module provides
reusable PySpark UDFs and column expressions for:
  - Date parsing (MM/DD/YYYY string -> DateType)
  - Amount parsing ("285,000" string -> DecimalType)
  - Status code expansion (ACT -> Active, etc.)
  - Null/malformed value handling with logging
"""

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, BooleanType, TimestampType
from datetime import datetime


# =============================================================================
# Date Parsing
# =============================================================================

def parse_legacy_date(col_name: str, alias: str = None) -> F.Column:
    """
    Parse a legacy date string (MM/DD/YYYY) to DateType.
    Falls back to ISO format (yyyy-MM-dd) if primary format fails.
    Returns null for unparseable values instead of raising errors.
    """
    target = alias or col_name
    return F.coalesce(
        F.to_date(F.col(col_name), "MM/dd/yyyy"),
        F.to_date(F.col(col_name), "M/d/yyyy"),
        F.to_date(F.col(col_name), "yyyy-MM-dd"),
    ).alias(target)


def parse_legacy_timestamp(col_name: str, alias: str = None) -> F.Column:
    """
    Parse a legacy date string to TimestampType (midnight on that date).
    Used for created_at/updated_at fields that were stored as date-only strings.
    """
    target = alias or col_name
    return F.to_timestamp(
        F.coalesce(
            F.to_date(F.col(col_name), "MM/dd/yyyy"),
            F.to_date(F.col(col_name), "M/d/yyyy"),
            F.to_date(F.col(col_name), "yyyy-MM-dd"),
        )
    ).alias(target)


# =============================================================================
# Amount / Numeric Parsing
# =============================================================================

def parse_legacy_amount(col_name: str, alias: str = None) -> F.Column:
    """
    Parse a comma-formatted amount string ("285,000" or "1,487.02") to DecimalType.
    Strips commas, dollar signs, and whitespace before casting.
    Returns null for non-numeric values.
    """
    target = alias or col_name
    cleaned = F.regexp_replace(
        F.regexp_replace(
            F.trim(F.col(col_name)),
            r"[$,]", ""
        ),
        r"\s+", ""
    )
    return cleaned.cast(DecimalType(12, 2)).alias(target)


def parse_legacy_decimal(col_name: str, precision: int, scale: int, alias: str = None) -> F.Column:
    """
    Parse a legacy decimal string (e.g. "5.250") to DecimalType with given precision/scale.
    """
    target = alias or col_name
    return F.trim(F.col(col_name)).cast(DecimalType(precision, scale)).alias(target)


def parse_legacy_integer(col_name: str, alias: str = None) -> F.Column:
    """
    Parse a legacy integer string (e.g. "360") to IntegerType.
    """
    target = alias or col_name
    return F.trim(F.col(col_name)).cast(IntegerType()).alias(target)


# =============================================================================
# Status Code Expansion
# =============================================================================

LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
    "DEC": "DECEASED",
    "SUS": "SUSPENDED",
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


def expand_status_code(col_name: str, mapping: dict, alias: str = None) -> F.Column:
    """
    Expand a legacy abbreviation code to its full value using a mapping dict.
    Unmapped values are preserved as-is (logged downstream by quality checks).
    """
    target = alias or col_name
    expr = F.col(col_name)
    for code, expanded in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(expanded)).otherwise(expr)
    return expr.alias(target)


def expand_product_status(col_name: str, alias: str = None) -> F.Column:
    """
    Convert product status code to boolean is_active flag.
    ACT -> true, everything else -> false.
    """
    target = alias or col_name
    return (F.col(col_name) == "ACT").cast(BooleanType()).alias(target)


# =============================================================================
# Quarantine / Error Logging
# =============================================================================

def add_quality_flags(df, required_columns: list):
    """
    Add a _quality_issues column that lists any problems found in each row.
    This column can be used to route rows to a quarantine table.
    """
    conditions = []
    for col_name in required_columns:
        conditions.append(
            F.when(
                F.col(col_name).isNull() | (F.trim(F.col(col_name)) == ""),
                F.lit(f"missing_{col_name}")
            )
        )

    if conditions:
        issues = F.array_compact(F.array(*conditions))
        df = df.withColumn("_quality_issues", issues)
        df = df.withColumn("_has_quality_issues", F.size(F.col("_quality_issues")) > 0)
    return df
