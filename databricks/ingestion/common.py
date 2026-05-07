"""
Common utilities for the legacy CDW to modern Delta Lake migration pipeline.
Provides shared transformation functions, logging, and configuration.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import (
    col, when, regexp_replace, to_date, to_timestamp, trim, lit, current_timestamp
)
from pyspark.sql.types import DecimalType, IntegerType
import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("cdw_migration")


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


class MigrationConfig:
    """Configuration for the migration pipeline."""

    def __init__(
        self,
        source_base_path: str = "/mnt/legacy-cdw/exports",
        target_database: str = "loan_warehouse",
        source_format: str = "csv",
        error_table: str = "loan_warehouse._migration_errors",
    ):
        self.source_base_path = source_base_path
        self.target_database = target_database
        self.source_format = source_format
        self.error_table = error_table


def get_spark() -> SparkSession:
    """Get or create a SparkSession configured for Delta Lake."""
    return (
        SparkSession.builder
        .appName("CDW_Legacy_Migration")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .getOrCreate()
    )


def parse_date_string(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """Parse MM/DD/YYYY date strings to DateType."""
    return df.withColumn(
        target_col,
        to_date(col(source_col), "MM/dd/yyyy")
    )


def parse_timestamp_string(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """Parse MM/DD/YYYY date strings to TimestampType (midnight)."""
    return df.withColumn(
        target_col,
        to_timestamp(col(source_col), "MM/dd/yyyy")
    )


def parse_amount_string(df: DataFrame, source_col: str, target_col: str,
                        precision: int = 12, scale: int = 2) -> DataFrame:
    """
    Parse amount strings like '285,000' or '271,432.56' to DecimalType.
    Removes commas and casts to decimal.
    """
    return df.withColumn(
        target_col,
        regexp_replace(col(source_col), ",", "").cast(DecimalType(precision, scale))
    )


def parse_integer_string(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """Parse numeric strings to IntegerType."""
    return df.withColumn(
        target_col,
        trim(col(source_col)).cast(IntegerType())
    )


def expand_status_code(df: DataFrame, source_col: str, target_col: str,
                       mapping: dict) -> DataFrame:
    """Expand abbreviated status codes to full descriptions using a mapping dict."""
    expr = None
    for code, expanded in mapping.items():
        condition = trim(col(source_col)) == code
        if expr is None:
            expr = when(condition, lit(expanded))
        else:
            expr = expr.when(condition, lit(expanded))
    expr = expr.otherwise(col(source_col))
    return df.withColumn(target_col, expr)


def read_source_data(spark: SparkSession, config: MigrationConfig,
                     table_name: str) -> DataFrame:
    """
    Read source data from legacy export files (CSV or Parquet).
    CSV files are expected to have headers and use standard delimiters.
    """
    source_path = f"{config.source_base_path}/{table_name}"
    logger.info(f"Reading source data from: {source_path} (format: {config.source_format})")

    if config.source_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "")
            .option("emptyValue", "")
            .csv(source_path)
        )
    elif config.source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {config.source_format}")

    row_count = df.count()
    logger.info(f"Read {row_count} rows from {table_name}")
    return df


def log_malformed_records(df: DataFrame, error_df: DataFrame, table_name: str,
                          spark: SparkSession, config: MigrationConfig) -> None:
    """
    Write malformed/rejected records to an error table for investigation.
    Does not silently drop records.
    """
    if error_df.count() > 0:
        error_count = error_df.count()
        logger.warning(
            f"Found {error_count} malformed records in {table_name}. "
            f"Writing to error table: {config.error_table}"
        )
        (
            error_df
            .withColumn("_source_table", lit(table_name))
            .withColumn("_error_timestamp", current_timestamp())
            .write
            .format("delta")
            .mode("append")
            .saveAsTable(config.error_table)
        )
    else:
        logger.info(f"No malformed records found in {table_name}")


def write_to_delta(df: DataFrame, table_name: str, mode: str = "overwrite") -> None:
    """Write a DataFrame to a Delta Lake table."""
    full_table = f"loan_warehouse.{table_name}"
    row_count = df.count()
    logger.info(f"Writing {row_count} rows to {full_table} (mode: {mode})")
    (
        df.write
        .format("delta")
        .mode(mode)
        .saveAsTable(full_table)
    )
    logger.info(f"Successfully wrote {row_count} rows to {full_table}")
