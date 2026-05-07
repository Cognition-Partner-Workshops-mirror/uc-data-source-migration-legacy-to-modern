"""
Shared transformation utilities for the legacy CDW to Delta Lake migration.

Provides UDFs and helper functions for:
- Date parsing (MM/DD/YYYY -> DateType)
- Amount parsing (comma-formatted strings -> DecimalType)
- Status code expansion (ACT -> ACTIVE, etc.)
- Null / malformed value handling with logging
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, BooleanType, TimestampType

# ---------------------------------------------------------------------------
# Status code lookup maps
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


def expand_status(col_name: str, mapping: dict, fallback: str = "UNKNOWN") -> F.Column:
    """Build a CASE/WHEN expression that expands abbreviated codes."""
    expr = F.lit(fallback)
    for code, expanded in mapping.items():
        expr = F.when(F.upper(F.trim(F.col(col_name))) == code, F.lit(expanded)).otherwise(expr)
    return expr


def parse_date(col_name: str) -> F.Column:
    """Parse MM/DD/YYYY string to DateType. Returns null for unparseable values."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy")


def parse_timestamp(col_name: str) -> F.Column:
    """Parse MM/DD/YYYY string to TimestampType (midnight). Returns null for unparseable values."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy")


def parse_amount(col_name: str, precision: int = 12, scale: int = 2) -> F.Column:
    """Strip commas and dollar signs from a string column and cast to DecimalType."""
    cleaned = F.regexp_replace(F.col(col_name), r"[$,]", "")
    return cleaned.cast(DecimalType(precision, scale))


def parse_int(col_name: str) -> F.Column:
    """Cast a VARCHAR column to IntegerType. Returns null for non-numeric values."""
    cleaned = F.regexp_replace(F.col(col_name), r"[,]", "")
    return cleaned.cast(IntegerType())


def parse_boolean_status(col_name: str) -> F.Column:
    """Convert ACT/INA to true/false."""
    return F.when(F.upper(F.trim(F.col(col_name))) == "ACT", F.lit(True)).otherwise(F.lit(False))


def add_ingestion_timestamp(df: DataFrame) -> DataFrame:
    """Append _ingestion_ts column with the current processing timestamp."""
    return df.withColumn("_ingestion_ts", F.current_timestamp())


def log_malformed_rows(
    df: DataFrame,
    required_cols: list,
    table_name: str,
    error_path: str,
) -> tuple:
    """
    Split a DataFrame into (valid, quarantined) based on null checks on required columns.

    Quarantined rows are written to error_path as JSON for manual review.
    Returns (valid_df, quarantine_count).
    """
    null_condition = F.lit(False)
    for col_name in required_cols:
        null_condition = null_condition | F.col(col_name).isNull()

    quarantined = df.filter(null_condition)
    valid = df.filter(~null_condition)

    quarantine_count = quarantined.count()
    if quarantine_count > 0:
        (
            quarantined
            .withColumn("_quarantine_reason", F.lit(f"NULL in required column(s): {required_cols}"))
            .withColumn("_source_table", F.lit(table_name))
            .withColumn("_quarantine_ts", F.current_timestamp())
            .write
            .mode("append")
            .json(error_path)
        )

    return valid, quarantine_count
