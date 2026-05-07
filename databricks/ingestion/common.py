"""Shared transformation helpers for the legacy-to-modern ingestion pipeline."""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Date / timestamp parsing
# ---------------------------------------------------------------------------

def parse_date_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY string column to DateType.

    Malformed or NULL values are preserved as NULL with a warning flag column.
    """
    flag_col = f"_flag_{tgt_col}_parse_error"
    return (
        df
        .withColumn(
            tgt_col,
            F.to_date(F.col(src_col), "MM/dd/yyyy").cast(DateType()),
        )
        .withColumn(
            flag_col,
            F.when(
                F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
                F.lit(True),
            ).otherwise(F.lit(False)),
        )
    )


def parse_timestamp_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse a MM/DD/YYYY string column to TimestampType (midnight)."""
    flag_col = f"_flag_{tgt_col}_parse_error"
    return (
        df
        .withColumn(
            tgt_col,
            F.to_timestamp(F.col(src_col), "MM/dd/yyyy").cast(TimestampType()),
        )
        .withColumn(
            flag_col,
            F.when(
                F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
                F.lit(True),
            ).otherwise(F.lit(False)),
        )
    )


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

def parse_amount_col(
    df: DataFrame,
    src_col: str,
    tgt_col: str,
    precision: int = 12,
    scale: int = 2,
) -> DataFrame:
    """Remove commas from a string amount and cast to DecimalType."""
    flag_col = f"_flag_{tgt_col}_parse_error"
    cleaned = F.regexp_replace(F.col(src_col), ",", "")
    return (
        df
        .withColumn(tgt_col, cleaned.cast(DecimalType(precision, scale)))
        .withColumn(
            flag_col,
            F.when(
                F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
                F.lit(True),
            ).otherwise(F.lit(False)),
        )
    )


def parse_int_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Cast a string column to IntegerType with error flagging."""
    flag_col = f"_flag_{tgt_col}_parse_error"
    return (
        df
        .withColumn(tgt_col, F.col(src_col).cast(IntegerType()))
        .withColumn(
            flag_col,
            F.when(
                F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
                F.lit(True),
            ).otherwise(F.lit(False)),
        )
    )


# ---------------------------------------------------------------------------
# Status / code expansion
# ---------------------------------------------------------------------------

LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

BORROWER_STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive",
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


def expand_status(
    df: DataFrame,
    src_col: str,
    tgt_col: str,
    mapping: dict,
) -> DataFrame:
    """Map abbreviated status codes to their expanded values.

    Unknown codes are preserved as-is and flagged.
    """
    flag_col = f"_flag_{tgt_col}_unknown_code"
    mapping_expr = F.create_map(
        *[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    return (
        df
        .withColumn(
            tgt_col,
            F.coalesce(mapping_expr[F.col(src_col)], F.col(src_col)),
        )
        .withColumn(
            flag_col,
            F.when(
                F.col(src_col).isNotNull() & mapping_expr[F.col(src_col)].isNull(),
                F.lit(True),
            ).otherwise(F.lit(False)),
        )
    )


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------

def collect_flag_columns(df: DataFrame) -> list[str]:
    """Return the names of all _flag_* columns in the DataFrame."""
    return [c for c in df.columns if c.startswith("_flag_")]


def log_parse_errors(df: DataFrame, table_name: str, logger) -> None:
    """Log counts of rows that had parse/mapping errors for each flag column."""
    for flag_col in collect_flag_columns(df):
        error_count = df.filter(F.col(flag_col) == True).count()  # noqa: E712
        if error_count > 0:
            logger.warning(
                "Table %s: %d rows flagged on %s",
                table_name,
                error_count,
                flag_col,
            )


def drop_flag_columns(df: DataFrame) -> DataFrame:
    """Remove all _flag_* columns before writing to Delta."""
    flags = collect_flag_columns(df)
    return df.drop(*flags)
