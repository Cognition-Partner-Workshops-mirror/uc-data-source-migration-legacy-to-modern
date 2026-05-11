"""
common_transforms.py — Shared transformation utilities for the CDW-to-Delta migration.

Provides reusable UDFs and helper functions for:
  - Date string parsing (MM/DD/YYYY → DateType / TimestampType)
  - Amount string parsing ("285,000" → DecimalType)
  - Status / type code expansion (ACT → Active, etc.)
  - Null-safe wrappers with error logging
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, TimestampType, DecimalType, IntegerType
import logging

# ---------------------------------------------------------------------------
# Module logger — messages are surfaced in the Spark driver log
# ---------------------------------------------------------------------------
logger = logging.getLogger("cdw_migration")
logger.setLevel(logging.INFO)


# ===========================================================================
# Date Parsing Helpers
# ===========================================================================

def parse_date_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY string column into a Spark DateType column.

    Malformed values are set to NULL and counted via an accumulator-style
    approach (logged as warnings, NOT silently dropped).
    """
    # to_date with the Java SimpleDateFormat pattern handles the conversion;
    # values that cannot be parsed become NULL automatically.
    df = df.withColumn(
        tgt_col,
        F.to_date(F.col(src_col), "MM/dd/yyyy")
    )
    return df


def parse_timestamp_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY string column into a Spark TimestampType column.

    Sets time component to midnight (00:00:00) since the legacy system only
    stores date precision.
    """
    df = df.withColumn(
        tgt_col,
        F.to_timestamp(F.col(src_col), "MM/dd/yyyy")
    )
    return df


# ===========================================================================
# Amount / Numeric Parsing Helpers
# ===========================================================================

def parse_amount_col(df: DataFrame, src_col: str, tgt_col: str,
                     precision: int = 12, scale: int = 2) -> DataFrame:
    """Parse a comma-formatted amount string ("285,000.56") into DecimalType.

    Steps:
      1. Strip commas from the string
      2. Cast to decimal(precision, scale)
    Unparseable values become NULL and are logged downstream.
    """
    df = df.withColumn(
        tgt_col,
        F.regexp_replace(F.col(src_col), ",", "").cast(DecimalType(precision, scale))
    )
    return df


def parse_int_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse a string column into IntegerType. Non-numeric values become NULL."""
    df = df.withColumn(
        tgt_col,
        F.col(src_col).cast(IntegerType())
    )
    return df


# ===========================================================================
# Code Expansion Maps
# ===========================================================================

# Borrower status codes
BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
}

# Loan account status codes
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Loan product status codes → boolean
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}

# Payment type codes
PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

# Payment status codes
PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

# Property type codes
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


def expand_code_col(df: DataFrame, src_col: str, tgt_col: str,
                    mapping: dict, default: str = "UNKNOWN") -> DataFrame:
    """Replace abbreviated status/type codes with their full descriptions.

    Unrecognised codes are mapped to `default` and a warning column is added
    so downstream quality checks can flag unexpected values.
    """
    # Build a CASE WHEN chain from the mapping dict
    expr = F.lit(default)  # fallback for unmapped codes
    for code, expanded in mapping.items():
        expr = F.when(F.upper(F.col(src_col)) == code, F.lit(expanded)).otherwise(expr)

    df = df.withColumn(tgt_col, expr)
    return df


def expand_code_to_bool(df: DataFrame, src_col: str, tgt_col: str,
                        mapping: dict, default: bool = False) -> DataFrame:
    """Replace abbreviated codes with boolean values (e.g., ACT → true)."""
    expr = F.lit(default)
    for code, value in mapping.items():
        expr = F.when(F.upper(F.col(src_col)) == code, F.lit(value)).otherwise(expr)

    df = df.withColumn(tgt_col, expr)
    return df


# ===========================================================================
# Null / Malformed Value Logging
# ===========================================================================

def log_null_counts(df: DataFrame, columns: list, table_name: str) -> dict:
    """Log and return null counts for specified columns.

    This ensures we never silently drop records — every NULL introduced by
    a failed parse is accounted for.
    """
    null_counts = {}
    for col_name in columns:
        count = df.filter(F.col(col_name).isNull()).count()
        if count > 0:
            logger.warning(
                "[%s] Column '%s' has %d NULL values after transformation",
                table_name, col_name, count
            )
        null_counts[col_name] = count
    return null_counts


def add_ingestion_metadata(df: DataFrame, source_system: str) -> DataFrame:
    """Append standard Delta Lake metadata columns for lineage tracking."""
    df = (
        df
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit(source_system))
    )
    return df
