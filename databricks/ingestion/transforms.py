"""
Shared transformation functions for legacy CDW → modern Delta Lake migration.

These functions encapsulate the type conversion, status code expansion,
and data cleansing logic documented in data/mappings/column_mappings.md.
All parse functions are null-safe and return None on failure with logging,
preventing silent record drops during ingestion.
"""

from pyspark.sql import Column
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# =============================================================================
# Date Parsing
# Legacy CDW stores all dates as MM/DD/YYYY strings in VARCHAR columns.
# =============================================================================

def parse_legacy_date(col: Column) -> Column:
    """Parse MM/dd/yyyy string to DateType. Returns null for unparseable values."""
    return F.to_date(F.trim(col), "MM/dd/yyyy")


def parse_legacy_timestamp(col: Column) -> Column:
    """Parse MM/dd/yyyy string to TimestampType (midnight). Returns null for unparseable values."""
    return F.to_timestamp(F.trim(col), "MM/dd/yyyy")


# =============================================================================
# Numeric Parsing
# Legacy CDW stores all numbers as VARCHAR, often with commas (e.g., "285,000").
# =============================================================================

def parse_legacy_amount(col: Column, precision: int = 12, scale: int = 2) -> Column:
    """
    Parse comma-separated amount string to DecimalType.
    Strips commas and whitespace before casting.
    Returns null for non-numeric values (logged by quality framework).
    """
    # Remove commas and trim whitespace, then cast to decimal
    cleaned = F.regexp_replace(F.trim(col), ",", "")
    return cleaned.cast(DecimalType(precision, scale))


def parse_legacy_decimal(col: Column, precision: int = 5, scale: int = 3) -> Column:
    """
    Parse plain decimal string (e.g., "4.750") to DecimalType.
    Also handles commas for robustness.
    """
    cleaned = F.regexp_replace(F.trim(col), ",", "")
    return cleaned.cast(DecimalType(precision, scale))


def parse_legacy_integer(col: Column) -> Column:
    """Parse integer string to IntegerType. Returns null for non-numeric values."""
    return F.trim(col).cast(IntegerType())


# =============================================================================
# Status Code Expansion
# Legacy CDW uses abbreviated status codes. The modern schema uses full labels.
# Mappings are defined in data/mappings/column_mappings.md.
# =============================================================================

def expand_borrower_status(col: Column) -> Column:
    """Expand borrower status: ACT→ACTIVE, INA→INACTIVE. Unknown codes preserved as-is."""
    return (
        F.when(F.trim(col) == "ACT", F.lit("ACTIVE"))
         .when(F.trim(col) == "INA", F.lit("INACTIVE"))
         .otherwise(F.trim(col))
    )


def expand_loan_status(col: Column) -> Column:
    """Expand loan status: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE."""
    return (
        F.when(F.trim(col) == "ACT", F.lit("ACTIVE"))
         .when(F.trim(col) == "CLO", F.lit("CLOSED"))
         .when(F.trim(col) == "DFT", F.lit("DEFAULT"))
         .when(F.trim(col) == "FRB", F.lit("FORBEARANCE"))
         .otherwise(F.trim(col))
    )


def expand_property_type(col: Column) -> Column:
    """Expand property type: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse."""
    return (
        F.when(F.trim(col) == "SFR", F.lit("Single Family"))
         .when(F.trim(col) == "CND", F.lit("Condominium"))
         .when(F.trim(col) == "MFR", F.lit("Multi-Family"))
         .when(F.trim(col) == "TWN", F.lit("Townhouse"))
         .otherwise(F.trim(col))
    )


def expand_payment_type(col: Column) -> Column:
    """Expand payment type: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT."""
    return (
        F.when(F.trim(col) == "REG", F.lit("REGULAR"))
         .when(F.trim(col) == "EXT", F.lit("EXTRA"))
         .when(F.trim(col) == "PRT", F.lit("PARTIAL"))
         .when(F.trim(col) == "PRE", F.lit("PREPAYMENT"))
         .otherwise(F.trim(col))
    )


def expand_payment_status(col: Column) -> Column:
    """Expand payment status: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING."""
    return (
        F.when(F.trim(col) == "PST", F.lit("POSTED"))
         .when(F.trim(col) == "REV", F.lit("REVERSED"))
         .when(F.trim(col) == "NSF", F.lit("NSF"))
         .when(F.trim(col) == "PND", F.lit("PENDING"))
         .otherwise(F.trim(col))
    )


def expand_product_status_to_boolean(col: Column) -> Column:
    """Convert product status to boolean: ACT→true, anything else→false."""
    return F.when(F.trim(col) == "ACT", F.lit(True)).otherwise(F.lit(False))
