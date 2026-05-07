"""
Common transformation functions for legacy CDW data migration.

These UDFs and helper functions handle the recurring patterns in the legacy schema:
- Date strings (MM/DD/YYYY) to DateType
- Amount strings with commas ("285,000") to DecimalType
- Status code abbreviation expansion
- Null-safe operations with logging
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, BooleanType, TimestampType
from datetime import datetime


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_legacy_date(col_name: str, alias: str = None) -> F.Column:
    """Parse MM/DD/YYYY string to DateType. Returns null for unparseable values."""
    target = alias or col_name
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(target)


def parse_legacy_timestamp(col_name: str, alias: str = None) -> F.Column:
    """Parse MM/DD/YYYY string to TimestampType (midnight). Returns null for unparseable values."""
    target = alias or col_name
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(target)


# ---------------------------------------------------------------------------
# Amount / numeric parsing
# ---------------------------------------------------------------------------

def parse_legacy_amount(col_name: str, alias: str = None) -> F.Column:
    """
    Parse amount strings like '285,000' or '1,487.02' to DecimalType.
    Strips commas, dollar signs, and whitespace before casting.
    Returns null for unparseable values.
    """
    target = alias or col_name
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), r"[$,\s]", "")
    return cleaned.cast(DecimalType(12, 2)).alias(target)


def parse_legacy_decimal(col_name: str, precision: int, scale: int, alias: str = None) -> F.Column:
    """Parse a numeric string to DecimalType with specified precision/scale."""
    target = alias or col_name
    return F.trim(F.col(col_name)).cast(DecimalType(precision, scale)).alias(target)


def parse_legacy_integer(col_name: str, alias: str = None) -> F.Column:
    """Parse a numeric string to IntegerType."""
    target = alias or col_name
    return F.trim(F.col(col_name)).cast(IntegerType()).alias(target)


# ---------------------------------------------------------------------------
# Status code expansion
# ---------------------------------------------------------------------------

LOAN_STATUS_MAP = {"ACT": "ACTIVE", "CLO": "CLOSED", "DFT": "DEFAULT", "FRB": "FORBEARANCE"}
PAYMENT_TYPE_MAP = {"REG": "REGULAR", "EXT": "EXTRA", "PRT": "PARTIAL", "PRE": "PREPAYMENT"}
PAYMENT_STATUS_MAP = {"PST": "POSTED", "REV": "REVERSED", "NSF": "NSF", "PND": "PENDING"}
BORROWER_STATUS_MAP = {"ACT": "ACTIVE", "INA": "INACTIVE"}
PROPERTY_TYPE_MAP = {"SFR": "Single Family", "CND": "Condominium", "MFR": "Multi-Family", "TWN": "Townhouse"}


def expand_status_code(col_name: str, mapping: dict, alias: str = None) -> F.Column:
    """
    Map legacy abbreviation codes to expanded values.
    Unrecognized codes are preserved as-is (not silently dropped).
    """
    target = alias or col_name
    expr = F.col(col_name)
    for code, expanded in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(expanded)).otherwise(expr)
    return expr.alias(target)


# ---------------------------------------------------------------------------
# Data quality flags
# ---------------------------------------------------------------------------

def add_ingestion_metadata(df: DataFrame, source_file: str = None) -> DataFrame:
    """Add standard ingestion metadata columns to a DataFrame."""
    df = df.withColumn("_ingestion_ts", F.current_timestamp())
    if source_file:
        df = df.withColumn("_source_file", F.lit(source_file))
    else:
        df = df.withColumn("_source_file", F.input_file_name())
    return df


def flag_null_required_fields(df: DataFrame, required_cols: list, flag_col: str = "_has_nulls") -> DataFrame:
    """Add a boolean column indicating whether any required field is null."""
    condition = F.lit(False)
    for col_name in required_cols:
        condition = condition | F.col(col_name).isNull()
    return df.withColumn(flag_col, condition)


def log_rejected_records(df: DataFrame, filter_col: str, table_name: str, spark: SparkSession) -> tuple:
    """
    Split a DataFrame into valid and rejected records.
    Rejected records are logged as warnings via Spark's log4j.
    Returns (valid_df, rejected_df).
    """
    valid_df = df.filter(~F.col(filter_col))
    rejected_df = df.filter(F.col(filter_col))

    rejected_count = rejected_df.count()
    if rejected_count > 0:
        log4j = spark._jvm.org.apache.log4j
        logger = log4j.LogManager.getLogger("LegacyMigration")
        logger.warn(
            f"[{table_name}] {rejected_count} records flagged with data quality issues"
        )

    return valid_df, rejected_df
