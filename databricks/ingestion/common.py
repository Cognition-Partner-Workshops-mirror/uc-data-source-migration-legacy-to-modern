"""
Common utilities for the legacy CDW to Delta Lake ingestion pipeline.

Provides shared transformation functions used across all table ingestion scripts:
- Date parsing (MM/DD/YYYY string -> DateType/TimestampType)
- Amount parsing (comma-formatted strings like "285,000" -> DecimalType)
- Status code expansion (ACT -> ACTIVE, CLO -> CLOSED, etc.)
- Null/malformed value handling with logging (never silently drops records)
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType
from datetime import datetime
import logging

logger = logging.getLogger("cdw_migration")

# ---------------------------------------------------------------------------
# Status code lookup maps derived from column_mappings.md
# ---------------------------------------------------------------------------

# Borrower status codes (CDW_BORR_MSTR.BORR_STAT_CD)
BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
}

# Loan account status codes (CDW_LN_ACCT.LN_STAT_CD)
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Product status codes (CDW_LN_PROD.PROD_STAT_CD) -> boolean
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}

# Payment type codes (CDW_PMT_HIST.PMT_TYP_CD)
PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

# Payment status codes (CDW_PMT_HIST.PMT_STAT_CD)
PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

# Property type codes (CDW_LN_ACCT.PROP_TYP_CD)
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


def expand_status_code(df: DataFrame, source_col: str, target_col: str,
                       mapping: dict, default: str = "UNKNOWN") -> DataFrame:
    """
    Expand abbreviated status codes to full readable values using a lookup map.

    Records with unrecognized codes get the default value and a warning flag column
    is added (<target_col>_unmapped = true) so downstream quality checks can catch them.
    """
    # Build a CASE WHEN expression from the mapping dict
    expr = F.coalesce(
        F.create_map(
            *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
        )[F.upper(F.trim(F.col(source_col)))],
        F.lit(default)
    )
    # Flag rows where the code was not in the known mapping
    flag_expr = ~F.upper(F.trim(F.col(source_col))).isin(list(mapping.keys()))

    return (
        df
        .withColumn(target_col, expr)
        .withColumn(f"{target_col}_unmapped", flag_expr)
    )


def parse_legacy_date(df: DataFrame, source_col: str, target_col: str,
                      fmt: str = "MM/dd/yyyy") -> DataFrame:
    """
    Parse legacy date strings (MM/DD/YYYY) to DateType.

    Malformed values become null rather than failing the pipeline.
    A flag column (<target_col>_parse_error) marks rows where parsing failed,
    preserving the original value for troubleshooting.
    """
    parsed = F.to_date(F.col(source_col), fmt)
    return (
        df
        .withColumn(target_col, parsed)
        # Flag rows where the source was non-null but parsing produced null
        .withColumn(
            f"{target_col}_parse_error",
            F.col(source_col).isNotNull() & F.col(target_col).isNull()
        )
    )


def parse_legacy_timestamp(df: DataFrame, source_col: str, target_col: str,
                           fmt: str = "MM/dd/yyyy") -> DataFrame:
    """
    Parse legacy date strings (MM/DD/YYYY) to TimestampType (midnight of that date).

    Same error-flagging behavior as parse_legacy_date.
    """
    parsed = F.to_timestamp(F.col(source_col), fmt)
    return (
        df
        .withColumn(target_col, parsed)
        .withColumn(
            f"{target_col}_parse_error",
            F.col(source_col).isNotNull() & F.col(target_col).isNull()
        )
    )


def parse_legacy_amount(df: DataFrame, source_col: str, target_col: str,
                        precision: int = 12, scale: int = 2) -> DataFrame:
    """
    Parse comma-formatted amount strings (e.g., '285,000', '1,487.02') to DecimalType.

    Steps:
    1. Strip leading/trailing whitespace
    2. Remove dollar signs and commas
    3. Cast to decimal
    Malformed values become null with a parse_error flag column.
    """
    # Clean the string: trim, remove $ and commas
    cleaned = F.regexp_replace(F.trim(F.col(source_col)), "[$,]", "")
    parsed = cleaned.cast(DecimalType(precision, scale))

    return (
        df
        .withColumn(target_col, parsed)
        # Flag rows where source was non-null/non-empty but parse produced null
        .withColumn(
            f"{target_col}_parse_error",
            (F.col(source_col).isNotNull() & (F.trim(F.col(source_col)) != F.lit("")))
            & F.col(target_col).isNull()
        )
    )


def parse_legacy_integer(df: DataFrame, source_col: str, target_col: str) -> DataFrame:
    """
    Parse string-encoded integers (e.g., term months '360', delinquency days '15').

    Removes commas (in case of formatted numbers) before casting.
    """
    cleaned = F.regexp_replace(F.trim(F.col(source_col)), "[,]", "")
    parsed = cleaned.cast(IntegerType())

    return (
        df
        .withColumn(target_col, parsed)
        .withColumn(
            f"{target_col}_parse_error",
            (F.col(source_col).isNotNull() & (F.trim(F.col(source_col)) != F.lit("")))
            & F.col(target_col).isNull()
        )
    )


def add_pipeline_metadata(df: DataFrame, source_system: str) -> DataFrame:
    """
    Add standard pipeline metadata columns for lineage tracking.

    _ingested_at: current timestamp when the pipeline ran
    _source_system: identifier for the CDW source table
    """
    return (
        df
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_system", F.lit(source_system))
    )


def log_parse_errors(df: DataFrame, table_name: str, error_columns: list) -> DataFrame:
    """
    Log a summary of parse errors for each flagged column.

    Counts rows where each _parse_error or _unmapped flag is True and logs at WARN level.
    Returns the original DataFrame unchanged (pure side-effect for observability).
    """
    for col_name in error_columns:
        if col_name in df.columns:
            error_count = df.filter(F.col(col_name) == True).count()
            if error_count > 0:
                logger.warning(
                    f"[{table_name}] {col_name}: {error_count} rows with parse/mapping issues"
                )
    return df


def read_legacy_csv(spark: SparkSession, path: str, header: bool = True,
                    infer_schema: bool = False) -> DataFrame:
    """
    Read a legacy data extract as CSV (simulates CDW export).

    All columns read as StringType by default (infer_schema=False) to match
    the all-VARCHAR nature of the legacy CDW tables and allow controlled parsing.
    """
    return (
        spark.read
        .option("header", str(header).lower())
        .option("inferSchema", str(infer_schema).lower())
        .option("mode", "PERMISSIVE")  # Don't drop malformed rows
        .option("columnNameOfCorruptRecord", "_corrupt_record")
        .csv(path)
    )


def read_legacy_parquet(spark: SparkSession, path: str) -> DataFrame:
    """
    Read a legacy data extract as Parquet (alternative CDW export format).

    Even in Parquet format, legacy CDW data may have all-string columns
    since the source schema is all VARCHAR.
    """
    return spark.read.parquet(path)
