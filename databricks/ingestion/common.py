"""
Common utilities for the CDW-to-Delta-Lake migration pipeline.

Provides shared parsing functions, status code mappings, and logging helpers
used across all ingestion scripts.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cdw_migration")

# ---------------------------------------------------------------------------
# Status-code expansion maps (legacy abbreviation -> modern readable value)
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
# UDF-friendly parsing helpers
# ---------------------------------------------------------------------------


def parse_date_string(date_str: str) -> datetime | None:
    """Parse MM/DD/YYYY string to a Python date, returning None on failure."""
    if date_str is None or date_str.strip() == "":
        return None
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y")
    except ValueError:
        logger.warning("Malformed date value: '%s'", date_str)
        return None


def parse_amount_string(amount_str: str) -> Decimal | None:
    """Remove commas/currency symbols and parse to Decimal, returning None on failure."""
    if amount_str is None or amount_str.strip() == "":
        return None
    try:
        cleaned = amount_str.strip().replace(",", "").replace("$", "")
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        logger.warning("Malformed amount value: '%s'", amount_str)
        return None


def parse_int_string(int_str: str) -> int | None:
    """Parse a string to int, returning None on failure."""
    if int_str is None or int_str.strip() == "":
        return None
    try:
        return int(int_str.strip().replace(",", ""))
    except ValueError:
        logger.warning("Malformed integer value: '%s'", int_str)
        return None


# ---------------------------------------------------------------------------
# Spark-column-level transformation helpers
# ---------------------------------------------------------------------------


def parse_date_col(col_name: str) -> F.Column:
    """Convert a VARCHAR date column (MM/dd/yyyy) to DateType."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(col_name)


def parse_timestamp_col(col_name: str) -> F.Column:
    """Convert a VARCHAR date column (MM/dd/yyyy) to TimestampType."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(col_name)


def parse_amount_col(col_name: str, precision: int = 12, scale: int = 2) -> F.Column:
    """Strip commas and cast a VARCHAR amount to DecimalType."""
    return (
        F.regexp_replace(F.col(col_name), "[,$]", "")
        .cast(DecimalType(precision, scale))
        .alias(col_name)
    )


def parse_int_col(col_name: str) -> F.Column:
    """Cast a VARCHAR column to IntegerType."""
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(IntegerType())
        .alias(col_name)
    )


def expand_status_col(col_name: str, mapping: dict[str, str], default: str = "UNKNOWN") -> F.Column:
    """Map legacy abbreviation codes to expanded readable values."""
    mapping_expr = F.create_map([F.lit(x) for pair in mapping.items() for x in pair])
    return F.coalesce(mapping_expr[F.col(col_name)], F.lit(default)).alias(col_name)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def read_legacy_csv(spark: SparkSession, path: str, header: bool = True) -> DataFrame:
    """Read a legacy-exported CSV file with all-string schema."""
    logger.info("Reading legacy CSV from: %s", path)
    return (
        spark.read
        .option("header", str(header).lower())
        .option("inferSchema", "false")
        .csv(path)
    )


def read_legacy_parquet(spark: SparkSession, path: str) -> DataFrame:
    """Read a legacy-exported Parquet file."""
    logger.info("Reading legacy Parquet from: %s", path)
    return spark.read.parquet(path)


def write_delta(df: DataFrame, table_name: str, mode: str = "overwrite", partition_cols: list[str] | None = None) -> None:
    """Write a DataFrame to a Delta Lake table."""
    logger.info("Writing %d rows to Delta table: %s (mode=%s)", df.count(), table_name, mode)
    writer = df.write.format("delta").mode(mode)
    if partition_cols:
        writer = writer.partitionBy(*partition_cols)
    writer.saveAsTable(table_name)
    logger.info("Successfully wrote table: %s", table_name)


def log_rejected_rows(df: DataFrame, reason: str, table_name: str) -> None:
    """Log rows that failed validation without silently dropping them."""
    count = df.count()
    if count > 0:
        logger.warning(
            "REJECTED %d rows for table '%s': %s",
            count, table_name, reason,
        )
        df.show(truncate=False)
    else:
        logger.info("No rejected rows for table '%s' (%s)", table_name, reason)
