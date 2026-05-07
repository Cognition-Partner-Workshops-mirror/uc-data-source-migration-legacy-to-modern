"""
Shared transformation utilities for the legacy CDW to Delta Lake migration.

Provides reusable UDFs and helper functions for:
- Date string parsing (MM/DD/YYYY -> DateType)
- Amount string parsing ("285,000" -> DecimalType)
- Status code expansion (ACT -> Active, etc.)
- Null / malformed value handling with logging
"""

from pyspark.sql import DataFrame
from pyspark.sql.types import DateType, DecimalType, IntegerType, BooleanType, TimestampType
from pyspark.sql import functions as F
from pyspark.sql.utils import AnalysisException
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cdw_migration")

# ---------------------------------------------------------------------------
# Status code expansion maps
# ---------------------------------------------------------------------------
BORROWER_STATUS_MAP = {"ACT": "ACTIVE", "INA": "INACTIVE"}

LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
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

PRODUCT_STATUS_MAP = {"ACT": True, "INA": False}


def _build_map_expr(mapping: dict, col_name: str, default: str = None):
    """Build a CASE/WHEN expression from a Python dict."""
    expr = F.coalesce(
        F.create_map(*[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))])[F.upper(F.col(col_name))],
        F.lit(default) if default else F.col(col_name),
    )
    return expr


def _build_bool_map_expr(mapping: dict, col_name: str, default: bool = None):
    """Build a CASE/WHEN expression that returns BooleanType."""
    expr = F.when(F.upper(F.col(col_name)) == "ACT", F.lit(True)) \
            .when(F.upper(F.col(col_name)) == "INA", F.lit(False))
    if default is not None:
        expr = expr.otherwise(F.lit(default))
    return expr


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
def parse_date_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY string column to DateType.

    Malformed values become NULL; a warning count is logged.
    """
    df = df.withColumn(
        tgt_col,
        F.to_date(F.col(src_col), "MM/dd/yyyy"),
    )
    bad_count = df.filter(F.col(src_col).isNotNull() & F.col(tgt_col).isNull()).count()
    if bad_count > 0:
        logger.warning("parse_date_col: %d rows in '%s' could not be parsed to DATE", bad_count, src_col)
    return df


def parse_timestamp_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY string column to TimestampType (midnight)."""
    df = df.withColumn(
        tgt_col,
        F.to_timestamp(F.col(src_col), "MM/dd/yyyy"),
    )
    bad_count = df.filter(F.col(src_col).isNotNull() & F.col(tgt_col).isNull()).count()
    if bad_count > 0:
        logger.warning("parse_timestamp_col: %d rows in '%s' could not be parsed to TIMESTAMP", bad_count, src_col)
    return df


# ---------------------------------------------------------------------------
# Amount / numeric parsing
# ---------------------------------------------------------------------------
def parse_amount_col(df: DataFrame, src_col: str, tgt_col: str,
                     precision: int = 12, scale: int = 2) -> DataFrame:
    """Strip commas from a string column and cast to DecimalType.

    Malformed values become NULL; a warning count is logged.
    """
    cleaned = F.regexp_replace(F.col(src_col), ",", "")
    df = df.withColumn(tgt_col, cleaned.cast(DecimalType(precision, scale)))
    bad_count = df.filter(F.col(src_col).isNotNull() & F.col(tgt_col).isNull()).count()
    if bad_count > 0:
        logger.warning("parse_amount_col: %d rows in '%s' could not be parsed to DECIMAL(%d,%d)", bad_count, src_col, precision, scale)
    return df


def parse_int_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Cast a string column to IntegerType.

    Malformed values become NULL; a warning count is logged.
    """
    cleaned = F.regexp_replace(F.col(src_col), ",", "")
    df = df.withColumn(tgt_col, cleaned.cast(IntegerType()))
    bad_count = df.filter(F.col(src_col).isNotNull() & F.col(tgt_col).isNull()).count()
    if bad_count > 0:
        logger.warning("parse_int_col: %d rows in '%s' could not be parsed to INT", bad_count, src_col)
    return df


# ---------------------------------------------------------------------------
# Status expansion
# ---------------------------------------------------------------------------
def expand_status(df: DataFrame, src_col: str, tgt_col: str,
                  mapping: dict, default: str = None) -> DataFrame:
    """Map short status codes to expanded values using a lookup dict."""
    df = df.withColumn(tgt_col, _build_map_expr(mapping, src_col, default))
    unmapped = df.filter(F.col(tgt_col).isNull() & F.col(src_col).isNotNull()).count()
    if unmapped > 0:
        logger.warning("expand_status: %d rows in '%s' had unmapped codes", unmapped, src_col)
    return df


def expand_bool_status(df: DataFrame, src_col: str, tgt_col: str,
                       mapping: dict, default: bool = None) -> DataFrame:
    """Map short status codes to boolean values."""
    df = df.withColumn(tgt_col, _build_bool_map_expr(mapping, src_col, default))
    return df


# ---------------------------------------------------------------------------
# Quarantine helper
# ---------------------------------------------------------------------------
def quarantine_nulls(df: DataFrame, required_cols: list, table_name: str):
    """Split a DataFrame into valid rows and quarantined rows with NULLs in required columns.

    Returns (valid_df, quarantine_df).
    Quarantined rows are logged but never silently dropped.
    """
    condition = F.lit(True)
    for col_name in required_cols:
        condition = condition & F.col(col_name).isNotNull()

    valid_df = df.filter(condition)
    quarantine_df = df.filter(~condition)

    q_count = quarantine_df.count()
    if q_count > 0:
        logger.warning(
            "quarantine_nulls [%s]: %d rows quarantined due to NULL required fields %s",
            table_name, q_count, required_cols,
        )
    return valid_df, quarantine_df


def log_row_counts(source_df: DataFrame, target_df: DataFrame, table_name: str):
    """Log source vs target row counts for reconciliation."""
    src = source_df.count()
    tgt = target_df.count()
    logger.info("Row counts [%s]: source=%d, target=%d, diff=%d", table_name, src, tgt, src - tgt)
    return src, tgt
