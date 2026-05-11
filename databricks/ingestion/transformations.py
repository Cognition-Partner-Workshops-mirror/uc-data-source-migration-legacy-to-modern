"""
Shared transformation utilities for the legacy CDW → Delta Lake migration.

Provides reusable UDFs and helper functions for:
  - Parsing legacy MM/DD/YYYY date strings to DateType/TimestampType
  - Parsing comma-formatted amount strings ("285,000") to DecimalType
  - Expanding cryptic status code abbreviations to readable values
  - Null/malformed value handling with logging (never silently drops records)
"""

import logging

from pyspark.sql import DataFrame, Column
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    TimestampType,
    DecimalType,
    IntegerType,
    BooleanType,
)

from config import LEGACY_DATE_FORMAT

# Logger for transformation warnings (malformed values, nulls, etc.)
logger = logging.getLogger("cdw_migration.transformations")


def parse_date(col_name: str, alias: str = None) -> Column:
    """
    Parse a legacy MM/DD/YYYY VARCHAR column to DateType.

    Returns NULL for unparseable values rather than failing the row.
    The calling script should log these as quarantine candidates.
    """
    target_name = alias or col_name
    return F.to_date(F.col(col_name), LEGACY_DATE_FORMAT).alias(target_name)


def parse_timestamp(col_name: str, alias: str = None) -> Column:
    """
    Parse a legacy MM/DD/YYYY VARCHAR column to TimestampType.

    Timestamps are set to midnight (00:00:00) since legacy only stores date.
    Returns NULL for unparseable values.
    """
    target_name = alias or col_name
    return F.to_timestamp(F.col(col_name), LEGACY_DATE_FORMAT).alias(target_name)


def parse_amount(col_name: str, alias: str = None) -> Column:
    """
    Parse a legacy comma-formatted amount string to DecimalType(12,2).

    Handles formats like "285,000", "1,487.02", "0.00".
    Strips commas before casting. Returns NULL for unparseable values.
    """
    target_name = alias or col_name
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(12, 2))
        .alias(target_name)
    )


def parse_amount_10_2(col_name: str, alias: str = None) -> Column:
    """
    Parse a legacy comma-formatted amount string to DecimalType(10,2).

    Same as parse_amount but with narrower precision for payment-sized fields.
    """
    target_name = alias or col_name
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(10, 2))
        .alias(target_name)
    )


def parse_integer(col_name: str, alias: str = None) -> Column:
    """
    Parse a legacy VARCHAR column to IntegerType.

    Returns NULL for non-numeric values.
    """
    target_name = alias or col_name
    return F.col(col_name).cast(IntegerType()).alias(target_name)


def parse_rate(col_name: str, alias: str = None) -> Column:
    """
    Parse a legacy interest rate string (e.g. "5.250") to DecimalType(5,3).
    """
    target_name = alias or col_name
    return F.col(col_name).cast(DecimalType(5, 3)).alias(target_name)


def parse_percent(col_name: str, alias: str = None) -> Column:
    """
    Parse a legacy percentage string (e.g. "82.5") to DecimalType(5,2).
    """
    target_name = alias or col_name
    return F.col(col_name).cast(DecimalType(5, 2)).alias(target_name)


def expand_status_code(col_name: str, mapping: dict, alias: str = None) -> Column:
    """
    Expand a legacy status code abbreviation using the provided mapping dict.

    Unmapped codes are preserved as-is with a '_UNKNOWN' suffix so they
    surface during quality checks rather than being silently dropped.
    """
    target_name = alias or col_name
    # Build a CASE WHEN chain from the mapping dictionary
    expr = F.col(col_name)
    case_expr = F.when(F.col(col_name).isNull(), F.lit(None))
    for code, expanded in mapping.items():
        case_expr = case_expr.when(F.col(col_name) == code, F.lit(expanded))
    # Fallback: preserve unknown codes with suffix for visibility
    case_expr = case_expr.otherwise(
        F.concat(F.col(col_name), F.lit("_UNKNOWN"))
    )
    return case_expr.alias(target_name)


def expand_to_boolean(col_name: str, mapping: dict, alias: str = None) -> Column:
    """
    Convert a legacy status code to BooleanType using the provided mapping.

    Used for PROD_STAT_CD → is_active (ACT→true, INA→false).
    Unmapped codes default to NULL.
    """
    target_name = alias or col_name
    case_expr = F.when(F.col(col_name).isNull(), F.lit(None).cast(BooleanType()))
    for code, value in mapping.items():
        case_expr = case_expr.when(F.col(col_name) == code, F.lit(value))
    # Unknown status codes → NULL boolean (flagged in quality checks)
    case_expr = case_expr.otherwise(F.lit(None).cast(BooleanType()))
    return case_expr.alias(target_name)


def add_etl_metadata(df: DataFrame, source_table: str) -> DataFrame:
    """
    Append ETL metadata columns to the DataFrame for lineage tracking.

    Adds:
      - _etl_loaded_at: current timestamp when the record was loaded
      - _etl_source: name of the legacy source table
    """
    return df.withColumn(
        "_etl_loaded_at", F.current_timestamp()
    ).withColumn(
        "_etl_source", F.lit(source_table)
    )


def tag_malformed_rows(df: DataFrame, required_cols: list) -> DataFrame:
    """
    Add a _malformed flag column that is True when any required column is NULL.

    Used to route bad records to the quarantine table rather than dropping them.
    """
    null_check = F.lit(False)
    for col_name in required_cols:
        null_check = null_check | F.col(col_name).isNull()
    return df.withColumn("_is_malformed", null_check)


def log_malformed_summary(df: DataFrame, table_name: str) -> None:
    """
    Log a summary of malformed rows to the migration logger.

    Counts malformed vs. clean rows and reports the ratio.
    """
    total = df.count()
    malformed = df.filter(F.col("_is_malformed")).count()
    if malformed > 0:
        logger.warning(
            f"[{table_name}] {malformed}/{total} rows flagged as malformed "
            f"({malformed / total * 100:.1f}%). Routing to quarantine table."
        )
    else:
        logger.info(f"[{table_name}] All {total} rows passed validation.")


def read_legacy_source(spark, path: str, schema, file_format: str = "csv"):
    """
    Read a legacy CDW export file (CSV or Parquet) with the given schema.

    CSV options:
      - header=True (assumes export includes column headers)
      - enforceSchema=True (cast all to STRING per legacy schema)
      - mode=PERMISSIVE (capture malformed rows rather than failing)
    """
    if file_format.lower() == "csv":
        return (
            spark.read.format("csv")
            .option("header", "true")
            .option("enforceSchema", "true")
            .option("mode", "PERMISSIVE")
            .schema(schema)
            .load(path)
        )
    elif file_format.lower() == "parquet":
        # Parquet already has a schema; we override with our STRING schema
        # to ensure consistent downstream processing
        return spark.read.schema(schema).parquet(path)
    else:
        raise ValueError(f"Unsupported file format: {file_format}")
