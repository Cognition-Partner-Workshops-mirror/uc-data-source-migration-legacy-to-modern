"""
Shared transformation utilities for the legacy CDW migration pipeline.

All helpers are pure functions operating on PySpark columns so they can be
reused across every ingestion module.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, IntegerType

# ---------------------------------------------------------------------------
# Date / timestamp parsing
# ---------------------------------------------------------------------------

def parse_date(col: Column) -> Column:
    """Parse a legacy MM/DD/YYYY string into a Spark DateType."""
    return F.to_date(F.trim(col), "MM/dd/yyyy")


def parse_timestamp(col: Column) -> Column:
    """Parse a legacy MM/DD/YYYY string into a Spark TimestampType (midnight)."""
    return F.to_timestamp(F.trim(col), "MM/dd/yyyy")


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def parse_amount(col: Column, precision: int = 12, scale: int = 2) -> Column:
    """Remove commas from a string amount and cast to DecimalType."""
    return F.regexp_replace(F.trim(col), ",", "").cast(DecimalType(precision, scale))


def parse_int(col: Column) -> Column:
    """Cast a string column to IntegerType, returning null for non-numeric values."""
    return F.trim(col).cast(IntegerType())


def parse_rate(col: Column, precision: int = 5, scale: int = 3) -> Column:
    """Parse a string rate (e.g. '5.250') to DecimalType."""
    return F.trim(col).cast(DecimalType(precision, scale))


def parse_percent(col: Column, precision: int = 5, scale: int = 2) -> Column:
    """Parse a string percentage (e.g. '82.5') to DecimalType."""
    return F.trim(col).cast(DecimalType(precision, scale))


# ---------------------------------------------------------------------------
# Status / code expansion
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

PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
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


def expand_status(col: Column, mapping: dict) -> Column:
    """Map abbreviated status codes to their expanded values.

    Unknown codes are preserved as-is and flagged with a '_UNKNOWN' suffix so
    they surface in data-quality checks rather than being silently dropped.
    """
    expr = F.coalesce(
        F.create_map(
            *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
        )[F.upper(F.trim(col))],
        F.concat(F.upper(F.trim(col)), F.lit("_UNKNOWN")),
    )
    return F.when(col.isNull(), F.lit(None)).otherwise(expr)


def expand_status_to_bool(col: Column, mapping: dict) -> Column:
    """Map abbreviated status codes to boolean values."""
    expr = F.create_map(
        *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )[F.upper(F.trim(col))]
    return F.when(col.isNull(), F.lit(None)).otherwise(expr)
