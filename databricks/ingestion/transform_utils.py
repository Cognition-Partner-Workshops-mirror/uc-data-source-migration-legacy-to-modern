"""
Shared transformation utilities for the CDW legacy-to-modern migration pipeline.

Provides UDFs and helper functions for:
- Date parsing (MM/DD/YYYY strings -> DateType / TimestampType)
- Amount parsing (comma-formatted strings -> DecimalType)
- Status code expansion (abbreviations -> readable values)
- Null / malformed-value handling with logging
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    TimestampType,
)

# ---------------------------------------------------------------------------
# Status-code lookup maps
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
# Date helpers
# ---------------------------------------------------------------------------
def parse_date_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse an MM/DD/YYYY VARCHAR column to DateType.

    Malformed values are set to NULL and flagged in a companion column
    ``_bad_{tgt_col}`` so they can be reported without silently dropping rows.
    """
    df = df.withColumn(
        tgt_col,
        F.to_date(F.col(src_col), "MM/dd/yyyy"),
    )
    df = df.withColumn(
        f"_bad_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.col(src_col),
        ),
    )
    return df


def parse_timestamp_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse an MM/DD/YYYY VARCHAR column to TimestampType (midnight)."""
    df = df.withColumn(
        tgt_col,
        F.to_timestamp(F.col(src_col), "MM/dd/yyyy"),
    )
    df = df.withColumn(
        f"_bad_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.col(src_col),
        ),
    )
    return df


# ---------------------------------------------------------------------------
# Amount / numeric helpers
# ---------------------------------------------------------------------------
def parse_amount_col(
    df: DataFrame,
    src_col: str,
    tgt_col: str,
    precision: int = 12,
    scale: int = 2,
) -> DataFrame:
    """Strip commas from a VARCHAR amount and cast to DecimalType.

    Malformed values are preserved in ``_bad_{tgt_col}`` for reporting.
    """
    cleaned = F.regexp_replace(F.col(src_col), ",", "")
    df = df.withColumn(
        tgt_col,
        cleaned.cast(DecimalType(precision, scale)),
    )
    df = df.withColumn(
        f"_bad_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.col(src_col),
        ),
    )
    return df


def parse_int_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Cast a VARCHAR column to IntegerType with bad-value tracking."""
    df = df.withColumn(tgt_col, F.col(src_col).cast(IntegerType()))
    df = df.withColumn(
        f"_bad_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.col(src_col),
        ),
    )
    return df


# ---------------------------------------------------------------------------
# Code-expansion helpers
# ---------------------------------------------------------------------------
def expand_status_col(
    df: DataFrame,
    src_col: str,
    tgt_col: str,
    mapping: dict,
) -> DataFrame:
    """Map abbreviated status codes to their expanded values.

    Unknown codes are preserved as-is and flagged in ``_unmapped_{tgt_col}``.
    """
    mapping_expr = F.create_map(
        *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )
    mapped = mapping_expr[F.upper(F.trim(F.col(src_col)))]

    df = df.withColumn(tgt_col, mapped)
    df = df.withColumn(
        f"_unmapped_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.col(src_col),
        ),
    )
    # Fall back to original value so records are never silently dropped
    df = df.withColumn(
        tgt_col,
        F.coalesce(F.col(tgt_col), F.upper(F.trim(F.col(src_col)))),
    )
    return df


# ---------------------------------------------------------------------------
# Bad-value logging
# ---------------------------------------------------------------------------
def collect_bad_value_report(df: DataFrame, table_name: str) -> DataFrame:
    """Return a DataFrame of rows that had at least one parse problem.

    Looks for columns prefixed with ``_bad_`` or ``_unmapped_`` and returns
    rows where any such column is non-null, along with the first column of the
    original DataFrame (assumed to be the primary key) for identification.
    """
    flag_cols = [c for c in df.columns if c.startswith("_bad_") or c.startswith("_unmapped_")]
    if not flag_cols:
        spark = SparkSession.getActiveSession()
        return spark.createDataFrame([], schema="table STRING, column STRING, bad_value STRING, pk_value STRING")

    pk_col = df.columns[0]
    condition = F.lit(False)
    for c in flag_cols:
        condition = condition | F.col(c).isNotNull()

    bad_rows = df.filter(condition)

    # Melt flag columns into a long-form report
    stack_expr = ", ".join(
        [f"'{c}', CAST(`{c}` AS STRING)" for c in flag_cols]
    )
    report = bad_rows.selectExpr(
        f"`{pk_col}` AS pk_value",
        f"stack({len(flag_cols)}, {stack_expr}) AS (column, bad_value)",
    ).filter(F.col("bad_value").isNotNull())

    report = report.withColumn("table", F.lit(table_name))
    return report.select("table", "column", "bad_value", "pk_value")


def drop_flag_columns(df: DataFrame) -> DataFrame:
    """Remove all ``_bad_*`` and ``_unmapped_*`` sentinel columns."""
    flag_cols = [c for c in df.columns if c.startswith("_bad_") or c.startswith("_unmapped_")]
    return df.drop(*flag_cols)
