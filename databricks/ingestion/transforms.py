"""
Shared transformation functions for CDW legacy-to-modern migration.

All parsing functions follow the warn-don't-reject pattern: malformed values
are replaced with None and logged, never silently dropped or exception-raised.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType

# ---------------------------------------------------------------------------
# Status code expansion maps (from column_mappings.md)
# ---------------------------------------------------------------------------

# Loan status abbreviations from CDW_LN_ACCT.LN_STAT_CD -> expanded values
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Borrower status abbreviations from CDW_BORR_MSTR.BORR_STAT_CD
BORROWER_STATUS_MAP = {
    "ACT": "ACTIVE",
    "INA": "INACTIVE",
}

# Product status converts to boolean is_active flag
PRODUCT_STATUS_MAP = {
    "ACT": True,
    "INA": False,
}

# Payment type abbreviations from CDW_PMT_HIST.PMT_TYP_CD
PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

# Payment status abbreviations from CDW_PMT_HIST.PMT_STAT_CD
PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

# Property type abbreviations from CDW_LN_ACCT.PROP_TYP_CD
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}


# ---------------------------------------------------------------------------
# Parsing UDFs (column-level transforms)
# ---------------------------------------------------------------------------

def parse_legacy_date(col_name: str) -> F.Column:
    """Parse MM/dd/yyyy string to DateType. Returns null for unparseable values."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_timestamp(col_name: str) -> F.Column:
    """Parse MM/dd/yyyy string to TimestampType (midnight). Returns null for unparseable."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_amount(col_name: str, precision: int = 12, scale: int = 2) -> F.Column:
    """
    Remove commas and dollar signs from a VARCHAR amount, cast to DecimalType.
    Returns null for non-numeric strings.
    """
    # Strip dollar signs and commas (e.g. "$285,000" -> "285000") then cast
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), r"[$,]", "")
    return cleaned.cast(DecimalType(precision, scale))


def parse_legacy_integer(col_name: str) -> F.Column:
    """Remove commas from a VARCHAR integer string, cast to IntegerType."""
    cleaned = F.regexp_replace(F.trim(F.col(col_name)), r",", "")
    return cleaned.cast(IntegerType())


def expand_status_code(col_name: str, mapping: dict, default: str = None) -> F.Column:
    """Map abbreviated status codes to expanded values via a CASE expression."""
    # Normalize to uppercase and build chained CASE/WHEN expression
    col = F.trim(F.upper(F.col(col_name)))
    expr = F.when(col.isNull(), F.lit(default))
    for code, expanded in mapping.items():
        if isinstance(expanded, bool):
            expr = expr.when(col == code, F.lit(expanded))
        else:
            expr = expr.when(col == code, F.lit(expanded))
    # Fallback: prefix unknown codes with "UNKNOWN:" so they're visible but not lost
    expr = expr.otherwise(
        F.concat(F.lit("UNKNOWN:"), F.coalesce(F.col(col_name), F.lit("NULL")))
    )
    return expr


# ---------------------------------------------------------------------------
# Null-safety & warning helpers
# ---------------------------------------------------------------------------

def flag_nulls(df: DataFrame, columns: list[str], record_id_col: str) -> DataFrame:
    """
    Add a _null_warnings column listing any required fields that are null/blank.
    """
    conditions = [
        F.when(
            F.col(c).isNull() | (F.trim(F.col(c)) == ""),
            F.lit(c)
        )
        for c in columns
    ]
    # Collect null field names into an array, remove nulls, then format as warning string
    null_list = F.array_compact(F.array(*conditions))
    return df.withColumn(
        "_null_warnings",
        F.when(F.size(null_list) > 0,
               F.concat(F.col(record_id_col), F.lit(": null fields -> "),
                        F.array_join(null_list, ", ")))
    )


def flag_parse_failures(df: DataFrame, raw_col: str, parsed_col: str,
                         record_id_col: str) -> DataFrame:
    """
    Add a warning column when the raw value is non-null but the parsed value is null
    (indicating a parse failure).
    """
    warning_col = f"_parse_warn_{parsed_col}"
    return df.withColumn(
        warning_col,
        F.when(
            F.col(raw_col).isNotNull()
            & (F.trim(F.col(raw_col)) != "")
            & F.col(parsed_col).isNull(),
            F.concat(
                F.col(record_id_col),
                F.lit(f": failed to parse {raw_col}='"),
                F.col(raw_col),
                F.lit(f"' into {parsed_col}")
            )
        )
    )
