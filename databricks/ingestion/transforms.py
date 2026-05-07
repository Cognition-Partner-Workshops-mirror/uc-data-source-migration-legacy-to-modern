"""
Shared transformation functions for the CDW legacy-to-modern migration.

All parsing helpers accept raw VARCHAR strings from the legacy CDW tables and
return properly typed PySpark column expressions. Malformed values are coerced
to ``None`` so that the data quality framework can flag them downstream rather
than silently dropping entire rows.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_date(col_name: str) -> Column:
    """Convert a MM/DD/YYYY string column to DateType.

    Returns ``None`` for null or unparseable values.
    """
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(col_name)


def parse_timestamp(col_name: str) -> Column:
    """Convert a MM/DD/YYYY string column to TimestampType (midnight)."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(col_name)


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def parse_amount(col_name: str, precision: int = 12, scale: int = 2) -> Column:
    """Strip commas from an amount string and cast to DecimalType.

    Examples: ``"285,000"`` → 285000.00, ``"1,487.02"`` → 1487.02
    """
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(precision, scale))
        .alias(col_name)
    )


def parse_int(col_name: str) -> Column:
    """Cast a string column to IntegerType."""
    return F.col(col_name).cast(IntegerType()).alias(col_name)


def parse_rate(col_name: str, precision: int = 5, scale: int = 3) -> Column:
    """Cast a rate string (e.g. ``"4.750"``) to DecimalType."""
    return F.col(col_name).cast(DecimalType(precision, scale)).alias(col_name)


def parse_percent(col_name: str, precision: int = 5, scale: int = 2) -> Column:
    """Cast a percentage string (e.g. ``"82.5"``) to DecimalType."""
    return F.col(col_name).cast(DecimalType(precision, scale)).alias(col_name)


# ---------------------------------------------------------------------------
# Status code expansion
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


def expand_status(col_name: str, mapping: dict, alias: str | None = None) -> Column:
    """Map short status codes to their full descriptions using a CASE expression.

    Unknown codes are preserved as-is and prefixed with ``UNKNOWN:`` so the
    quality framework can detect them.
    """
    expr = F.col(col_name)
    case_expr = F.when(expr.isNull(), F.lit(None))
    for code, label in mapping.items():
        if isinstance(label, bool):
            case_expr = case_expr.when(expr == code, F.lit(label))
        else:
            case_expr = case_expr.when(expr == code, F.lit(label))
    case_expr = case_expr.otherwise(F.concat(F.lit("UNKNOWN:"), expr))
    return case_expr.alias(alias or col_name)


def expand_product_active(col_name: str) -> Column:
    """Convert product status code to boolean is_active flag."""
    expr = F.col(col_name)
    return (
        F.when(expr == "ACT", F.lit(True))
        .when(expr == "INA", F.lit(False))
        .otherwise(F.lit(None))
        .alias("is_active")
    )
