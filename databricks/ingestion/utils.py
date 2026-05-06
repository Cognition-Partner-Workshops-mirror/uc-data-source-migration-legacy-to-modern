"""
Shared utility functions for data parsing and transformation.

All transformations log warnings for malformed values rather than silently
dropping records. A quarantine table captures rows that fail critical parsing.
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DateType, DecimalType, IntegerType, TimestampType


# ---------------------------------------------------------------------------
# Date Parsing
# ---------------------------------------------------------------------------

def parse_date_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse MM/DD/YYYY string column to DateType.

    Records with unparseable dates get NULL and are flagged in _parse_errors.
    """
    return df.withColumn(
        tgt_col,
        F.to_date(F.col(src_col), "MM/dd/yyyy")
    ).withColumn(
        f"_err_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.concat(F.lit(f"Failed to parse date from {src_col}: "), F.col(src_col))
        )
    )


def parse_timestamp_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse MM/DD/YYYY string to TimestampType (midnight)."""
    return df.withColumn(
        tgt_col,
        F.to_timestamp(F.col(src_col), "MM/dd/yyyy")
    ).withColumn(
        f"_err_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.concat(F.lit(f"Failed to parse timestamp from {src_col}: "), F.col(src_col))
        )
    )


# ---------------------------------------------------------------------------
# Amount / Numeric Parsing
# ---------------------------------------------------------------------------

def parse_amount_col(df: DataFrame, src_col: str, tgt_col: str,
                     precision: int = 12, scale: int = 2) -> DataFrame:
    """Parse comma-formatted amount string (e.g., '285,000') to DecimalType.

    Removes commas and casts. Flags unparseable values.
    """
    cleaned = F.regexp_replace(F.col(src_col), ",", "")
    return df.withColumn(
        tgt_col,
        cleaned.cast(DecimalType(precision, scale))
    ).withColumn(
        f"_err_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.concat(F.lit(f"Failed to parse amount from {src_col}: "), F.col(src_col))
        )
    )


def parse_int_col(df: DataFrame, src_col: str, tgt_col: str) -> DataFrame:
    """Parse string column to IntegerType."""
    return df.withColumn(
        tgt_col,
        F.col(src_col).cast(IntegerType())
    ).withColumn(
        f"_err_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.concat(F.lit(f"Failed to parse integer from {src_col}: "), F.col(src_col))
        )
    )


def parse_decimal_col(df: DataFrame, src_col: str, tgt_col: str,
                      precision: int = 5, scale: int = 3) -> DataFrame:
    """Parse string column to DecimalType without comma removal."""
    return df.withColumn(
        tgt_col,
        F.col(src_col).cast(DecimalType(precision, scale))
    ).withColumn(
        f"_err_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & F.col(tgt_col).isNull(),
            F.concat(F.lit(f"Failed to parse decimal from {src_col}: "), F.col(src_col))
        )
    )


# ---------------------------------------------------------------------------
# Status Code Expansion
# ---------------------------------------------------------------------------

STATUS_MAPS = {
    "loan_status": {
        "ACT": "ACTIVE",
        "CLO": "CLOSED",
        "DFT": "DEFAULT",
        "FRB": "FORBEARANCE",
    },
    "borrower_status": {
        "ACT": "ACTIVE",
        "INA": "INACTIVE",
    },
    "product_status": {
        "ACT": True,
        "INA": False,
    },
    "payment_type": {
        "REG": "REGULAR",
        "EXT": "EXTRA",
        "PRT": "PARTIAL",
        "PRE": "PREPAYMENT",
    },
    "payment_status": {
        "PST": "POSTED",
        "REV": "REVERSED",
        "NSF": "NSF",
        "PND": "PENDING",
    },
    "property_type": {
        "SFR": "Single Family",
        "CND": "Condominium",
        "MFR": "Multi-Family",
        "TWN": "Townhouse",
    },
}


def expand_status_code(df: DataFrame, src_col: str, tgt_col: str,
                       map_name: str) -> DataFrame:
    """Expand abbreviated status codes using predefined mappings.

    Unknown codes are preserved as-is with a warning flag.
    """
    mapping = STATUS_MAPS[map_name]
    mapping_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])

    return df.withColumn(
        tgt_col,
        F.coalesce(mapping_expr[F.col(src_col)], F.col(src_col))
    ).withColumn(
        f"_err_{tgt_col}",
        F.when(
            F.col(src_col).isNotNull() & mapping_expr[F.col(src_col)].isNull(),
            F.concat(F.lit(f"Unknown code in {src_col}: "), F.col(src_col))
        )
    )


# ---------------------------------------------------------------------------
# Error Handling / Quarantine
# ---------------------------------------------------------------------------

def collect_parse_errors(df: DataFrame) -> DataFrame:
    """Aggregate all _err_ columns into a single array column for logging."""
    err_cols = [c for c in df.columns if c.startswith("_err_")]
    if not err_cols:
        return df.withColumn("_parse_errors", F.array())

    non_null_errors = F.array_compact(F.array(*[F.col(c) for c in err_cols]))
    result = df.withColumn("_parse_errors", non_null_errors)
    # Drop individual error columns
    return result.drop(*err_cols)


def quarantine_bad_records(df: DataFrame, table_name: str,
                           spark: SparkSession) -> DataFrame:
    """Separate records with parse errors into a quarantine table.

    Returns the clean DataFrame (records with no errors).
    Records with errors are written to loan_warehouse._quarantine_{table_name}.
    """
    df_with_errors = collect_parse_errors(df)

    bad_records = df_with_errors.filter(F.size("_parse_errors") > 0)
    good_records = df_with_errors.filter(F.size("_parse_errors") == 0)

    bad_count = bad_records.count()
    if bad_count > 0:
        print(f"[WARN] {bad_count} records quarantined for {table_name}")
        bad_records.withColumn("_quarantine_ts", F.current_timestamp()).write \
            .mode("append") \
            .format("delta") \
            .saveAsTable(f"loan_warehouse._quarantine_{table_name}")

    return good_records.drop("_parse_errors")


# ---------------------------------------------------------------------------
# Source Reading
# ---------------------------------------------------------------------------

def read_legacy_source(spark: SparkSession, source_path: str,
                       file_format: str = "csv") -> DataFrame:
    """Read legacy source data from CSV or Parquet files.

    Args:
        spark: Active SparkSession
        source_path: Path to the source file(s) (DBFS, S3, ADLS, etc.)
        file_format: 'csv' or 'parquet'

    Returns:
        Raw DataFrame with all string columns (matching legacy VARCHAR schema)
    """
    if file_format == "csv":
        return spark.read \
            .option("header", "true") \
            .option("inferSchema", "false") \
            .csv(source_path)
    elif file_format == "parquet":
        return spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported file format: {file_format}")
