"""
Shared transformation utilities for legacy CDW to modern Delta Lake migration.

Handles date parsing, amount parsing, status code expansion, and null-safe
conversions used across all ingestion scripts.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType

# ---------------------------------------------------------------------------
# Status code expansion maps
# ---------------------------------------------------------------------------
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

PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}


def expand_status(col: Column, mapping: dict, default: str = "UNKNOWN") -> Column:
    """Replace abbreviated status codes with full descriptions via a CASE chain."""
    expr = F.lit(default)
    for code, expanded in mapping.items():
        expr = F.when(F.upper(F.trim(col)) == code, F.lit(expanded)).otherwise(expr)
    return expr


def expand_status_bool(col: Column, mapping: dict, default: bool = False) -> Column:
    """Replace abbreviated status codes with boolean values."""
    expr = F.lit(default)
    for code, val in mapping.items():
        expr = F.when(F.upper(F.trim(col)) == code, F.lit(val)).otherwise(expr)
    return expr


def parse_date_mmddyyyy(col: Column) -> Column:
    """Parse a MM/DD/YYYY string column into DateType. Returns null on failure."""
    return F.to_date(F.trim(col), "MM/dd/yyyy").cast(DateType())


def parse_timestamp_mmddyyyy(col: Column) -> Column:
    """Parse a MM/DD/YYYY string column into TimestampType (midnight)."""
    return F.to_timestamp(F.trim(col), "MM/dd/yyyy").cast(TimestampType())


def parse_amount(col: Column, precision: int = 12, scale: int = 2) -> Column:
    """
    Remove commas from a string amount and cast to DecimalType.
    E.g. '285,000' -> 285000.00, '1,487.02' -> 1487.02
    Returns null for empty/malformed values.
    """
    cleaned = F.regexp_replace(F.trim(col), ",", "")
    return cleaned.cast(DecimalType(precision, scale))


def parse_int(col: Column) -> Column:
    """Parse a string column to IntegerType. Returns null on failure."""
    return F.trim(col).cast(IntegerType())


def tag_load_metadata(source_system: str) -> list:
    """Return metadata columns to append to every ingested DataFrame."""
    return [
        F.current_timestamp().alias("_load_timestamp"),
        F.lit(source_system).alias("_source_system"),
    ]
