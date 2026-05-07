"""
Shared transformation helpers for the CDW legacy-to-modern migration.

All functions operate on PySpark columns or DataFrames and are imported by
the table-specific ingestion scripts.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType

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

PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

PRODUCT_STATUS_MAP = {"ACT": True, "INA": False}


# ---------------------------------------------------------------------------
# Column-level transforms
# ---------------------------------------------------------------------------
def parse_legacy_date(col_name: str) -> Column:
    """Convert a MM/DD/YYYY VARCHAR string to a Spark DateType."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy").cast(DateType())


def parse_legacy_timestamp(col_name: str) -> Column:
    """Convert a MM/DD/YYYY VARCHAR string to a Spark TimestampType (midnight)."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").cast(TimestampType())


def parse_legacy_amount(col_name: str, precision: int = 12, scale: int = 2) -> Column:
    """Strip commas from a VARCHAR amount and cast to DecimalType."""
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(precision, scale))
    )


def parse_legacy_int(col_name: str) -> Column:
    """Cast a VARCHAR numeric string to IntegerType."""
    return F.col(col_name).cast(IntegerType())


def expand_status_code(col_name: str, mapping: dict, default: str = "Unknown") -> Column:
    """Map a short status code to its expanded readable value."""
    expr = F.col(col_name)
    for code, expanded in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(expanded)).otherwise(expr)
    # Final fallback for unmapped codes
    return F.when(expr == F.col(col_name), F.lit(default)).otherwise(expr)


def expand_status_code_preserving(col_name: str, mapping: dict) -> Column:
    """Map a short status code; keep original value if no mapping exists."""
    expr = F.col(col_name)
    for code, expanded in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(expanded)).otherwise(expr)
    return expr


def expand_status_to_boolean(col_name: str, mapping: dict, default: bool = False) -> Column:
    """Map a status code to a boolean value."""
    expr = F.lit(default)
    for code, value in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(value)).otherwise(expr)
    return expr
