"""
Shared transformation functions for the CDW legacy-to-modern migration.

All parsing, code-expansion, and type-conversion logic lives here so that
ingestion scripts and quality checks can reuse the same definitions.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Date / Timestamp parsing
# ---------------------------------------------------------------------------

def parse_date(col_name: str) -> Column:
    """Parse a MM/DD/YYYY VARCHAR column to DateType.

    Returns NULL for empty strings, whitespace-only strings, and
    values that do not match the expected format.
    """
    trimmed = F.trim(F.col(col_name))
    cleaned = F.when(
        (trimmed == "") | trimmed.isNull(), F.lit(None)
    ).otherwise(trimmed)
    return F.to_date(cleaned, "MM/dd/yyyy").cast(DateType())


def parse_timestamp(col_name: str) -> Column:
    """Parse a MM/DD/YYYY VARCHAR column to TimestampType (midnight)."""
    trimmed = F.trim(F.col(col_name))
    cleaned = F.when(
        (trimmed == "") | trimmed.isNull(), F.lit(None)
    ).otherwise(trimmed)
    return F.to_timestamp(cleaned, "MM/dd/yyyy").cast(TimestampType())


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def parse_amount(col_name: str, precision: int = 12, scale: int = 2) -> Column:
    """Parse a comma-formatted amount string (e.g. '285,000') to DecimalType.

    Strips commas, dollar signs, and whitespace before casting.
    Returns NULL for empty / non-numeric values.
    """
    stripped = F.regexp_replace(F.trim(F.col(col_name)), r"[$,]", "")
    cleaned = F.when(
        (stripped == "") | stripped.isNull(), F.lit(None)
    ).otherwise(stripped)
    return cleaned.cast(DecimalType(precision, scale))


def parse_int(col_name: str) -> Column:
    """Parse a VARCHAR column to IntegerType.

    Strips whitespace; returns NULL for empty / non-numeric values.
    """
    trimmed = F.trim(F.col(col_name))
    cleaned = F.when(
        (trimmed == "") | trimmed.isNull(), F.lit(None)
    ).otherwise(trimmed)
    return cleaned.cast(IntegerType())


def parse_rate(col_name: str) -> Column:
    """Parse an interest-rate string (e.g. '5.250') to DECIMAL(5,3)."""
    trimmed = F.trim(F.col(col_name))
    cleaned = F.when(
        (trimmed == "") | trimmed.isNull(), F.lit(None)
    ).otherwise(trimmed)
    return cleaned.cast(DecimalType(5, 3))


def parse_percent(col_name: str) -> Column:
    """Parse a percentage string (e.g. '82.5') to DECIMAL(5,2)."""
    trimmed = F.trim(F.col(col_name))
    cleaned = F.when(
        (trimmed == "") | trimmed.isNull(), F.lit(None)
    ).otherwise(trimmed)
    return cleaned.cast(DecimalType(5, 2))


# ---------------------------------------------------------------------------
# Status / code expansion maps
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


def expand_code(col_name: str, mapping: dict, default: str = "UNKNOWN") -> Column:
    """Map abbreviated status codes to their expanded values.

    Unrecognised codes are preserved with a configurable default prefix so they
    are visible in quality checks rather than silently dropped.
    """
    trimmed = F.upper(F.trim(F.col(col_name)))
    expr = F.lit(default)
    for code, expansion in mapping.items():
        expr = F.when(trimmed == code, F.lit(expansion)).otherwise(expr)
    return F.when(trimmed.isNull() | (trimmed == ""), F.lit(None)).otherwise(expr)


def expand_bool(col_name: str, mapping: dict) -> Column:
    """Map abbreviated status codes to boolean values."""
    trimmed = F.upper(F.trim(F.col(col_name)))
    expr = F.lit(None).cast("boolean")
    for code, value in mapping.items():
        expr = F.when(trimmed == code, F.lit(value)).otherwise(expr)
    return expr
