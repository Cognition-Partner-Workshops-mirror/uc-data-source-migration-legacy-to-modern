"""
Shared transformation helpers used by all ingestion notebooks.

All functions are pure PySpark Column expressions so they can be used inside
`withColumn` / `select` calls without collecting data to the driver.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql import types as T


# ---------------------------------------------------------------------------
# Date / Timestamp parsing
# ---------------------------------------------------------------------------

def parse_date_mmddyyyy(col: Column) -> Column:
    """Convert a MM/DD/YYYY string column to DateType.

    Returns NULL for blank or unparseable values.
    """
    trimmed = F.trim(col)
    return F.when(
        (trimmed.isNull()) | (trimmed == F.lit("")),
        F.lit(None).cast(T.DateType()),
    ).otherwise(
        F.to_date(trimmed, "MM/dd/yyyy")
    )


def parse_timestamp_mmddyyyy(col: Column) -> Column:
    """Convert a MM/DD/YYYY string column to TimestampType (midnight)."""
    trimmed = F.trim(col)
    return F.when(
        (trimmed.isNull()) | (trimmed == F.lit("")),
        F.lit(None).cast(T.TimestampType()),
    ).otherwise(
        F.to_timestamp(trimmed, "MM/dd/yyyy")
    )


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def parse_amount(col: Column, precision: int = 12, scale: int = 2) -> Column:
    """Remove commas from an amount string and cast to DecimalType.

    Example: '285,000' -> 285000.00, '271,432.56' -> 271432.56
    Returns NULL for blank / unparseable values.
    """
    decimal_type = T.DecimalType(precision, scale)
    trimmed = F.trim(col)
    return F.when(
        (trimmed.isNull()) | (trimmed == F.lit("")),
        F.lit(None).cast(decimal_type),
    ).otherwise(
        F.regexp_replace(trimmed, ",", "").cast(decimal_type)
    )


def parse_int(col: Column) -> Column:
    """Cast a string column to IntegerType, returning NULL on failure."""
    trimmed = F.trim(col)
    return F.when(
        (trimmed.isNull()) | (trimmed == F.lit("")),
        F.lit(None).cast(T.IntegerType()),
    ).otherwise(
        F.regexp_replace(trimmed, ",", "").cast(T.IntegerType())
    )


def parse_rate(col: Column, precision: int = 5, scale: int = 3) -> Column:
    """Cast a rate string (e.g. '4.750') to DecimalType."""
    decimal_type = T.DecimalType(precision, scale)
    trimmed = F.trim(col)
    return F.when(
        (trimmed.isNull()) | (trimmed == F.lit("")),
        F.lit(None).cast(decimal_type),
    ).otherwise(
        trimmed.cast(decimal_type)
    )


# ---------------------------------------------------------------------------
# Status-code expansion look-ups
# ---------------------------------------------------------------------------

_BORROWER_STATUS = {"ACT": "Active", "INA": "Inactive"}
_LOAN_STATUS = {"ACT": "Active", "CLO": "Closed", "DFT": "Default", "FRB": "Forbearance"}
_PRODUCT_STATUS = {"ACT": True, "INA": False}
_PAYMENT_TYPE = {"REG": "Regular", "EXT": "Extra", "PRT": "Partial", "PRE": "Prepayment"}
_PAYMENT_STATUS = {"PST": "Posted", "REV": "Reversed", "NSF": "NSF", "PND": "Pending"}
_PROPERTY_TYPE = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


def _build_when_chain(col: Column, mapping: dict, default: Column | None = None) -> Column:
    """Build a chained WHEN expression from a dict mapping."""
    expr = F
    chain = None
    for code, expanded in mapping.items():
        condition = F.upper(F.trim(col)) == F.lit(code)
        value = F.lit(expanded)
        if chain is None:
            chain = F.when(condition, value)
        else:
            chain = chain.when(condition, value)
    if default is not None:
        chain = chain.otherwise(default)
    else:
        chain = chain.otherwise(F.concat(F.lit("UNKNOWN("), col, F.lit(")")))
    return chain


def expand_borrower_status(col: Column) -> Column:
    return _build_when_chain(col, _BORROWER_STATUS)


def expand_loan_status(col: Column) -> Column:
    return _build_when_chain(col, _LOAN_STATUS)


def expand_product_status_to_bool(col: Column) -> Column:
    """Convert product status code to boolean is_active flag."""
    trimmed = F.upper(F.trim(col))
    return F.when(trimmed == F.lit("ACT"), F.lit(True)).otherwise(F.lit(False))


def expand_payment_type(col: Column) -> Column:
    return _build_when_chain(col, _PAYMENT_TYPE)


def expand_payment_status(col: Column) -> Column:
    return _build_when_chain(col, _PAYMENT_STATUS)


def expand_property_type(col: Column) -> Column:
    return _build_when_chain(col, _PROPERTY_TYPE)
