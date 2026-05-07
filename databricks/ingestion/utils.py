"""Shared transformation utilities for the CDW-to-Delta-Lake migration pipeline."""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType

# ---------------------------------------------------------------------------
# Status-code expansion maps (legacy abbreviation -> modern readable value)
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


def expand_status(df: DataFrame, col_name: str, mapping: dict, target_col: str) -> DataFrame:
    """Replace legacy status codes with expanded values using a mapping dict.

    Unrecognised codes are preserved as-is and flagged in ``_unmapped_{target_col}``.
    """
    map_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])
    df = df.withColumn(
        target_col,
        F.coalesce(map_expr[F.upper(F.col(col_name))], F.col(col_name)),
    )
    df = df.withColumn(
        f"_unmapped_{target_col}",
        F.when(map_expr[F.upper(F.col(col_name))].isNull() & F.col(col_name).isNotNull(), F.lit(True))
        .otherwise(F.lit(False)),
    )
    return df


def expand_status_bool(df: DataFrame, col_name: str, mapping: dict, target_col: str) -> DataFrame:
    """Expand a status code to a boolean column."""
    map_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in (kv[0], str(kv[1]))])
    df = df.withColumn(
        target_col,
        F.when(map_expr[F.upper(F.col(col_name))] == "True", F.lit(True))
        .when(map_expr[F.upper(F.col(col_name))] == "False", F.lit(False))
        .otherwise(F.lit(None).cast("boolean")),
    )
    return df


def parse_date(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse ``MM/DD/YYYY`` string into a ``DateType`` column.

    Malformed values become ``NULL``; the original value is preserved in
    ``_raw_{tgt_col}`` for auditability.
    """
    df = df.withColumn(f"_raw_{tgt_col}", F.col(src_col))
    df = df.withColumn(tgt_col, F.to_date(F.col(src_col), "MM/dd/yyyy").cast(DateType()))
    return df


def parse_timestamp(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse ``MM/DD/YYYY`` string into a ``TimestampType`` column."""
    df = df.withColumn(f"_raw_{tgt_col}", F.col(src_col))
    df = df.withColumn(tgt_col, F.to_timestamp(F.col(src_col), "MM/dd/yyyy").cast(TimestampType()))
    return df


def parse_amount(df: DataFrame, src_col: str, tgt_col: str, precision: int = 12, scale: int = 2) -> DataFrame:
    """Strip commas from a string amount and cast to ``DecimalType``.

    Malformed values become ``NULL``; the original value is preserved in
    ``_raw_{tgt_col}``.
    """
    df = df.withColumn(f"_raw_{tgt_col}", F.col(src_col))
    df = df.withColumn(
        tgt_col,
        F.regexp_replace(F.col(src_col), ",", "").cast(DecimalType(precision, scale)),
    )
    return df


def parse_int(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Cast a string column to ``IntegerType``, preserving raw value for audit."""
    df = df.withColumn(f"_raw_{tgt_col}", F.col(src_col))
    df = df.withColumn(tgt_col, F.col(src_col).cast(IntegerType()))
    return df


def add_ingestion_metadata(df: DataFrame, source_system: str) -> DataFrame:
    """Append standard ingestion audit columns."""
    return (
        df.withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit(source_system))
    )


def log_null_counts(df: DataFrame, table_name: str, columns: list) -> DataFrame:
    """Print null counts per column to the Spark driver log for diagnostics.

    Returns the DataFrame unchanged (pass-through).
    """
    print(f"\n{'='*60}")
    print(f"NULL AUDIT — {table_name}")
    print(f"{'='*60}")
    for c in columns:
        null_count = df.filter(F.col(c).isNull()).count()
        total = df.count()
        pct = (null_count / total * 100) if total > 0 else 0.0
        print(f"  {c:30s}  nulls={null_count:>6d}  ({pct:5.1f}%)")
    print(f"{'='*60}\n")
    return df
