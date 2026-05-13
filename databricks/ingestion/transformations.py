"""
Shared transformation functions for the Legacy CDW to Delta Lake migration.

Provides reusable UDFs and helper functions for:
  - Parsing date strings (MM/DD/YYYY) to DateType / TimestampType
  - Parsing amount strings with commas ("285,000") to DecimalType
  - Expanding status code abbreviations to full descriptions
  - Handling nulls and malformed values with logging
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, TimestampType, DecimalType, IntegerType
import logging

# ---------------------------------------------------------------------------
# Logger setup — logs malformed values instead of silently dropping records
# ---------------------------------------------------------------------------
logger = logging.getLogger("cdw_migration.transformations")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Status code expansion mappings derived from column_mappings.md
# ---------------------------------------------------------------------------

# Borrower status codes (CDW_BORR_MSTR.BORR_STAT_CD)
BORROWER_STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive",
}

# Loan status codes (CDW_LN_ACCT.LN_STAT_CD)
LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance",
}

# Payment type codes (CDW_PMT_HIST.PMT_TYP_CD)
PAYMENT_TYPE_MAP = {
    "REG": "Regular",
    "EXT": "Extra",
    "PRT": "Partial",
    "PRE": "Prepayment",
}

# Payment status codes (CDW_PMT_HIST.PMT_STAT_CD)
PAYMENT_STATUS_MAP = {
    "PST": "Posted",
    "REV": "Reversed",
    "NSF": "NSF",
    "PND": "Pending",
}

# Property type codes (CDW_LN_ACCT.PROP_TYP_CD)
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

# Product active-status mapping (CDW_LN_PROD.PROD_STAT_CD)
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}


# ---------------------------------------------------------------------------
# Date parsing: MM/DD/YYYY string -> DateType or TimestampType
# ---------------------------------------------------------------------------
def parse_date_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """
    Parse a date string column in MM/DD/YYYY format to Spark DateType.

    Malformed or null values are preserved as NULL in the target column.
    A boolean flag column '_bad_{tgt_col}' is added to track parse failures.
    """
    # Use to_date with the legacy format pattern
    df = df.withColumn(
        tgt_col,
        F.to_date(F.col(src_col), "MM/dd/yyyy")
    )
    # Flag rows where the source was non-null but parsing produced null
    df = df.withColumn(
        f"_bad_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    return df


def parse_timestamp_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """
    Parse a date string column in MM/DD/YYYY format to Spark TimestampType.

    Sets time component to midnight (00:00:00) since the legacy system
    only stores date precision.  Malformed values become NULL with a
    '_bad_{tgt_col}' flag for downstream logging.
    """
    df = df.withColumn(
        tgt_col,
        F.to_timestamp(F.col(src_col), "MM/dd/yyyy")
    )
    # Flag rows where the source was non-null but parsing produced null
    df = df.withColumn(
        f"_bad_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    return df


# ---------------------------------------------------------------------------
# Amount parsing: comma-formatted string -> DecimalType
# ---------------------------------------------------------------------------
def parse_amount_col(
    df: DataFrame,
    src_col: str,
    tgt_col: str,
    precision: int = 12,
    scale: int = 2
) -> DataFrame:
    """
    Parse a comma-formatted amount string (e.g. "285,000" or "271,432.56")
    to Spark DecimalType.

    Steps:
      1. Strip leading/trailing whitespace
      2. Remove commas
      3. Remove dollar signs (if present)
      4. Cast to DecimalType(precision, scale)

    Malformed values become NULL with a '_bad_{tgt_col}' flag.
    """
    cleaned = F.regexp_replace(F.trim(F.col(src_col)), "[,$]", "")
    df = df.withColumn(
        tgt_col,
        cleaned.cast(DecimalType(precision, scale))
    )
    # Flag rows where the source was non-null but casting produced null
    df = df.withColumn(
        f"_bad_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    return df


def parse_int_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """
    Parse a numeric string column to IntegerType.

    Strips commas and whitespace before casting.
    Malformed values become NULL with a '_bad_{tgt_col}' flag.
    """
    cleaned = F.regexp_replace(F.trim(F.col(src_col)), ",", "")
    df = df.withColumn(
        tgt_col,
        cleaned.cast(IntegerType())
    )
    # Flag rows where the source was non-null but casting produced null
    df = df.withColumn(
        f"_bad_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    return df


# ---------------------------------------------------------------------------
# Status code expansion: abbreviation -> full description
# ---------------------------------------------------------------------------
def expand_status_col(
    df: DataFrame,
    src_col: str,
    tgt_col: str,
    mapping: dict
) -> DataFrame:
    """
    Map a status code abbreviation column to its expanded description
    using the provided mapping dictionary.

    Unknown codes are preserved as-is with a '_unmapped_{tgt_col}' flag
    so they can be reviewed rather than silently dropped.
    """
    # Build a Spark map literal from the Python dict
    mapping_expr = F.create_map(
        *[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    df = df.withColumn(
        tgt_col,
        F.coalesce(
            mapping_expr[F.upper(F.trim(F.col(src_col)))],
            F.col(src_col)  # Preserve unknown codes as-is
        )
    )
    # Flag rows with codes that did not match any mapping entry
    known_codes = list(mapping.keys())
    df = df.withColumn(
        f"_unmapped_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull()
            & ~F.upper(F.trim(F.col(src_col))).isin(known_codes),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    return df


def expand_boolean_status_col(
    df: DataFrame,
    src_col: str,
    tgt_col: str,
    mapping: dict
) -> DataFrame:
    """
    Map a status code column to a boolean value (e.g. ACT -> True, INA -> False).

    Unknown codes produce NULL with a flag column.
    """
    mapping_expr = F.create_map(
        *[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    df = df.withColumn(
        tgt_col,
        mapping_expr[F.upper(F.trim(F.col(src_col)))]
    )
    # Flag rows with unmapped codes
    known_codes = list(mapping.keys())
    df = df.withColumn(
        f"_unmapped_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull()
            & ~F.upper(F.trim(F.col(src_col))).isin(known_codes),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    return df


# ---------------------------------------------------------------------------
# Ingestion metadata helpers
# ---------------------------------------------------------------------------
def add_ingestion_metadata(df: DataFrame, source_system: str) -> DataFrame:
    """
    Add standard audit/metadata columns to a DataFrame before writing to Delta.
    """
    return (
        df
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit(source_system))
    )


# ---------------------------------------------------------------------------
# Data quality logging helper
# ---------------------------------------------------------------------------
def log_bad_records(df: DataFrame, table_name: str) -> dict:
    """
    Scan all '_bad_*' and '_unmapped_*' flag columns in the DataFrame,
    count flagged rows, and log warnings for any non-zero counts.

    Returns a dict of {flag_column: count} for downstream reporting.
    """
    flag_cols = [c for c in df.columns if c.startswith("_bad_") or c.startswith("_unmapped_")]
    issues = {}
    for col_name in flag_cols:
        count = df.filter(F.col(col_name) == True).count()  # noqa: E712
        if count > 0:
            logger.warning(
                "[%s] %d records flagged by %s", table_name, count, col_name
            )
            issues[col_name] = count
    if not issues:
        logger.info("[%s] No data quality issues detected during transformation.", table_name)
    return issues


def drop_flag_columns(df: DataFrame) -> DataFrame:
    """
    Remove all internal flag columns (_bad_*, _unmapped_*) before writing
    to the target Delta table.
    """
    flag_cols = [c for c in df.columns if c.startswith("_bad_") or c.startswith("_unmapped_")]
    return df.drop(*flag_cols)
