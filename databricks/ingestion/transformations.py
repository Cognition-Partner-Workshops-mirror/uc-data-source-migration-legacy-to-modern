"""
Reusable transformation helpers for the legacy-to-modern migration.

Handles:
  - Date string parsing  (MM/DD/YYYY -> DateType / TimestampType)
  - Amount string parsing ("285,000" -> DecimalType)
  - Status code expansion (ACT -> Active, CLO -> Closed, etc.)
  - Null / malformed value handling with logging
"""

import logging

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DecimalType,
    IntegerType,
)

logger = logging.getLogger("loan_migration.transformations")

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_DATE_FORMAT = "MM/dd/yyyy"


def parse_date_col(col_name: str, alias: str) -> Column:
    """Parse a MM/DD/YYYY string column to DateType."""
    return F.to_date(F.col(col_name), _DATE_FORMAT).alias(alias)


def parse_timestamp_col(col_name: str, alias: str) -> Column:
    """Parse a MM/DD/YYYY string column to TimestampType (midnight)."""
    return F.to_timestamp(F.col(col_name), _DATE_FORMAT).alias(alias)


# ---------------------------------------------------------------------------
# Amount / numeric parsing
# ---------------------------------------------------------------------------


def parse_amount_col(col_name: str, alias: str, precision: int = 12, scale: int = 2) -> Column:
    """
    Parse a comma-formatted amount string ("285,000" or "271,432.56")
    to DecimalType.  Returns null for unparseable values.
    """
    stripped = F.regexp_replace(F.col(col_name), ",", "")
    return stripped.cast(DecimalType(precision, scale)).alias(alias)


def parse_int_col(col_name: str, alias: str) -> Column:
    """Parse a string column to IntegerType. Returns null for non-numeric."""
    return F.col(col_name).cast(IntegerType()).alias(alias)


def parse_decimal_col(col_name: str, alias: str, precision: int = 5, scale: int = 2) -> Column:
    """Parse a string column to DecimalType (no comma removal needed)."""
    return F.col(col_name).cast(DecimalType(precision, scale)).alias(alias)


# ---------------------------------------------------------------------------
# Status / code expansion
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


def expand_status_col(col_name: str, mapping: dict, alias: str) -> Column:
    """
    Map abbreviated status codes to their expanded form.
    Unknown codes are preserved as-is and flagged with a _UNKNOWN suffix
    so they surface in quality checks rather than being silently dropped.
    """
    mapping_expr = F.create_map(
        *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )
    raw = F.upper(F.trim(F.col(col_name)))
    return F.coalesce(mapping_expr[raw], F.concat(raw, F.lit("_UNKNOWN"))).alias(alias)


def expand_product_status_col(col_name: str, alias: str) -> Column:
    """Map product status code to boolean is_active."""
    return (
        F.when(F.upper(F.trim(F.col(col_name))) == "ACT", F.lit(True))
        .when(F.upper(F.trim(F.col(col_name))) == "INA", F.lit(False))
        .otherwise(F.lit(None))
        .alias(alias)
    )


# ---------------------------------------------------------------------------
# Null / malformed value logging
# ---------------------------------------------------------------------------


def log_null_counts(df: DataFrame, table_name: str, required_cols: list[str]) -> dict:
    """
    Check for nulls in required columns and log warnings.
    Returns a dict of {column: null_count} for columns with nulls.
    """
    null_counts = {}
    for col_name in required_cols:
        count = df.filter(F.col(col_name).isNull()).count()
        if count > 0:
            null_counts[col_name] = count
            logger.warning(
                "Table %s: column '%s' has %d null values in required field",
                table_name, col_name, count,
            )
    return null_counts


def log_parse_failures(
    source_df: DataFrame, transformed_df: DataFrame,
    source_col: str, target_col: str, table_name: str,
) -> int:
    """
    Compare source non-null count vs transformed non-null count to detect
    parse failures (values that became null after type conversion).
    Returns count of records that failed to parse.
    """
    source_non_null = source_df.filter(
        F.col(source_col).isNotNull() & (F.trim(F.col(source_col)) != "")
    ).count()
    target_non_null = transformed_df.filter(F.col(target_col).isNotNull()).count()
    failures = source_non_null - target_non_null
    if failures > 0:
        logger.warning(
            "Table %s: %d records failed to parse %s -> %s",
            table_name, failures, source_col, target_col,
        )
    return failures


def add_row_quality_flag(df: DataFrame, required_cols: list[str]) -> DataFrame:
    """
    Add a boolean column `_has_quality_issue` that is True when any
    required column is null.  This keeps all records in the output
    (no silent drops) while flagging problematic rows for review.
    """
    condition = F.lit(False)
    for col_name in required_cols:
        condition = condition | F.col(col_name).isNull()
    return df.withColumn("_has_quality_issue", condition)
