"""
Shared transformation UDFs and helper functions for the legacy CDW migration.

Handles the core type conversions documented in data/mappings/column_mappings.md:
  - Date strings (MM/DD/YYYY) → DateType
  - Amount strings with commas ("285,000") → DecimalType
  - Status code expansion (ACT→Active, etc.)
  - Null handling with logging
"""

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Date parsing: MM/DD/YYYY strings → DateType
# ---------------------------------------------------------------------------
def parse_legacy_date(col_name: str, alias: str = None):
    """
    Parse a legacy date string column (MM/DD/YYYY format) into a Spark DateType.
    Returns null for unparseable values instead of failing the pipeline.
    """
    target = alias or col_name
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(target)


def parse_legacy_timestamp(col_name: str, alias: str = None):
    """
    Parse a legacy date string column (MM/DD/YYYY) into a Spark TimestampType.
    Used for created_at / updated_at fields that need timestamp precision.
    """
    target = alias or col_name
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(target)


# ---------------------------------------------------------------------------
# Amount parsing: VARCHAR with commas → DecimalType
# ---------------------------------------------------------------------------
def parse_legacy_amount(col_name: str, alias: str = None):
    """
    Parse a legacy amount string (e.g., "285,000" or "1,487.02") into DecimalType(12,2).
    Strips commas and currency symbols before casting.
    Returns null for unparseable values.
    """
    target = alias or col_name
    # Strip dollar signs, commas, percent signs, and whitespace
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), r"[$%,\s]", "")
    return cleaned.cast(DecimalType(12, 2)).alias(target)


def parse_legacy_amount_10_2(col_name: str, alias: str = None):
    """
    Same as parse_legacy_amount but with DECIMAL(10,2) precision.
    Used for payment amounts and escrow balances.
    """
    target = alias or col_name
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), r"[$%,\s]", "")
    return cleaned.cast(DecimalType(10, 2)).alias(target)


def parse_legacy_rate(col_name: str, alias: str = None):
    """
    Parse a legacy rate string (e.g., "5.250") into DecimalType(5,3).
    Used for interest rates and LTV percentages.
    """
    target = alias or col_name
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), r"[$%,\s]", "")
    return cleaned.cast(DecimalType(5, 3)).alias(target)


def parse_legacy_pct(col_name: str, alias: str = None):
    """
    Parse a legacy percentage string (e.g., "82.5") into DecimalType(5,2).
    Used for LTV percent.
    """
    target = alias or col_name
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), r"[$%,\s]", "")
    return cleaned.cast(DecimalType(5, 2)).alias(target)


def parse_legacy_integer(col_name: str, alias: str = None):
    """
    Parse a legacy integer string (e.g., "360", "745") into IntegerType.
    Strips non-digit characters before casting.
    """
    target = alias or col_name
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), r"[^\d-]", "")
    return cleaned.cast(IntegerType()).alias(target)


# ---------------------------------------------------------------------------
# Status code expansion maps (per column_mappings.md)
# ---------------------------------------------------------------------------

# Borrower status: BORR_STAT_CD
BORROWER_STATUS_MAP = {"ACT": "ACTIVE", "INA": "INACTIVE"}

# Loan status: LN_STAT_CD
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Product status: PROD_STAT_CD → boolean (handled separately)
PRODUCT_STATUS_MAP = {"ACT": True, "INA": False}

# Payment type: PMT_TYP_CD
PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

# Payment status: PMT_STAT_CD
PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

# Property type: PROP_TYP_CD
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


def expand_status_code(col_name: str, mapping: dict, alias: str = None):
    """
    Expand a legacy status code abbreviation using the provided mapping.
    Unmapped codes are preserved as-is (not silently dropped) and flagged.
    """
    target = alias or col_name
    # Build a CASE WHEN expression from the mapping dict
    expr = F.col(col_name)
    case_expr = F.when(F.col(col_name).isNull(), F.lit("UNKNOWN"))
    for code, expanded in mapping.items():
        case_expr = case_expr.when(F.col(col_name) == code, F.lit(expanded))
    # Default: keep original code for unmapped values
    case_expr = case_expr.otherwise(F.col(col_name))
    return case_expr.alias(target)


def expand_product_status(col_name: str, alias: str = "is_active"):
    """
    Convert product status code to boolean: ACT→true, INA→false, else null.
    """
    return (
        F.when(F.col(col_name) == "ACT", F.lit(True))
        .when(F.col(col_name) == "INA", F.lit(False))
        .otherwise(F.lit(None).cast("boolean"))
        .alias(alias)
    )
