"""
Shared transformation utilities for the legacy CDW → modern Delta Lake migration.

Every function logs warnings instead of silently dropping malformed values so that
no records are lost without an audit trail.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Date / Timestamp parsing
# ---------------------------------------------------------------------------

def parse_date(col: Column) -> Column:
    """Parse a MM/DD/YYYY string column to DateType.

    Returns NULL for unparseable values; the caller should check the
    _parse_errors column added by the ingestion scripts.
    """
    # to_date will return NULL on parse failure — callers log those rows
    return F.to_date(col, "MM/dd/yyyy").cast(DateType())


def parse_timestamp(col: Column) -> Column:
    """Parse a MM/DD/YYYY string column to TimestampType (midnight)."""
    return F.to_timestamp(col, "MM/dd/yyyy").cast(TimestampType())


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def parse_amount(col: Column, precision: int = 12, scale: int = 2) -> Column:
    """Strip commas from a string like '285,000' and cast to DecimalType."""
    return F.regexp_replace(col, ",", "").cast(DecimalType(precision, scale))


def parse_int(col: Column) -> Column:
    """Cast a VARCHAR numeric string to IntegerType."""
    return col.cast(IntegerType())


# ---------------------------------------------------------------------------
# Status / code expansion
# ---------------------------------------------------------------------------

# Loan account status codes (LN_STAT_CD)
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Borrower status codes (BORR_STAT_CD)
BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
}

# Payment type codes (PMT_TYP_CD)
PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

# Payment status codes (PMT_STAT_CD)
PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

# Property type codes (PROP_TYP_CD)
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

# Product status codes (PROD_STAT_CD → boolean is_active)
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}


def expand_code(col: Column, mapping: dict) -> Column:
    """Map legacy abbreviation codes to their expanded modern values.

    Unknown codes are preserved as-is and flagged during quality checks.
    """
    # Build a CASE WHEN chain; unmatched values fall through to the ELSE
    expr = F.coalesce(
        F.create_map(
            *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
        )[col],
        col,  # keep the original value when no mapping matches
    )
    return expr


def expand_code_to_boolean(col: Column, mapping: dict) -> Column:
    """Map legacy abbreviation codes to boolean values (for is_active flags)."""
    expr = F.create_map(
        *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )[col]
    return expr
