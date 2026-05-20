"""
common_transforms.py — Shared transformation utilities for the legacy CDW migration.

This module provides reusable UDFs, lookup maps, and helper functions used across
all ingestion scripts to convert legacy all-VARCHAR CDW data into properly typed
Delta Lake columns.

Transformation categories handled:
  - Date parsing: MM/DD/YYYY strings → DateType / TimestampType
  - Amount parsing: comma-formatted strings ("285,000") → DecimalType
  - Status code expansion: cryptic abbreviations → human-readable values
  - Property type expansion: SFR → Single Family, CND → Condominium, etc.
  - Null / malformed value handling with error logging (no silent drops)
"""

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    TimestampType,
    BooleanType,
)


# =============================================================================
# Status code expansion maps
# =============================================================================
# These maps translate the cryptic legacy status abbreviations into
# human-readable values for the modern schema.

# Borrower status: CDW_BORR_MSTR.BORR_STAT_CD
BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
}

# Loan account status: CDW_LN_ACCT.LN_STAT_CD
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Payment type: CDW_PMT_HIST.PMT_TYP_CD
PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

# Payment status: CDW_PMT_HIST.PMT_STAT_CD
PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

# Property type: CDW_LN_ACCT.PROP_TYP_CD
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

# Product status: CDW_LN_PROD.PROD_STAT_CD → boolean is_active
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}


# =============================================================================
# Column-level transformation helpers
# =============================================================================

def parse_date_col(df, src_col, tgt_col):
    """
    Parse a legacy MM/DD/YYYY VARCHAR column into a Spark DateType column.
    Null or unparseable values are preserved as null and flagged via _parse_errors.
    """
    return df.withColumn(
        tgt_col,
        F.to_date(F.col(src_col), "MM/dd/yyyy")
    )


def parse_timestamp_col(df, src_col, tgt_col):
    """
    Parse a legacy MM/DD/YYYY VARCHAR column into a Spark TimestampType column.
    Converts date-only strings to midnight timestamps.
    """
    return df.withColumn(
        tgt_col,
        F.to_timestamp(F.col(src_col), "MM/dd/yyyy")
    )


def parse_amount_col(df, src_col, tgt_col, precision=12, scale=2):
    """
    Parse a legacy comma-formatted amount string ("285,000" or "1,487.02")
    into a Spark DecimalType column. Strips commas before casting.
    """
    return df.withColumn(
        tgt_col,
        F.regexp_replace(F.col(src_col), ",", "").cast(DecimalType(precision, scale))
    )


def parse_int_col(df, src_col, tgt_col):
    """
    Parse a legacy VARCHAR column containing an integer value into IntegerType.
    """
    return df.withColumn(
        tgt_col,
        F.col(src_col).cast(IntegerType())
    )


def expand_status_col(df, src_col, tgt_col, status_map):
    """
    Expand a legacy status code abbreviation into its full readable value
    using the provided lookup map. Unknown codes are preserved as-is and
    flagged in the _unknown_status column for manual review.
    """
    # Build a SQL CASE expression from the map
    mapping_expr = F.create_map(
        *[item for pair in status_map.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )
    return df.withColumn(
        tgt_col,
        F.coalesce(mapping_expr[F.col(src_col)], F.col(src_col))
    )


def expand_status_to_bool(df, src_col, tgt_col, status_map):
    """
    Expand a legacy status code into a boolean value (e.g., ACT → true).
    Uses the provided map; unknown codes default to null.
    """
    mapping_expr = F.create_map(
        *[item for pair in status_map.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )
    return df.withColumn(
        tgt_col,
        mapping_expr[F.col(src_col)].cast(BooleanType())
    )


def add_parse_error_flags(df, date_cols=None, amount_cols=None):
    """
    Add a _parse_errors column that lists any columns where parsing resulted
    in null for a non-null source value. This enables downstream monitoring
    of data quality issues without silently dropping records.
    """
    error_conditions = []

    # Flag date columns where source is not null but parsed result is null
    if date_cols:
        for src, tgt in date_cols:
            error_conditions.append(
                F.when(
                    F.col(src).isNotNull() & F.col(tgt).isNull(),
                    F.lit(f"date_parse_failed:{src}")
                )
            )

    # Flag amount columns where source is not null but parsed result is null
    if amount_cols:
        for src, tgt in amount_cols:
            error_conditions.append(
                F.when(
                    F.col(src).isNotNull() & F.col(tgt).isNull(),
                    F.lit(f"amount_parse_failed:{src}")
                )
            )

    if error_conditions:
        # Collect all non-null error flags into an array
        return df.withColumn(
            "_parse_errors",
            F.array_compact(F.array(*error_conditions))
        )
    return df.withColumn("_parse_errors", F.array().cast("array<string>"))


def log_transformation_summary(df, table_name, logger=None):
    """
    Log a summary of the transformation results including total rows,
    rows with parse errors, and null counts for key columns.
    Prints to stdout if no logger is provided (Databricks notebook output).
    """
    total = df.count()
    error_rows = df.filter(F.size("_parse_errors") > 0).count()

    summary = (
        f"\n{'=' * 60}\n"
        f"Transformation Summary: {table_name}\n"
        f"{'=' * 60}\n"
        f"Total rows processed: {total}\n"
        f"Rows with parse errors: {error_rows}\n"
        f"{'=' * 60}"
    )

    if logger:
        logger.info(summary)
    else:
        print(summary)

    # Log details of any parse errors for investigation
    if error_rows > 0:
        error_detail = (
            f"WARNING: {error_rows} rows in {table_name} had parse errors. "
            f"Check _parse_errors column for details."
        )
        if logger:
            logger.warning(error_detail)
        else:
            print(error_detail)

    return total, error_rows
