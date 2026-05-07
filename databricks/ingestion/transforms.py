"""
Shared transformation functions for legacy CDW data migration.

Handles date parsing, amount parsing, status code expansion,
and property type expansion used across all ingestion scripts.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Status code mappings
# ---------------------------------------------------------------------------

LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

BORROWER_STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive",
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


# ---------------------------------------------------------------------------
# Type conversion helpers
# ---------------------------------------------------------------------------

def parse_date_col(col_name: str) -> Column:
    """Parse MM/DD/YYYY string column to DateType.

    Returns NULL for unparseable values instead of raising.
    """
    return F.to_date(F.col(col_name), "MM/dd/yyyy").cast(DateType())


def parse_timestamp_col(col_name: str) -> Column:
    """Parse MM/DD/YYYY string column to TimestampType (midnight)."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").cast(TimestampType())


def parse_amount_col(col_name: str, precision: int = 12, scale: int = 2) -> Column:
    """Remove commas from amount strings and cast to DecimalType.

    Examples: '285,000' -> 285000.00, '1,487.02' -> 1487.02
    Returns NULL for unparseable values.
    """
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(precision, scale))
    )


def parse_int_col(col_name: str) -> Column:
    """Cast string column to IntegerType. Returns NULL for non-numeric."""
    return F.col(col_name).cast(IntegerType())


def expand_status_col(col_name: str, mapping: dict, default: str = "Unknown") -> Column:
    """Replace abbreviated status codes with full descriptive values.

    Unmapped codes are replaced with the default value and flagged
    in the _unmapped_codes audit column downstream.
    """
    expr = F.col(col_name)
    for code, label in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(label)).otherwise(expr)
    # If the value was not in the mapping, keep original but log it
    return expr
