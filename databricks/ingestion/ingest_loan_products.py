"""
Ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan products table (simulated as CSV/Parquet),
applies type conversions, and writes to Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from databricks.ingestion.transforms import (
    parse_date_col,
    parse_amount_col,
    parse_int_col,
    expand_bool_status,
    quarantine_nulls,
    log_row_counts,
    PRODUCT_STATUS_MAP,
    logger,
)

TARGET_TABLE = "loan_warehouse.loan_products"
SOURCE_TABLE = "CDW_LN_PROD"
REQUIRED_COLS = ["code", "name", "type", "term_months", "rate_type"]


def read_source(spark: SparkSession, source_path: str, source_format: str = "csv") -> DataFrame:
    """Read legacy loan product data from CSV or Parquet source files."""
    if source_format == "csv":
        df = (
            spark.read.format("csv")
            .option("header", "true")
            .option("inferSchema", "false")
            .load(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from %s (%s)", df.count(), source_path, source_format)
    return df


def transform(df: DataFrame) -> DataFrame:
    """Transform legacy loan product data to modern schema.

    Transformations:
        - Rename cryptic columns to meaningful names
        - Parse term months string to integer
        - Parse min/max amount strings to decimal
        - Parse effective/expiration date strings to DateType
        - Convert status code to boolean (ACT -> true, INA -> false)
    """
    # Rename columns
    df = (
        df.withColumnRenamed("PROD_CD", "code")
        .withColumnRenamed("PROD_DESC_TXT", "name")
        .withColumnRenamed("PROD_TYP_CD", "type")
        .withColumnRenamed("PROD_RT_TYP", "rate_type")
    )

    # Parse numerics
    df = parse_int_col(df, "PROD_TERM_MOS", "term_months")
    df = parse_amount_col(df, "PROD_MIN_AMT", "min_amount")
    df = parse_amount_col(df, "PROD_MAX_AMT", "max_amount")

    # Parse dates
    df = parse_date_col(df, "PROD_EFF_DT", "effective_date")
    df = parse_date_col(df, "PROD_EXP_DT", "expiration_date")

    # Convert status to boolean
    df = expand_bool_status(df, "PROD_STAT_CD", "is_active", PRODUCT_STATUS_MAP, default=True)

    # Add migration metadata
    df = df.withColumn("_migration_source", F.lit(SOURCE_TABLE))
    df = df.withColumn("_migrated_at", F.current_timestamp())

    # Select final columns
    df = df.select(
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "is_active",
        "effective_date", "expiration_date",
        "_migration_source", "_migrated_at",
    )

    return df


def load(df: DataFrame, mode: str = "overwrite"):
    """Write transformed loan product DataFrame to Delta Lake."""
    df.write.format("delta").mode(mode).saveAsTable(TARGET_TABLE)
    logger.info("Wrote %d rows to %s", df.count(), TARGET_TABLE)


def run(spark: SparkSession, source_path: str, source_format: str = "csv",
        write_mode: str = "overwrite"):
    """Execute the full loan product ingestion pipeline.

    Returns:
        Tuple of (valid_df, quarantine_df).
    """
    logger.info("=== Starting loan product ingestion from %s ===", source_path)

    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform(raw_df)

    valid_df, quarantine_df = quarantine_nulls(transformed_df, REQUIRED_COLS, TARGET_TABLE)
    src_count, tgt_count = log_row_counts(raw_df, valid_df, TARGET_TABLE)

    load(valid_df, mode=write_mode)

    logger.info("=== Loan product ingestion complete: %d/%d rows loaded ===", tgt_count, src_count)
    return valid_df, quarantine_df
