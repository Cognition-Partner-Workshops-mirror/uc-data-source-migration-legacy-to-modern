"""
Shared transformation utilities for the CDW legacy-to-modern migration pipeline.

Provides reusable UDFs and helper functions for:
  - Parsing legacy MM/DD/YYYY date strings to DateType / TimestampType
  - Parsing comma-formatted amount strings ("285,000") to DecimalType
  - Expanding cryptic status code abbreviations to readable values
  - Null-safe wrappers that log malformed values instead of silently dropping rows
"""

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, TimestampType, IntegerType
from pyspark.sql import DataFrame
import logging

logger = logging.getLogger("cdw_migration")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Status code expansion mappings
# ---------------------------------------------------------------------------

# Borrower status codes (CDW_BORR_MSTR.BORR_STAT_CD)
BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
}

# Loan status codes (CDW_LN_ACCT.LN_STAT_CD)
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
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

# Loan product status codes (CDW_LN_PROD.PROD_STAT_CD)
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}

# Property type codes (CDW_LN_ACCT.PROP_TYP_CD)
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


def expand_status_code(column_name: str, mapping: dict, fallback: str = "UNKNOWN") -> F.Column:
    """
    Build a CASE WHEN expression that expands legacy status codes to readable values.
    Unmapped codes are preserved with the fallback prefix for investigation rather than
    being silently dropped.
    """
    expr = F.col(column_name)
    case_expr = F.when(F.col(column_name).isNull(), F.lit(None))
    for code, expanded in mapping.items():
        if isinstance(expanded, bool):
            # Boolean mapping for product status
            case_expr = case_expr.when(F.upper(expr) == code, F.lit(expanded))
        else:
            case_expr = case_expr.when(F.upper(expr) == code, F.lit(expanded))
    # Unmapped codes: preserve original with prefix so they can be investigated
    case_expr = case_expr.otherwise(F.concat(F.lit(f"{fallback}: "), expr))
    return case_expr


def parse_date_mmddyyyy(column_name: str) -> F.Column:
    """
    Parse a legacy MM/DD/YYYY date string to DateType.
    Returns null for unparseable values — the quality framework catches these downstream.
    """
    return F.to_date(F.col(column_name), "MM/dd/yyyy")


def parse_timestamp_mmddyyyy(column_name: str) -> F.Column:
    """
    Parse a legacy MM/DD/YYYY date string to TimestampType (midnight of that date).
    Returns null for unparseable values.
    """
    return F.to_timestamp(F.col(column_name), "MM/dd/yyyy")


def parse_decimal_amount(column_name: str, precision: int = 12, scale: int = 2) -> F.Column:
    """
    Parse a legacy comma-formatted amount string (e.g. "285,000" or "1,487.02")
    to DecimalType by stripping commas and casting.
    Returns null for unparseable values.
    """
    return F.regexp_replace(F.col(column_name), ",", "").cast(DecimalType(precision, scale))


def parse_integer(column_name: str) -> F.Column:
    """
    Parse a legacy VARCHAR numeric string to IntegerType.
    Returns null for unparseable values.
    """
    return F.col(column_name).cast(IntegerType())


def tag_malformed_rows(df: DataFrame, column_name: str, parsed_column_name: str) -> DataFrame:
    """
    Add a boolean flag column indicating rows where the parsed value is null but the
    source value was non-null (i.e., the parse failed). This allows the quality framework
    to report on malformed values without dropping records.
    """
    flag_col = f"_malformed_{column_name}"
    return df.withColumn(
        flag_col,
        F.when(
            F.col(column_name).isNotNull() & F.col(parsed_column_name).isNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )


def log_unmapped_codes(df: DataFrame, column_name: str, mapped_column_name: str,
                       table_label: str) -> None:
    """
    Log a warning for any rows where the expanded status contains 'UNKNOWN:',
    indicating an unmapped legacy code.
    """
    unmapped = df.filter(F.col(mapped_column_name).contains("UNKNOWN:"))
    count = unmapped.count()
    if count > 0:
        logger.warning(
            "[%s] Found %d rows with unmapped code in column '%s'. "
            "Sample values: %s",
            table_label,
            count,
            column_name,
            [row[column_name] for row in unmapped.select(column_name).limit(10).collect()],
        )
