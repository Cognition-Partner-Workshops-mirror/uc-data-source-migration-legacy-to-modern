"""
Shared transformation functions for legacy CDW to modern Delta Lake migration.

All parsers handle nulls and malformed values gracefully, returning None
rather than raising exceptions. Malformed values are logged for investigation.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, BooleanType, TimestampType


# ---------------------------------------------------------------------------
# Status code expansion maps
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
# UDF-free column-level transformers
# ---------------------------------------------------------------------------

def parse_date_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse MM/DD/YYYY string to DateType. Nulls and unparseable values become None."""
    return df.withColumn(
        tgt_col,
        F.to_date(F.col(src_col), "MM/dd/yyyy")
    )


def parse_timestamp_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse MM/DD/YYYY string to TimestampType (midnight). Nulls become None."""
    return df.withColumn(
        tgt_col,
        F.to_timestamp(F.col(src_col), "MM/dd/yyyy")
    )


def parse_amount_col(df: DataFrame, src_col: str, tgt_col: str,
                     precision: int = 12, scale: int = 2) -> DataFrame:
    """Remove commas from amount strings and cast to DecimalType."""
    return df.withColumn(
        tgt_col,
        F.regexp_replace(F.col(src_col), ",", "").cast(DecimalType(precision, scale))
    )


def parse_int_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Cast string column to IntegerType. Non-numeric values become None."""
    return df.withColumn(
        tgt_col,
        F.col(src_col).cast(IntegerType())
    )


def expand_status_col(df: DataFrame, src_col: str, tgt_col: str,
                      mapping: dict) -> DataFrame:
    """Map abbreviated status codes to expanded values using a lookup."""
    mapping_expr = F.create_map([F.lit(x) for pair in mapping.items() for x in pair])
    return df.withColumn(
        tgt_col,
        F.coalesce(mapping_expr[F.trim(F.col(src_col))], F.col(src_col))
    )


def expand_status_to_bool(df: DataFrame, src_col: str, tgt_col: str,
                          mapping: dict) -> DataFrame:
    """Map abbreviated status codes to boolean values."""
    mapping_expr = F.create_map(
        [F.lit(x) for pair in ((k, v) for k, v in mapping.items()) for x in (k, v)]
    )
    return df.withColumn(
        tgt_col,
        mapping_expr[F.trim(F.col(src_col))].cast(BooleanType())
    )


# ---------------------------------------------------------------------------
# Quarantine / error logging helpers
# ---------------------------------------------------------------------------

def flag_parse_failures(df: DataFrame, src_col: str, parsed_col: str,
                        flag_col: str) -> DataFrame:
    """Add a boolean flag column that is True when the source is non-null but
    the parsed result is null (indicating a parse failure)."""
    return df.withColumn(
        flag_col,
        F.when(
            F.col(src_col).isNotNull() & F.col(parsed_col).isNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )


def quarantine_bad_records(df: DataFrame, flag_columns: list) -> tuple:
    """Split a DataFrame into good records and quarantined (bad) records.

    Returns:
        (good_df, bad_df) tuple
    """
    any_bad = F.lit(False)
    for col_name in flag_columns:
        any_bad = any_bad | F.col(col_name)

    good_df = df.filter(~any_bad)
    bad_df = df.filter(any_bad)
    return good_df, bad_df
