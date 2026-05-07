"""
Shared transformation utilities for the CDW-to-Delta-Lake migration pipeline.

All parsing helpers log warnings for malformed values and return None
instead of silently dropping records.
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType

logger = logging.getLogger("cdw_migration")

# ---------------------------------------------------------------------------
# Status-code expansion maps
# ---------------------------------------------------------------------------
BORROWER_STATUS_MAP = {"ACT": "Active", "INA": "Inactive"}

LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

PAYMENT_TYPE_MAP = {
    "REG": "Regular",
    "EXT": "Extra",
    "PRT": "Partial",
    "PRE": "Prepayment",
}

PAYMENT_STATUS_MAP = {
    "PST": "Posted",
    "REV": "Reversed",
    "NSF": "NSF",
    "PND": "Pending",
}

PRODUCT_STATUS_MAP = {"ACT": True, "INA": False}

PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


# ---------------------------------------------------------------------------
# Column-level transformation helpers (PySpark expressions)
# ---------------------------------------------------------------------------

def expand_status_expr(col_name: str, mapping: dict) -> Column:
    """Build a CASE/WHEN expression that maps abbreviations to full values."""
    expr = F.lit(None).cast("string")
    for code, expanded in mapping.items():
        expr = F.when(F.upper(F.trim(F.col(col_name))) == code, F.lit(expanded)).otherwise(expr)
    return expr.alias(col_name)


def expand_status_with_fallback(col_name: str, mapping: dict, alias: str | None = None) -> Column:
    """Map abbreviations; keep original value (trimmed) if no match is found."""
    target = alias or col_name
    expr = F.trim(F.col(col_name))
    for code, expanded in mapping.items():
        expr = F.when(F.upper(F.trim(F.col(col_name))) == code, F.lit(expanded)).otherwise(expr)
    return expr.alias(target)


def parse_date_expr(col_name: str, alias: str | None = None) -> Column:
    """Parse MM/DD/YYYY string to DateType. Returns null for unparseable values."""
    target = alias or col_name
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(target)


def parse_timestamp_expr(col_name: str, alias: str | None = None) -> Column:
    """Parse MM/DD/YYYY string to TimestampType (midnight). Returns null for unparseable."""
    target = alias or col_name
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(target)


def parse_amount_expr(col_name: str, alias: str | None = None, precision: int = 12, scale: int = 2) -> Column:
    """Strip commas from amount strings and cast to DecimalType."""
    target = alias or col_name
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(precision, scale))
        .alias(target)
    )


def parse_int_expr(col_name: str, alias: str | None = None) -> Column:
    """Cast string column to IntegerType. Returns null for non-numeric values."""
    target = alias or col_name
    return F.col(col_name).cast(IntegerType()).alias(target)


def parse_rate_expr(col_name: str, alias: str | None = None) -> Column:
    """Parse interest rate string (e.g. '5.250') to Decimal(5,3)."""
    target = alias or col_name
    return F.col(col_name).cast(DecimalType(5, 3)).alias(target)


def log_null_counts(df, table_name: str, columns: list[str]) -> None:
    """Log null counts for specified columns after transformation."""
    null_exprs = [F.sum(F.when(F.col(c).isNull(), 1).otherwise(0)).alias(c) for c in columns]
    null_counts = df.select(null_exprs).collect()[0]
    for c in columns:
        count = null_counts[c]
        if count and count > 0:
            logger.warning("[%s] Column '%s' has %d null values after transformation", table_name, c, count)
