"""
Common transformation utilities for the legacy CDW to Delta Lake migration.

Provides reusable UDFs and helper functions for:
- Date parsing (MM/DD/YYYY strings -> DateType / TimestampType)
- Amount parsing (comma-formatted strings -> DecimalType)
- Status code expansion (abbreviations -> full labels)
- Null / malformed value handling with logging
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    StringType,
    TimestampType,
)

# ---------------------------------------------------------------------------
# Status code expansion maps
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
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_date_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY VARCHAR column into a DateType column.

    Malformed values become NULL; a boolean flag column ``__{tgt_col}_parse_err``
    is added so callers can audit rows that failed parsing.
    """
    parsed = F.to_date(F.col(src_col), "MM/dd/yyyy")
    err_flag = F.when(
        F.col(src_col).isNotNull() & parsed.isNull(), True
    ).otherwise(False)
    return (
        df.withColumn(tgt_col, parsed)
          .withColumn(f"__{tgt_col}_parse_err", err_flag)
    )


def parse_timestamp_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY VARCHAR column into a TimestampType column.

    Sets time component to midnight (00:00:00).  Adds a parse-error flag.
    """
    parsed = F.to_timestamp(F.col(src_col), "MM/dd/yyyy")
    err_flag = F.when(
        F.col(src_col).isNotNull() & parsed.isNull(), True
    ).otherwise(False)
    return (
        df.withColumn(tgt_col, parsed)
          .withColumn(f"__{tgt_col}_parse_err", err_flag)
    )


def parse_amount_col(
    df: DataFrame,
    src_col: str,
    tgt_col: str,
    precision: int = 12,
    scale: int = 2,
) -> DataFrame:
    """Strip commas from a string amount and cast to DecimalType.

    Adds a parse-error flag for values that are non-null but fail conversion.
    """
    cleaned = F.regexp_replace(F.col(src_col), ",", "")
    casted = cleaned.cast(DecimalType(precision, scale))
    err_flag = F.when(
        F.col(src_col).isNotNull() & casted.isNull(), True
    ).otherwise(False)
    return (
        df.withColumn(tgt_col, casted)
          .withColumn(f"__{tgt_col}_parse_err", err_flag)
    )


def parse_int_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Cast a VARCHAR column to IntegerType with a parse-error flag."""
    casted = F.col(src_col).cast(IntegerType())
    err_flag = F.when(
        F.col(src_col).isNotNull() & casted.isNull(), True
    ).otherwise(False)
    return (
        df.withColumn(tgt_col, casted)
          .withColumn(f"__{tgt_col}_parse_err", err_flag)
    )


def expand_status_col(
    df: DataFrame,
    src_col: str,
    tgt_col: str,
    mapping: dict,
) -> DataFrame:
    """Replace abbreviated status codes with expanded values using a mapping dict.

    Unknown codes are preserved as-is and flagged.
    """
    map_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])
    expanded = map_expr[F.upper(F.trim(F.col(src_col)))]
    # If the code isn't in the map, keep the original value and set a flag
    result = F.coalesce(expanded, F.col(src_col))
    err_flag = F.when(
        F.col(src_col).isNotNull() & expanded.isNull(), True
    ).otherwise(False)
    return (
        df.withColumn(tgt_col, result)
          .withColumn(f"__{tgt_col}_unmapped", err_flag)
    )


# ---------------------------------------------------------------------------
# Error / audit helpers
# ---------------------------------------------------------------------------

def collect_parse_errors(df: DataFrame) -> DataFrame:
    """Return rows that have at least one parse-error flag set to True."""
    err_cols = [c for c in df.columns if c.startswith("__") and c.endswith("_parse_err")]
    if not err_cols:
        return df.limit(0)
    condition = F.lit(False)
    for c in err_cols:
        condition = condition | F.col(c)
    return df.filter(condition)


def drop_audit_columns(df: DataFrame) -> DataFrame:
    """Remove internal ``__*`` audit flag columns before writing to Delta."""
    audit_cols = [c for c in df.columns if c.startswith("__")]
    return df.drop(*audit_cols)


def log_error_summary(df: DataFrame, table_name: str) -> dict:
    """Print and return a summary of parse errors per column.

    Returns a dict of ``{column: error_count}`` for downstream reporting.
    """
    err_cols = [c for c in df.columns if c.startswith("__") and (
        c.endswith("_parse_err") or c.endswith("_unmapped")
    )]
    summary = {}
    for c in err_cols:
        count = df.filter(F.col(c) == True).count()  # noqa: E712
        if count > 0:
            summary[c] = count
            print(f"  WARNING [{table_name}] {c}: {count} row(s) with issues")
    if not summary:
        print(f"  OK [{table_name}] No parse errors detected.")
    return summary


# ---------------------------------------------------------------------------
# Source reading helpers
# ---------------------------------------------------------------------------

def read_legacy_csv(
    spark: SparkSession,
    path: str,
    header: bool = True,
) -> DataFrame:
    """Read a legacy source exported as CSV with all-string schema."""
    return (
        spark.read
        .option("header", str(header).lower())
        .option("inferSchema", "false")
        .csv(path)
    )


def read_legacy_parquet(spark: SparkSession, path: str) -> DataFrame:
    """Read a legacy source exported as Parquet."""
    return spark.read.parquet(path)


def read_legacy_source(
    spark: SparkSession,
    path: str,
    fmt: str = "csv",
) -> DataFrame:
    """Unified reader that dispatches to CSV or Parquet based on ``fmt``."""
    if fmt == "parquet":
        return read_legacy_parquet(spark, path)
    return read_legacy_csv(spark, path)
