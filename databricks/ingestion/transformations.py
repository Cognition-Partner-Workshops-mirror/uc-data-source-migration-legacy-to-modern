"""
Common transformation functions for the legacy CDW to Delta Lake migration.

Provides reusable parsing and mapping functions for:
- Date string parsing (MM/DD/YYYY -> DateType/TimestampType)
- Amount string parsing (comma-formatted strings -> DecimalType)
- Status code expansion (abbreviated codes -> full descriptions)
- Null/malformed value handling with error logging
"""

from typing import Optional

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DecimalType,
    IntegerType,
)

# =============================================================================
# Status Code Mappings
# =============================================================================

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


# =============================================================================
# Date Parsing Functions
# =============================================================================


def parse_date_column(col_name: str, alias: Optional[str] = None) -> Column:
    """
    Parse a MM/DD/YYYY string column to DateType.

    Returns NULL for unparseable values rather than failing the pipeline.
    """
    target_name = alias or col_name
    return F.to_date(F.col(col_name), "MM/dd/yyyy").alias(target_name)


def parse_timestamp_column(col_name: str, alias: Optional[str] = None) -> Column:
    """
    Parse a MM/DD/YYYY string column to TimestampType (midnight).

    Returns NULL for unparseable values rather than failing the pipeline.
    """
    target_name = alias or col_name
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy").alias(target_name)


# =============================================================================
# Amount Parsing Functions
# =============================================================================


def parse_amount_column(
    col_name: str,
    precision: int = 12,
    scale: int = 2,
    alias: Optional[str] = None,
) -> Column:
    """
    Parse a comma-formatted amount string to DecimalType.

    Handles formats like "285,000", "271,432.56", "0".
    Returns NULL for unparseable values.
    """
    target_name = alias or col_name
    cleaned = F.regexp_replace(F.col(col_name), ",", "")
    return cleaned.cast(DecimalType(precision, scale)).alias(target_name)


def parse_integer_column(col_name: str, alias: Optional[str] = None) -> Column:
    """
    Parse a string column to IntegerType.

    Handles plain numeric strings like "360", "745".
    Returns NULL for unparseable values.
    """
    target_name = alias or col_name
    cleaned = F.regexp_replace(F.col(col_name), ",", "")
    return cleaned.cast(IntegerType()).alias(target_name)


def parse_rate_column(
    col_name: str,
    precision: int = 5,
    scale: int = 3,
    alias: Optional[str] = None,
) -> Column:
    """
    Parse a rate/percentage string to DecimalType.

    Handles formats like "4.750", "82.5".
    """
    target_name = alias or col_name
    return F.col(col_name).cast(DecimalType(precision, scale)).alias(target_name)


# =============================================================================
# Status Code Expansion Functions
# =============================================================================


def expand_status_column(
    col_name: str,
    mapping: dict,
    alias: Optional[str] = None,
) -> Column:
    """
    Expand abbreviated status codes to full descriptions using a mapping dict.

    Unknown codes are preserved as-is with a '_UNKNOWN' suffix for visibility.
    """
    target_name = alias or col_name
    mapping_expr = F.create_map(
        *[item for pair in mapping.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )
    return (
        F.coalesce(
            mapping_expr[F.upper(F.trim(F.col(col_name)))],
            F.concat(F.col(col_name), F.lit("_UNKNOWN")),
        )
        .alias(target_name)
    )


def expand_boolean_status(col_name: str, alias: Optional[str] = None) -> Column:
    """
    Convert status code to boolean (ACT -> true, anything else -> false).
    """
    target_name = alias or col_name
    return (
        F.when(F.upper(F.trim(F.col(col_name))) == "ACT", F.lit(True))
        .otherwise(F.lit(False))
        .alias(target_name)
    )


# =============================================================================
# Data Quality / Error Tracking
# =============================================================================


def add_ingestion_metadata(df: DataFrame, source_system: str) -> DataFrame:
    """
    Add standard metadata columns for lineage tracking.
    """
    return df.withColumn(
        "_ingestion_ts", F.current_timestamp()
    ).withColumn(
        "_source_system", F.lit(source_system)
    )


def flag_parse_errors(
    df: DataFrame,
    original_col: str,
    parsed_col: str,
    error_col: str,
) -> DataFrame:
    """
    Add an error flag column where the original value was non-null but parsing
    resulted in NULL (indicates malformed data).
    """
    return df.withColumn(
        error_col,
        F.when(
            F.col(original_col).isNotNull() & F.col(parsed_col).isNull(),
            F.lit(True),
        ).otherwise(F.lit(False)),
    )


def log_rejected_records(
    df: DataFrame,
    error_columns: list,
    table_name: str,
    output_path: str,
) -> int:
    """
    Write records with parse errors to a rejection log for review.
    Returns the count of rejected records.
    """
    error_condition = F.lit(False)
    for col in error_columns:
        error_condition = error_condition | F.col(col)

    rejected_df = df.filter(error_condition)
    rejected_count = rejected_df.count()

    if rejected_count > 0:
        rejected_df.withColumn(
            "_rejection_reason",
            F.concat_ws(
                "; ",
                *[
                    F.when(F.col(col), F.lit(col.replace("_error", "")))
                    for col in error_columns
                ],
            ),
        ).write.mode("append").format("delta").save(
            f"{output_path}/rejections/{table_name}"
        )
        print(
            f"[WARN] {table_name}: {rejected_count} records written to rejection log"
        )

    return rejected_count
