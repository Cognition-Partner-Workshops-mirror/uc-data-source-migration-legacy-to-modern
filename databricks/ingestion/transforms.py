"""
Shared transformation utilities for the CDW legacy-to-modern migration.

Handles:
- Date string parsing (MM/DD/YYYY -> DateType/TimestampType)
- Amount string parsing ("285,000" -> DecimalType)
- Status code expansion (ACT -> Active, CLO -> Closed, etc.)
- Property type expansion (SFR -> Single Family, etc.)
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# -----------------------------------------------------------------------------
# Status Code Mappings
# -----------------------------------------------------------------------------

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


# -----------------------------------------------------------------------------
# Date Transformations
# -----------------------------------------------------------------------------

def parse_date(col_name: str) -> Column:
    """
    Parse a legacy date string in MM/DD/YYYY format to DateType.
    Returns NULL for empty strings or malformed dates (logged via monitoring).
    """
    trimmed = F.trim(F.col(col_name))
    return F.when(
        (trimmed.isNull()) | (trimmed == "") | (F.length(trimmed) < 8),
        F.lit(None).cast(DateType())
    ).otherwise(
        F.to_date(trimmed, "MM/dd/yyyy")
    )


def parse_timestamp(col_name: str) -> Column:
    """
    Parse a legacy date string in MM/DD/YYYY format to TimestampType.
    Timestamp is set to midnight (00:00:00) of the parsed date.
    Returns NULL for empty strings or malformed dates.
    """
    trimmed = F.trim(F.col(col_name))
    return F.when(
        (trimmed.isNull()) | (trimmed == "") | (F.length(trimmed) < 8),
        F.lit(None).cast(TimestampType())
    ).otherwise(
        F.to_timestamp(trimmed, "MM/dd/yyyy")
    )


# -----------------------------------------------------------------------------
# Amount/Numeric Transformations
# -----------------------------------------------------------------------------

def parse_amount(col_name: str, precision: int = 12, scale: int = 2) -> Column:
    """
    Parse a legacy amount string (e.g., "285,000" or "1,487.02") to DecimalType.
    Removes commas and dollar signs before casting.
    Returns NULL for empty/malformed values.
    """
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), "[,$]", "")
    return F.when(
        (cleaned.isNull()) | (cleaned == "") | (cleaned == "null"),
        F.lit(None).cast(DecimalType(precision, scale))
    ).otherwise(
        cleaned.cast(DecimalType(precision, scale))
    )


def parse_integer(col_name: str) -> Column:
    """
    Parse a legacy string to IntegerType.
    Removes commas before casting. Returns NULL for empty/malformed values.
    """
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), ",", "")
    return F.when(
        (cleaned.isNull()) | (cleaned == "") | (cleaned == "null"),
        F.lit(None).cast(IntegerType())
    ).otherwise(
        cleaned.cast(IntegerType())
    )


def parse_rate(col_name: str) -> Column:
    """
    Parse an interest rate string (e.g., "5.250") to Decimal(5,3).
    """
    trimmed = F.trim(F.col(col_name))
    return F.when(
        (trimmed.isNull()) | (trimmed == "") | (trimmed == "null"),
        F.lit(None).cast(DecimalType(5, 3))
    ).otherwise(
        trimmed.cast(DecimalType(5, 3))
    )


def parse_percent(col_name: str) -> Column:
    """
    Parse a percentage string (e.g., "82.5") to Decimal(5,2).
    """
    trimmed = F.trim(F.col(col_name))
    return F.when(
        (trimmed.isNull()) | (trimmed == "") | (trimmed == "null"),
        F.lit(None).cast(DecimalType(5, 2))
    ).otherwise(
        trimmed.cast(DecimalType(5, 2))
    )


# -----------------------------------------------------------------------------
# Status/Code Expansion
# -----------------------------------------------------------------------------

def expand_status(col_name: str, mapping: dict) -> Column:
    """
    Expand a legacy status code abbreviation to its full form using
    a CASE WHEN expression built from the provided mapping dict.
    Unknown codes are preserved as-is with a '_UNMAPPED' suffix for investigation.
    """
    trimmed = F.upper(F.trim(F.col(col_name)))
    expr = F.when(trimmed.isNull(), F.lit(None))
    for code, expanded in mapping.items():
        if isinstance(expanded, bool):
            expr = expr.when(trimmed == code, F.lit(expanded))
        else:
            expr = expr.when(trimmed == code, F.lit(expanded))
    # Unknown codes: preserve with suffix for data quality flagging
    expr = expr.otherwise(F.concat(trimmed, F.lit("_UNMAPPED")))
    return expr


# -----------------------------------------------------------------------------
# Flagging / Error Logging
# -----------------------------------------------------------------------------

def flag_parse_errors(df, col_name: str, expected_type: str):
    """
    Add a boolean column indicating rows where a parse would fail.
    Useful for pre-migration data profiling.
    """
    flag_col = f"_parse_error_{col_name}"
    if expected_type == "date":
        parsed = parse_date(col_name)
        return df.withColumn(flag_col, parsed.isNull() & F.col(col_name).isNotNull())
    elif expected_type == "decimal":
        parsed = parse_amount(col_name)
        return df.withColumn(flag_col, parsed.isNull() & F.col(col_name).isNotNull())
    elif expected_type == "integer":
        parsed = parse_integer(col_name)
        return df.withColumn(flag_col, parsed.isNull() & F.col(col_name).isNotNull())
    return df
