"""
Shared transformation utilities for CDW legacy-to-Delta Lake migration.

Provides reusable helpers for parsing dates, amounts, integers, and status
codes from legacy all-VARCHAR columns into properly typed Spark columns.
All parse helpers produce companion boolean error-flag columns so that no
records are silently dropped.
"""

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    DecimalType,
    IntegerType,
)

# ============================================================================
# Status-code expansion dictionaries
# ============================================================================

BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
}

LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
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

PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}

PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

# ============================================================================
# Date parsing helpers
# ============================================================================


def parse_date(col_name: str, alias: str | None = None) -> Column:
    """Parse a MM/DD/YYYY VARCHAR column to DateType.

    Returns the parsed date or ``null`` when the value cannot be parsed.
    """
    target = alias or col_name
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(target)


def parse_date_flag(col_name: str) -> Column:
    """Return a boolean error-flag column that is ``True`` when *col_name*
    is non-null but fails to parse as MM/DD/YYYY.
    """
    return (
        F.when(F.col(col_name).isNull(), F.lit(False))
        .when(
            F.to_date(F.col(col_name), "MM/dd/yyyy").isNull(),
            F.lit(True),
        )
        .otherwise(F.lit(False))
        .cast(BooleanType())
        .alias(f"_err_{col_name}")
    )


def parse_timestamp(col_name: str, alias: str | None = None) -> Column:
    """Parse a MM/DD/YYYY VARCHAR column to TimestampType."""
    target = alias or col_name
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(target)


def parse_timestamp_flag(col_name: str) -> Column:
    """Boolean error-flag for timestamp parsing failures."""
    return (
        F.when(F.col(col_name).isNull(), F.lit(False))
        .when(
            F.to_timestamp(F.col(col_name), "MM/dd/yyyy").isNull(),
            F.lit(True),
        )
        .otherwise(F.lit(False))
        .cast(BooleanType())
        .alias(f"_err_{col_name}")
    )


# ============================================================================
# Amount / decimal parsing helpers
# ============================================================================


def parse_amount(
    col_name: str,
    precision: int = 12,
    scale: int = 2,
    alias: str | None = None,
) -> Column:
    """Strip commas from a VARCHAR amount and cast to DecimalType."""
    target = alias or col_name
    return (
        F.regexp_replace(F.col(col_name), ",", "")
        .cast(DecimalType(precision, scale))
        .alias(target)
    )


def parse_amount_flag(col_name: str) -> Column:
    """Boolean error-flag for amount parsing failures."""
    cleaned = F.regexp_replace(F.col(col_name), ",", "")
    return (
        F.when(F.col(col_name).isNull(), F.lit(False))
        .when(cleaned.cast("decimal(12,2)").isNull(), F.lit(True))
        .otherwise(F.lit(False))
        .cast(BooleanType())
        .alias(f"_err_{col_name}")
    )


# ============================================================================
# Integer parsing helpers
# ============================================================================


def parse_integer(col_name: str, alias: str | None = None) -> Column:
    """Cast a VARCHAR column to IntegerType."""
    target = alias or col_name
    return F.col(col_name).cast(IntegerType()).alias(target)


def parse_integer_flag(col_name: str) -> Column:
    """Boolean error-flag for integer parsing failures."""
    return (
        F.when(F.col(col_name).isNull(), F.lit(False))
        .when(F.col(col_name).cast(IntegerType()).isNull(), F.lit(True))
        .otherwise(F.lit(False))
        .cast(BooleanType())
        .alias(f"_err_{col_name}")
    )


# ============================================================================
# Status-code expansion helpers
# ============================================================================


def expand_status(
    col_name: str,
    mapping: dict,
    alias: str | None = None,
) -> Column:
    """Map abbreviated status codes to their expanded values.

    Unmapped codes are preserved as-is and flagged separately.
    """
    target = alias or col_name
    expr = F.col(col_name)
    for code, expanded in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(str(expanded))).otherwise(
            expr
        )
    return expr.alias(target)


def expand_status_flag(col_name: str, mapping: dict) -> Column:
    """Boolean flag that is ``True`` when the code is not in *mapping*
    and the value is non-null.
    """
    known_codes = list(mapping.keys())
    return (
        F.when(F.col(col_name).isNull(), F.lit(False))
        .when(F.col(col_name).isin(known_codes), F.lit(False))
        .otherwise(F.lit(True))
        .cast(BooleanType())
        .alias(f"_err_{col_name}")
    )


# ============================================================================
# Error aggregation utilities
# ============================================================================


def add_error_summary(df: DataFrame) -> DataFrame:
    """Add an ``_has_parse_errors`` boolean column that is ``True`` when any
    ``_err_*`` flag column is ``True``.
    """
    err_cols = [c for c in df.columns if c.startswith("_err_")]
    if not err_cols:
        return df.withColumn("_has_parse_errors", F.lit(False))
    condition = F.lit(False)
    for c in err_cols:
        condition = condition | F.col(c)
    return df.withColumn("_has_parse_errors", condition)


def log_parse_errors(df: DataFrame, table_name: str) -> None:
    """Print parse-error counts and sample values for each ``_err_*`` column."""
    err_cols = [c for c in df.columns if c.startswith("_err_")]
    if not err_cols:
        print(f"[{table_name}] No error-flag columns found — nothing to log.")
        return

    total = df.count()
    error_df = df.filter(F.col("_has_parse_errors") == F.lit(True))
    error_count = error_df.count()
    print(f"[{table_name}] Total rows: {total}, Rows with errors: {error_count}")

    for ec in err_cols:
        source_col = ec.replace("_err_", "", 1)
        flagged = df.filter(F.col(ec) == F.lit(True))
        cnt = flagged.count()
        if cnt > 0:
            samples = (
                flagged.select(source_col)
                .distinct()
                .limit(5)
                .collect()
            )
            sample_vals = [str(row[0]) for row in samples]
            print(
                f"  {ec}: {cnt} errors — sample values: {sample_vals}"
            )


def strip_error_columns(df: DataFrame) -> DataFrame:
    """Remove all ``_err_*`` and ``_has_parse_errors`` columns."""
    drop_cols = [
        c
        for c in df.columns
        if c.startswith("_err_") or c == "_has_parse_errors"
    ]
    return df.drop(*drop_cols)


# ============================================================================
# Lineage metadata helpers
# ============================================================================

MIGRATION_SOURCE = "CDW_LEGACY"


def add_lineage_columns(df: DataFrame) -> DataFrame:
    """Append ``_migration_source`` and ``_migrated_at`` columns."""
    return df.withColumn(
        "_migration_source", F.lit(MIGRATION_SOURCE)
    ).withColumn("_migrated_at", F.current_timestamp())
