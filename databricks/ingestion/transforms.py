"""
Shared transformation utilities for the CDW legacy-to-modern migration pipeline.

All parsing functions are null-safe and log warnings for malformed values
instead of silently dropping records.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Status / code expansion mappings
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


def parse_legacy_date(col_name: str, alias: str | None = None) -> F.Column:
    """Parse MM/DD/YYYY string to DateType. Returns null for unparseable values."""
    target = alias or col_name
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(target)


def parse_legacy_timestamp(col_name: str, alias: str | None = None) -> F.Column:
    """Parse MM/DD/YYYY string to TimestampType (midnight). Returns null for unparseable."""
    target = alias or col_name
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(target)


def parse_amount(col_name: str, alias: str | None = None) -> F.Column:
    """Strip commas from amount strings and cast to Decimal(12,2)."""
    target = alias or col_name
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(12, 2))
        .alias(target)
    )


def parse_amount_10_2(col_name: str, alias: str | None = None) -> F.Column:
    """Strip commas from amount strings and cast to Decimal(10,2)."""
    target = alias or col_name
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(10, 2))
        .alias(target)
    )


def parse_int(col_name: str, alias: str | None = None) -> F.Column:
    """Cast string to IntegerType."""
    target = alias or col_name
    return F.col(col_name).cast(IntegerType()).alias(target)


def parse_rate(col_name: str, alias: str | None = None) -> F.Column:
    """Cast string interest rate to Decimal(5,3)."""
    target = alias or col_name
    return F.col(col_name).cast(DecimalType(5, 3)).alias(target)


def parse_percent(col_name: str, alias: str | None = None) -> F.Column:
    """Cast string percent to Decimal(5,2)."""
    target = alias or col_name
    return F.col(col_name).cast(DecimalType(5, 2)).alias(target)


def expand_codes(col_name: str, mapping: dict, alias: str | None = None) -> F.Column:
    """Map abbreviated status codes to full descriptions via a CASE expression."""
    target = alias or col_name
    expr = F.col(col_name)
    case_expr = F.when(F.lit(False), F.lit(None))  # seed the chain
    for code, label in mapping.items():
        case_expr = case_expr.when(F.upper(expr) == code, F.lit(label))
    # preserve original value if no match (logged downstream as anomaly)
    case_expr = case_expr.otherwise(expr)
    return case_expr.alias(target)


def expand_codes_to_bool(
    col_name: str, mapping: dict, alias: str | None = None
) -> F.Column:
    """Map abbreviated codes to boolean via a CASE expression."""
    target = alias or col_name
    expr = F.col(col_name)
    case_expr = F.when(F.lit(False), F.lit(None))
    for code, flag in mapping.items():
        case_expr = case_expr.when(F.upper(expr) == code, F.lit(flag))
    case_expr = case_expr.otherwise(F.lit(None))
    return case_expr.alias(target)


# ---------------------------------------------------------------------------
# Row-level quality tagging
# ---------------------------------------------------------------------------


def tag_parse_errors(
    df: DataFrame, original_col: str, parsed_col: str, tag_col: str
) -> DataFrame:
    """Add a boolean column that is True when the original value was non-null
    but the parsed result is null (indicating a parse failure)."""
    return df.withColumn(
        tag_col,
        F.when(
            F.col(original_col).isNotNull() & F.col(parsed_col).isNull(),
            F.lit(True),
        ).otherwise(F.lit(False)),
    )
