"""
Shared PySpark transformation utilities for legacy CDW data migration.

Provides reusable UDFs and column expressions for:
- Date parsing (MM/DD/YYYY → DateType)
- Amount parsing (comma-separated strings → DecimalType)
- Status code expansion (short codes → human-readable values)
- Null-safe string operations
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, BooleanType

import sys
sys.path.insert(0, "..")
from config.pipeline_config import LEGACY_DATE_FORMAT


def parse_legacy_date(col: Column) -> Column:
    """
    Convert legacy MM/dd/yyyy string dates to proper DateType.
    Returns null for unparseable or null inputs.
    """
    return F.to_date(F.trim(col), LEGACY_DATE_FORMAT)


def parse_legacy_timestamp(col: Column) -> Column:
    """
    Convert legacy MM/dd/yyyy string dates to TimestampType.
    Defaults to midnight (00:00:00) since legacy has no time component.
    """
    return F.to_timestamp(F.trim(col), LEGACY_DATE_FORMAT)


def parse_legacy_amount(col: Column) -> Column:
    """
    Parse legacy amount strings (with commas and optional $ sign) to DecimalType.
    Examples: '285,000' → 285000.00, '$1,487.02' → 1487.02
    Returns 0.00 for null/unparseable values.
    """
    # Strip dollar sign, commas, whitespace, then cast to decimal
    cleaned = F.regexp_replace(F.trim(F.coalesce(col, F.lit("0"))), r"[$,]", "")
    return F.coalesce(cleaned.cast(DecimalType(12, 2)), F.lit(0).cast(DecimalType(12, 2)))


def parse_legacy_integer(col: Column) -> Column:
    """
    Parse legacy VARCHAR integer fields to IntegerType.
    Returns null for non-numeric values.
    """
    return F.trim(col).cast(IntegerType())


def parse_legacy_rate(col: Column) -> Column:
    """
    Parse legacy interest rate strings to DecimalType(5,3).
    Example: '4.750' → 4.750
    """
    return F.trim(col).cast(DecimalType(5, 3))


def parse_legacy_percent(col: Column) -> Column:
    """
    Parse legacy percentage strings to DecimalType(5,2).
    Example: '82.5' → 82.50
    """
    return F.trim(col).cast(DecimalType(5, 2))


def expand_status_code(col: Column, mapping: dict) -> Column:
    """
    Map legacy short status codes to expanded human-readable values.
    Falls back to original value if code not found in mapping.
    """
    # Build a CASE WHEN expression from the mapping dict
    expr = col
    for code, expanded in mapping.items():
        expr = F.when(F.upper(F.trim(col)) == code, F.lit(expanded)).otherwise(expr)
    # Final: use the last chained .otherwise as the expression
    # Re-implement as a proper chain:
    result = F.lit(None).cast("string")
    for code, expanded in mapping.items():
        result = F.when(F.upper(F.trim(col)) == code, F.lit(expanded)).otherwise(result)
    # If none matched, return trimmed original
    return F.coalesce(result, F.trim(col))


def status_to_boolean(col: Column, active_code: str = "ACT") -> Column:
    """
    Convert status code to boolean (ACT → true, anything else → false).
    Used for loan_products.is_active conversion.
    """
    return F.when(F.upper(F.trim(col)) == active_code, F.lit(True)).otherwise(F.lit(False))


def null_safe_concat(*cols: Column, separator: str = " ") -> Column:
    """
    Concatenate columns with a separator, skipping nulls.
    Useful for building full names from first/middle/last.
    """
    return F.concat_ws(separator, *[F.coalesce(c, F.lit("")) for c in cols])
