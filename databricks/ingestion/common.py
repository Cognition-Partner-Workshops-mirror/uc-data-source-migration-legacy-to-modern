"""
Common utilities for legacy CDW data ingestion into Delta Lake.

Provides safe parsing functions, status code expansion maps, and logging
helpers shared across all ingestion scripts.
"""

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    StringType,
    TimestampType,
)

# ---------------------------------------------------------------------------
# Status code expansion maps (from data/mappings/column_mappings.md)
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
    "SFR": "SINGLE_FAMILY",
    "CND": "CONDOMINIUM",
    "MFR": "MULTI_FAMILY",
    "TWN": "TOWNHOUSE",
}

PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}


# ---------------------------------------------------------------------------
# Safe parsing UDFs
# ---------------------------------------------------------------------------

def build_status_map_udf(mapping: dict):
    """Build a Spark mapping column expression from a Python dict."""
    return F.create_map(*[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))])


def expand_status(col_name: str, mapping: dict, fallback: str = "UNKNOWN"):
    """
    Expand a legacy status code abbreviation to its full name.
    Returns the original value if no mapping is found (logged as warning).
    """
    map_expr = build_status_map_udf(mapping)
    return F.coalesce(map_expr[F.upper(F.trim(F.col(col_name)))], F.lit(fallback))


def expand_status_to_bool(col_name: str, mapping: dict, fallback: bool = False):
    """Expand a status code to a boolean (e.g., ACT → true, INA → false)."""
    map_expr = F.create_map(*[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))])
    return F.coalesce(map_expr[F.upper(F.trim(F.col(col_name)))], F.lit(fallback))


def parse_legacy_date(col_name: str):
    """
    Parse a legacy date string (MM/DD/YYYY) to DateType.
    Returns null if the value is null, empty, or unparseable.
    """
    trimmed = F.trim(F.col(col_name))
    return F.when(
        (trimmed.isNull()) | (trimmed == "") | (trimmed == "null"),
        F.lit(None).cast(DateType()),
    ).otherwise(
        F.coalesce(
            F.to_date(trimmed, "MM/dd/yyyy"),
            F.to_date(trimmed, "yyyy-MM-dd"),
            F.to_date(trimmed, "M/d/yyyy"),
        )
    )


def parse_legacy_timestamp(col_name: str):
    """
    Parse a legacy date string to TimestampType (midnight).
    Returns null for unparseable values.
    """
    date_col = parse_legacy_date(col_name)
    return date_col.cast(TimestampType())


def parse_legacy_amount(col_name: str, precision: int = 12, scale: int = 2):
    """
    Parse a comma-formatted amount string (e.g., '285,000.00') to DecimalType.
    Strips commas, dollar signs, and spaces before casting.
    Returns null if unparseable.
    """
    trimmed = F.trim(F.col(col_name))
    cleaned = F.regexp_replace(
        F.regexp_replace(
            F.regexp_replace(trimmed, "[$,]", ""),
            "\\s+", "",
        ),
        "^$", None,
    )
    return F.when(
        (cleaned.isNull()) | (cleaned == "") | (cleaned == "null"),
        F.lit(None).cast(DecimalType(precision, scale)),
    ).otherwise(
        cleaned.cast(DecimalType(precision, scale))
    )


def parse_legacy_int(col_name: str):
    """
    Parse a VARCHAR integer (e.g., '360') to IntegerType.
    Returns null if unparseable.
    """
    trimmed = F.trim(F.col(col_name))
    return F.when(
        (trimmed.isNull()) | (trimmed == "") | (trimmed == "null"),
        F.lit(None).cast(IntegerType()),
    ).otherwise(
        trimmed.cast(IntegerType())
    )


def parse_legacy_decimal(col_name: str, precision: int = 5, scale: int = 3):
    """
    Parse a VARCHAR decimal (e.g., '4.750') to DecimalType.
    Returns null if unparseable.
    """
    trimmed = F.trim(F.col(col_name))
    return F.when(
        (trimmed.isNull()) | (trimmed == "") | (trimmed == "null"),
        F.lit(None).cast(DecimalType(precision, scale)),
    ).otherwise(
        trimmed.cast(DecimalType(precision, scale))
    )


def tag_ingestion_metadata(df, source_system: str):
    """Add _ingested_at and _source_system audit columns."""
    return df.withColumn(
        "_ingested_at", F.current_timestamp()
    ).withColumn(
        "_source_system", F.lit(source_system)
    )


def flag_quarantine(df, condition, reason: str):
    """
    Flag rows matching a condition for quarantine instead of dropping them.
    Adds _quarantine (boolean) and _quarantine_reason (string) columns.
    """
    return df.withColumn(
        "_quarantine",
        F.when(condition, F.lit(True)).otherwise(F.col("_quarantine") if "_quarantine" in df.columns else F.lit(False)),
    ).withColumn(
        "_quarantine_reason",
        F.when(
            condition,
            F.concat_ws(
                "; ",
                F.coalesce(F.col("_quarantine_reason") if "_quarantine_reason" in df.columns else F.lit(None), F.lit("")),
                F.lit(reason),
            ),
        ).otherwise(
            F.col("_quarantine_reason") if "_quarantine_reason" in df.columns else F.lit(None)
        ),
    )
