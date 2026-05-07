"""
Common utilities for the legacy CDW to Delta Lake migration pipeline.
Provides shared transformation functions, logging, and configuration.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import (
    col, to_date, regexp_replace, trim, when, lit, current_timestamp, coalesce
)
from pyspark.sql.types import DecimalType, IntegerType, DateType, TimestampType
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("cdw_migration")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CATALOG = "lending_warehouse"
SCHEMA = "loan_management"
LEGACY_DATE_FORMAT = "MM/dd/yyyy"

# Status code expansion mappings
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

PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}


# ---------------------------------------------------------------------------
# Transformation Helpers
# ---------------------------------------------------------------------------


def get_spark() -> SparkSession:
    """Get or create a SparkSession configured for Delta Lake."""
    return (
        SparkSession.builder
        .appName("CDW_Legacy_Migration")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.databricks.delta.schema.autoMerge.enabled", "true")
        .getOrCreate()
    )


def parse_date_column(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """Parse MM/DD/YYYY string column to DateType."""
    return df.withColumn(
        target_col,
        to_date(trim(col(source_col)), LEGACY_DATE_FORMAT)
    )


def parse_timestamp_column(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """Parse MM/DD/YYYY string column to TimestampType (midnight)."""
    return df.withColumn(
        target_col,
        to_date(trim(col(source_col)), LEGACY_DATE_FORMAT).cast(TimestampType())
    )


def parse_amount_column(df: DataFrame, source_col: str, target_col: str, precision: int = 12, scale: int = 2) -> DataFrame:
    """Remove commas from amount strings and cast to DecimalType."""
    return df.withColumn(
        target_col,
        regexp_replace(trim(col(source_col)), ",", "").cast(DecimalType(precision, scale))
    )


def parse_integer_column(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """Parse string column to IntegerType."""
    return df.withColumn(
        target_col,
        trim(col(source_col)).cast(IntegerType())
    )


def expand_status_code(df: DataFrame, source_col: str, target_col: str, mapping: dict) -> DataFrame:
    """Expand abbreviated status codes using a lookup mapping."""
    expr = coalesce(
        *[when(trim(col(source_col)) == k, lit(v)) for k, v in mapping.items()],
        trim(col(source_col))  # fallback: keep original if no mapping found
    )
    return df.withColumn(target_col, expr)


def expand_status_to_boolean(df: DataFrame, source_col: str, target_col: str, mapping: dict) -> DataFrame:
    """Expand abbreviated status codes to boolean values."""
    expr = coalesce(
        *[when(trim(col(source_col)) == k, lit(v)) for k, v in mapping.items()],
        lit(None)
    )
    return df.withColumn(target_col, expr)


def log_record_counts(df: DataFrame, table_name: str, stage: str) -> int:
    """Log and return the record count at a given pipeline stage."""
    count = df.count()
    logger.info(f"[{table_name}] {stage}: {count} records")
    return count


def log_null_counts(df: DataFrame, table_name: str, columns: list) -> dict:
    """Log null counts for specified columns. Returns dict of col->null_count."""
    null_counts = {}
    for c in columns:
        null_count = df.filter(col(c).isNull()).count()
        if null_count > 0:
            logger.warning(f"[{table_name}] Column '{c}' has {null_count} null values")
        null_counts[c] = null_count
    return null_counts


def write_delta(df: DataFrame, table_name: str, mode: str = "overwrite", partition_cols: list = None):
    """Write DataFrame to a Delta Lake table."""
    full_table = f"{CATALOG}.{SCHEMA}.{table_name}"
    writer = df.write.format("delta").mode(mode)
    if partition_cols:
        writer = writer.partitionBy(*partition_cols)
    writer.saveAsTable(full_table)
    logger.info(f"[{table_name}] Written to {full_table} (mode={mode})")
