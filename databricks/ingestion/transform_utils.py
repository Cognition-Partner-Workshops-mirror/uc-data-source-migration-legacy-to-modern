"""
Shared transformation utilities for legacy CDW to modern Delta Lake migration.

Provides reusable UDFs and helper functions for:
- Date parsing (MM/DD/YYYY strings to DateType/TimestampType)
- Amount parsing (comma-formatted strings to DecimalType)
- Status code expansion (cryptic abbreviations to readable values)
- Null / malformed value handling with logging
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DecimalType,
    IntegerType,
)

# ---------------------------------------------------------------------------
# Status code expansion mappings
# ---------------------------------------------------------------------------

BORROWER_STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive",
}

LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
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


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

def parse_date_column(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY VARCHAR column to DateType.

    Malformed values are set to NULL and flagged in a companion
    ``_<target_col>_parse_error`` boolean column so that downstream
    quality checks can report them.
    """
    parsed = F.to_date(F.col(source_col), "MM/dd/yyyy")
    error_flag = F.when(
        F.col(source_col).isNotNull() & F.col(target_col).isNull(), True
    ).otherwise(False)
    result = df.withColumn(target_col, parsed)
    result = result.withColumn(f"_{target_col}_parse_error", error_flag)
    return result


def parse_timestamp_column(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY VARCHAR column to TimestampType (midnight)."""
    parsed = F.to_timestamp(F.col(source_col), "MM/dd/yyyy")
    error_flag = F.when(
        F.col(source_col).isNotNull() & F.col(target_col).isNull(), True
    ).otherwise(False)
    result = df.withColumn(target_col, parsed)
    result = result.withColumn(f"_{target_col}_parse_error", error_flag)
    return result


# ---------------------------------------------------------------------------
# Amount / numeric parsing helpers
# ---------------------------------------------------------------------------

def parse_amount_column(
    df: DataFrame,
    source_col: str,
    target_col: str,
    precision: int = 12,
    scale: int = 2,
) -> DataFrame:
    """Strip commas from a VARCHAR amount field and cast to DecimalType.

    Handles formats like ``"285,000"`` and ``"271,432.56"``.
    """
    cleaned = F.regexp_replace(F.col(source_col), ",", "")
    parsed = cleaned.cast(DecimalType(precision, scale))
    error_flag = F.when(
        F.col(source_col).isNotNull() & F.col(target_col).isNull(), True
    ).otherwise(False)
    result = df.withColumn(target_col, parsed)
    result = result.withColumn(f"_{target_col}_parse_error", error_flag)
    return result


def parse_int_column(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """Cast a VARCHAR column to IntegerType with error flagging."""
    parsed = F.col(source_col).cast(IntegerType())
    error_flag = F.when(
        F.col(source_col).isNotNull() & F.col(target_col).isNull(), True
    ).otherwise(False)
    result = df.withColumn(target_col, parsed)
    result = result.withColumn(f"_{target_col}_parse_error", error_flag)
    return result


# ---------------------------------------------------------------------------
# Status / code expansion helpers
# ---------------------------------------------------------------------------

def expand_status_column(
    df: DataFrame,
    source_col: str,
    target_col: str,
    mapping: dict,
) -> DataFrame:
    """Map legacy status abbreviations to expanded values.

    Unknown codes are preserved as-is and flagged in a companion
    ``_<target_col>_unmapped`` boolean column.
    """
    mapping_expr = F.create_map([F.lit(x) for pair in mapping.items() for x in pair])
    mapped = mapping_expr[F.upper(F.trim(F.col(source_col)))]
    unmapped_flag = F.when(
        F.col(source_col).isNotNull() & mapped.isNull(), True
    ).otherwise(False)
    result = df.withColumn(target_col, F.coalesce(mapped, F.col(source_col)))
    result = result.withColumn(f"_{target_col}_unmapped", unmapped_flag)
    return result


# ---------------------------------------------------------------------------
# Error aggregation
# ---------------------------------------------------------------------------

def collect_parse_errors(df: DataFrame, table_name: str) -> DataFrame:
    """Return a summary DataFrame of parse-error and unmapped columns.

    Scans all boolean columns whose name starts with ``_`` and ends with
    ``_parse_error`` or ``_unmapped``, counts rows where the flag is True,
    and returns a three-column DataFrame: ``table, column, error_count``.
    """
    error_cols = [
        c for c in df.columns
        if c.startswith("_") and (c.endswith("_parse_error") or c.endswith("_unmapped"))
    ]
    if not error_cols:
        spark = SparkSession.getActiveSession()
        return spark.createDataFrame([], "table STRING, column STRING, error_count LONG")

    rows = []
    for col_name in error_cols:
        count_val = df.filter(F.col(col_name) == True).count()  # noqa: E712
        if count_val > 0:
            rows.append((table_name, col_name, count_val))

    spark = SparkSession.getActiveSession()
    if rows:
        return spark.createDataFrame(rows, ["table", "column", "error_count"])
    return spark.createDataFrame([], "table STRING, column STRING, error_count LONG")


def drop_parse_error_columns(df: DataFrame) -> DataFrame:
    """Remove all internal ``_*_parse_error`` and ``_*_unmapped`` flag columns."""
    keep = [c for c in df.columns if not (c.startswith("_") and (c.endswith("_parse_error") or c.endswith("_unmapped")))]
    return df.select(*keep)
