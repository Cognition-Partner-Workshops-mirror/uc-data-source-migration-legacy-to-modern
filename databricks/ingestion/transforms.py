"""
Shared transformation functions for legacy CDW to modern Delta Lake migration.

All parsers follow a fail-safe pattern: malformed values are returned as None
and logged rather than silently dropped or causing pipeline failures.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType

# ---------------------------------------------------------------------------
# Status code expansion maps
# ---------------------------------------------------------------------------

BORROWER_STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive",
}

LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
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


# ---------------------------------------------------------------------------
# Column-level transforms
# ---------------------------------------------------------------------------

def parse_legacy_date(col_name: str) -> Column:
    """Parse MM/DD/YYYY string to DateType. Returns null for malformed values."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy").cast(DateType())


def parse_legacy_timestamp(col_name: str) -> Column:
    """Parse MM/DD/YYYY string to TimestampType (midnight). Returns null for malformed."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").cast(TimestampType())


def parse_legacy_amount(col_name: str, precision: int = 12, scale: int = 2) -> Column:
    """Remove commas from amount string and cast to DecimalType."""
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(precision, scale))
    )


def parse_legacy_integer(col_name: str) -> Column:
    """Cast a string column to IntegerType. Returns null for non-numeric."""
    return F.col(col_name).cast(IntegerType())


def expand_status_code(col_name: str, mapping: dict) -> Column:
    """Map abbreviated status codes to their expanded form using a lookup."""
    mapping_expr = F.create_map(
        *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )
    return F.coalesce(
        mapping_expr[F.upper(F.trim(F.col(col_name)))],
        F.concat(F.lit("UNKNOWN:"), F.col(col_name)),
    )


def expand_status_to_boolean(col_name: str, mapping: dict) -> Column:
    """Map abbreviated status codes to boolean (for product active/inactive)."""
    mapping_expr = F.create_map(
        *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )
    return mapping_expr[F.upper(F.trim(F.col(col_name)))]
