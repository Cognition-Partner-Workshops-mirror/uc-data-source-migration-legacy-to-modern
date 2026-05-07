"""
Shared transformation utilities for the CDW legacy-to-modern migration.

Provides reusable UDFs and helper functions for:
- Date parsing (MM/DD/YYYY strings -> DateType / TimestampType)
- Amount parsing (comma-formatted strings -> DecimalType)
- Status code expansion (ACT -> ACTIVE, etc.)
- Null / malformed-value handling with logging
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    TimestampType,
)

logger = logging.getLogger("cdw_migration")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Lookup maps
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

# ---------------------------------------------------------------------------
# UDF-safe parsing helpers
# ---------------------------------------------------------------------------


def parse_date_string(date_str: str):
    """Parse MM/DD/YYYY string to a Python date. Returns None on failure."""
    if date_str is None or date_str.strip() == "":
        return None
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
    except ValueError:
        logger.warning("Malformed date value: %s", date_str)
        return None


def parse_timestamp_string(date_str: str):
    """Parse MM/DD/YYYY string to a Python datetime (midnight). Returns None on failure."""
    if date_str is None or date_str.strip() == "":
        return None
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y")
    except ValueError:
        logger.warning("Malformed timestamp value: %s", date_str)
        return None


def parse_amount_string(amount_str: str):
    """Remove commas and parse to Decimal. Returns None on failure."""
    if amount_str is None or amount_str.strip() == "":
        return None
    try:
        cleaned = amount_str.strip().replace(",", "").replace("$", "")
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        logger.warning("Malformed amount value: %s", amount_str)
        return None


def parse_int_string(int_str: str):
    """Parse a string to int. Returns None on failure."""
    if int_str is None or int_str.strip() == "":
        return None
    try:
        cleaned = int_str.strip().replace(",", "")
        return int(cleaned)
    except ValueError:
        logger.warning("Malformed integer value: %s", int_str)
        return None


def expand_code(code: str, mapping: dict, fallback: str = None):
    """Expand an abbreviated status code using the given mapping."""
    if code is None:
        return fallback
    return mapping.get(code.strip().upper(), fallback or code.strip())


# ---------------------------------------------------------------------------
# Spark UDF registration
# ---------------------------------------------------------------------------


def register_udfs(spark: SparkSession):
    """Register all migration UDFs on the given SparkSession."""
    spark.udf.register("parse_date", parse_date_string, DateType())
    spark.udf.register("parse_timestamp", parse_timestamp_string, TimestampType())
    spark.udf.register("parse_amount", parse_amount_string, DecimalType(12, 2))
    spark.udf.register("parse_amount_10_2", parse_amount_string, DecimalType(10, 2))
    spark.udf.register("parse_amount_5_3", parse_amount_string, DecimalType(5, 3))
    spark.udf.register("parse_amount_5_2", parse_amount_string, DecimalType(5, 2))
    spark.udf.register("parse_int", parse_int_string, IntegerType())

    return {
        "parse_date": F.udf(parse_date_string, DateType()),
        "parse_timestamp": F.udf(parse_timestamp_string, TimestampType()),
        "parse_amount_12_2": F.udf(parse_amount_string, DecimalType(12, 2)),
        "parse_amount_10_2": F.udf(parse_amount_string, DecimalType(10, 2)),
        "parse_amount_5_3": F.udf(parse_amount_string, DecimalType(5, 3)),
        "parse_amount_5_2": F.udf(parse_amount_string, DecimalType(5, 2)),
        "parse_int": F.udf(parse_int_string, IntegerType()),
    }


# ---------------------------------------------------------------------------
# Column-level transformers (DataFrame API)
# ---------------------------------------------------------------------------


def map_status_column(df: DataFrame, source_col: str, target_col: str,
                      mapping: dict) -> DataFrame:
    """Replace abbreviated status codes with expanded values via a mapping expr."""
    mapping_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])
    return df.withColumn(
        target_col,
        F.coalesce(
            mapping_expr[F.upper(F.trim(F.col(source_col)))],
            F.trim(F.col(source_col))
        )
    )


# ---------------------------------------------------------------------------
# Source readers
# ---------------------------------------------------------------------------


def read_legacy_csv(spark: SparkSession, path: str, header: bool = True) -> DataFrame:
    """
    Read a legacy CSV export. All columns are read as STRING to mirror the
    all-VARCHAR legacy schema, ensuring parsing happens explicitly downstream.
    """
    logger.info("Reading legacy CSV from: %s", path)
    df = (
        spark.read
        .option("header", str(header).lower())
        .option("inferSchema", "false")
        .option("mode", "PERMISSIVE")
        .option("columnNameOfCorruptRecord", "_corrupt_record")
        .csv(path)
    )
    row_count = df.count()
    logger.info("Read %d rows from %s", row_count, path)
    return df


def read_legacy_parquet(spark: SparkSession, path: str) -> DataFrame:
    """Read a legacy Parquet export (column types may already be STRING)."""
    logger.info("Reading legacy Parquet from: %s", path)
    df = spark.read.parquet(path)
    row_count = df.count()
    logger.info("Read %d rows from %s", row_count, path)
    return df


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def write_delta(df: DataFrame, table_name: str, mode: str = "overwrite",
                partition_cols: list = None):
    """Write a DataFrame to a Delta Lake table."""
    writer = df.write.format("delta").mode(mode)
    if partition_cols:
        writer = writer.partitionBy(*partition_cols)
    writer.saveAsTable(table_name)
    logger.info("Wrote %d rows to %s (mode=%s)", df.count(), table_name, mode)


# ---------------------------------------------------------------------------
# Error quarantine
# ---------------------------------------------------------------------------


def quarantine_malformed(df: DataFrame, table_name: str,
                         required_cols: list) -> tuple:
    """
    Split a DataFrame into valid and quarantined subsets.
    Rows where any required column is NULL after transformation are quarantined.

    Returns (valid_df, quarantine_df).
    """
    condition = F.lit(True)
    for col_name in required_cols:
        condition = condition & F.col(col_name).isNotNull()

    valid_df = df.filter(condition)
    quarantine_df = df.filter(~condition)

    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        logger.warning(
            "Quarantined %d rows from %s due to NULL required fields: %s",
            quarantine_count, table_name, required_cols,
        )

    return valid_df, quarantine_df
