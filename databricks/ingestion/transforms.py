"""
Reusable transformation helpers for the legacy CDW → modern Delta Lake migration.

Every function is a pure PySpark column expression so it can be used inside
.withColumn() / .select() without side effects.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Date / Timestamp parsing
# ---------------------------------------------------------------------------

def parse_date(col: Column) -> Column:
    """Parse a legacy MM/DD/YYYY string into a Spark DateType.

    Returns NULL for empty strings, whitespace-only strings, and unparseable
    values — the caller should log these via the quarantine mechanism rather
    than silently dropping them.
    """
    trimmed = F.trim(col)
    return (
        F.when(trimmed.isNull() | (trimmed == F.lit("")), F.lit(None).cast(DateType()))
         .otherwise(F.to_date(trimmed, "MM/dd/yyyy"))
    )


def parse_timestamp(col: Column) -> Column:
    """Parse a legacy MM/DD/YYYY string into a Spark TimestampType.

    For legacy columns that only store a date but map to a modern TIMESTAMP.
    Midnight is used as the time component.
    """
    trimmed = F.trim(col)
    return (
        F.when(trimmed.isNull() | (trimmed == F.lit("")), F.lit(None).cast(TimestampType()))
         .otherwise(F.to_timestamp(trimmed, "MM/dd/yyyy"))
    )


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def parse_amount(col: Column, precision: int = 12, scale: int = 2) -> Column:
    """Parse a legacy amount string like '285,000' or '1,487.02' into DecimalType.

    Strips commas, trims whitespace, and casts. Non-numeric values become NULL.
    """
    cleaned = F.regexp_replace(F.trim(col), ",", "")
    return (
        F.when(cleaned.isNull() | (cleaned == F.lit("")), F.lit(None).cast(DecimalType(precision, scale)))
         .otherwise(cleaned.cast(DecimalType(precision, scale)))
    )


def parse_int(col: Column) -> Column:
    """Parse a legacy string integer (e.g. '360', '15') into IntegerType."""
    trimmed = F.trim(col)
    return (
        F.when(trimmed.isNull() | (trimmed == F.lit("")), F.lit(None).cast(IntegerType()))
         .otherwise(trimmed.cast(IntegerType()))
    )


def parse_rate(col: Column) -> Column:
    """Parse an interest-rate string like '5.250' into DECIMAL(5,3)."""
    return parse_amount(col, precision=5, scale=3)


def parse_percent(col: Column) -> Column:
    """Parse a percentage string like '82.5' into DECIMAL(5,2)."""
    return parse_amount(col, precision=5, scale=2)


# ---------------------------------------------------------------------------
# Status / code expansion
# ---------------------------------------------------------------------------

# Loan account status codes
LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

# Borrower status codes
BORROWER_STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive",
}

# Loan product status codes → boolean-style
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}

# Payment type codes
PAYMENT_TYPE_MAP = {
    "REG": "Regular",
    "EXT": "Extra",
    "PRT": "Partial",
    "PRE": "Prepayment",
}

# Payment status codes
PAYMENT_STATUS_MAP = {
    "PST": "Posted",
    "REV": "Reversed",
    "NSF": "NSF",
    "PND": "Pending",
}

# Property type codes
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


def expand_code(col: Column, mapping: dict, default: str = "Unknown") -> Column:
    """Map a legacy abbreviation to its expanded value using a dictionary.

    Unrecognised codes are mapped to *default* rather than NULL so the record
    is preserved and the anomaly is visible in quality checks.
    """
    trimmed = F.upper(F.trim(col))
    expr = F.lit(default)
    for code, value in mapping.items():
        expr = F.when(trimmed == F.lit(code), F.lit(str(value))).otherwise(expr)
    return F.when(col.isNull(), F.lit(None)).otherwise(expr)


def expand_to_boolean(col: Column, true_code: str = "ACT") -> Column:
    """Map a legacy status code to a Boolean (ACT → true, anything else → false)."""
    trimmed = F.upper(F.trim(col))
    return F.when(col.isNull(), F.lit(None)).otherwise(trimmed == F.lit(true_code))
