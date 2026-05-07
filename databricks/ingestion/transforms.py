"""
Shared transformation utilities for legacy CDW → modern Delta Lake migration.

Handles:
  - Date parsing (MM/DD/YYYY string → DateType / TimestampType)
  - Amount parsing (comma-formatted strings → DecimalType)
  - Status code expansion (ACT → Active, etc.)
  - Safe integer parsing with null handling
"""

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Status-code lookup maps
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
# Column-level transform helpers
# ---------------------------------------------------------------------------

def parse_legacy_date(col_name: str):
    """Parse MM/DD/YYYY string into DateType. Returns null for unparseable values."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_timestamp(col_name: str):
    """Parse MM/DD/YYYY string into TimestampType (midnight)."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_amount(col_name: str, precision: int = 12, scale: int = 2):
    """Remove commas from amount strings and cast to DecimalType."""
    return F.regexp_replace(F.col(col_name), ",", "").cast(DecimalType(precision, scale))


def parse_legacy_int(col_name: str):
    """Cast string column to IntegerType. Returns null for non-numeric values."""
    return F.col(col_name).cast(IntegerType())


def expand_status_code(col_name: str, mapping: dict, default: str = "Unknown"):
    """Map abbreviated status codes to expanded values using a dictionary."""
    mapping_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])
    return F.coalesce(mapping_expr[F.trim(F.col(col_name))], F.lit(default))


def expand_status_code_bool(col_name: str, mapping: dict, default: bool = False):
    """Map abbreviated status codes to boolean values."""
    mapping_expr = F.create_map(
        [F.lit(x) for kv in mapping.items() for x in (kv[0], kv[1])]
    )
    return F.coalesce(mapping_expr[F.trim(F.col(col_name))], F.lit(default))
