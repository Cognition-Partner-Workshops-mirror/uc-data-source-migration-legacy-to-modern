"""
Shared utilities for the legacy-to-modern loan data migration pipeline.

Provides parsing helpers, status code mappings, and logging configuration
used across all ingestion scripts.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Status code expansion mappings
# ---------------------------------------------------------------------------

LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

BORROWER_STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive",
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

PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}


# ---------------------------------------------------------------------------
# UDF-safe parsing functions
# ---------------------------------------------------------------------------

def parse_legacy_date(date_str: str) -> datetime:
    """Parse MM/DD/YYYY string to a Python date. Returns None on failure."""
    if date_str is None or date_str.strip() == "":
        return None
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
    except (ValueError, TypeError):
        return None


def parse_legacy_amount(amount_str: str) -> Decimal:
    """Remove commas from amount string and parse to Decimal. Returns None on failure."""
    if amount_str is None or amount_str.strip() == "":
        return None
    try:
        return Decimal(amount_str.strip().replace(",", ""))
    except (InvalidOperation, TypeError):
        return None


def parse_legacy_int(int_str: str) -> int:
    """Parse a string integer. Returns None on failure."""
    if int_str is None or int_str.strip() == "":
        return None
    try:
        return int(int_str.strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Column-level transformers (Spark native — prefer these over UDFs)
# ---------------------------------------------------------------------------

def col_parse_date(col_name: str, alias: str = None) -> F.Column:
    """Convert a MM/DD/YYYY VARCHAR column to DateType using Spark native functions."""
    target = alias or col_name
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(target)


def col_parse_timestamp(col_name: str, alias: str = None) -> F.Column:
    """Convert a MM/DD/YYYY VARCHAR column to TimestampType."""
    target = alias or col_name
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(target)


def col_parse_amount(col_name: str, alias: str = None, precision: int = 12, scale: int = 2) -> F.Column:
    """Remove commas and cast to DecimalType."""
    target = alias or col_name
    return F.regexp_replace(F.col(col_name), ",", "").cast(DecimalType(precision, scale)).alias(target)


def col_parse_int(col_name: str, alias: str = None) -> F.Column:
    """Cast a VARCHAR column to IntegerType."""
    target = alias or col_name
    return F.regexp_replace(F.col(col_name), ",", "").cast(IntegerType()).alias(target)


def col_expand_status(col_name: str, mapping: dict, alias: str = None) -> F.Column:
    """Expand abbreviated status codes using a mapping dict via a Spark CASE expression."""
    target = alias or col_name
    expr = F.col(col_name)
    case_expr = None
    for code, full_name in mapping.items():
        condition = F.when(F.upper(F.trim(expr)) == code, F.lit(full_name))
        case_expr = condition if case_expr is None else case_expr.when(
            F.upper(F.trim(expr)) == code, F.lit(full_name)
        )
    # Build a proper chained when/otherwise
    result = None
    for code, full_name in mapping.items():
        if result is None:
            result = F.when(F.upper(F.trim(expr)) == code, F.lit(full_name))
        else:
            result = result.when(F.upper(F.trim(expr)) == code, F.lit(full_name))
    result = result.otherwise(F.concat(F.lit("UNKNOWN:"), F.trim(expr)))
    return result.alias(target)


def col_expand_boolean(col_name: str, mapping: dict, alias: str = None) -> F.Column:
    """Expand abbreviated status codes to boolean."""
    target = alias or col_name
    expr = F.col(col_name)
    result = None
    for code, val in mapping.items():
        if result is None:
            result = F.when(F.upper(F.trim(expr)) == code, F.lit(val))
        else:
            result = result.when(F.upper(F.trim(expr)) == code, F.lit(val))
    result = result.otherwise(F.lit(None))
    return result.alias(target)


# ---------------------------------------------------------------------------
# Error logging / quarantine helpers
# ---------------------------------------------------------------------------

def tag_migration_metadata(df: DataFrame, source_table: str) -> DataFrame:
    """Add migration audit columns to a DataFrame."""
    return (
        df
        .withColumn("_migration_source", F.lit(source_table))
        .withColumn("_migrated_at", F.current_timestamp())
    )


def quarantine_malformed_rows(
    df: DataFrame,
    required_cols: list,
    source_table: str,
    spark: SparkSession,
) -> tuple:
    """
    Split a DataFrame into valid and quarantined rows.

    Rows where any column in required_cols is NULL after transformation
    are sent to the quarantine table. Returns (valid_df, quarantine_df).
    """
    null_condition = None
    for col_name in required_cols:
        cond = F.col(col_name).isNull()
        null_condition = cond if null_condition is None else (null_condition | cond)

    if null_condition is None:
        return df, spark.createDataFrame([], df.schema)

    quarantine_df = df.filter(null_condition).withColumn(
        "_quarantine_reason",
        F.lit(f"NULL in required column(s): {', '.join(required_cols)}")
    )
    valid_df = df.filter(~null_condition)

    return valid_df, quarantine_df


def log_row_counts(spark: SparkSession, source_count: int, target_count: int,
                   quarantine_count: int, table_name: str) -> dict:
    """Log and return row count reconciliation for a table."""
    result = {
        "table": table_name,
        "source_rows": source_count,
        "target_rows": target_count,
        "quarantined_rows": quarantine_count,
        "is_reconciled": source_count == (target_count + quarantine_count),
    }
    print(f"[MIGRATION] {table_name}: source={source_count}, "
          f"target={target_count}, quarantined={quarantine_count}, "
          f"reconciled={result['is_reconciled']}")
    return result
