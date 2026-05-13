"""
Ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan products table (simulated as CSV/Parquet source)
and transforms it into the modern loan_products Delta Lake table.

Transformations applied:
  - Parse PROD_TERM_MOS (string) -> term_months (INT)
  - Parse PROD_MIN_AMT, PROD_MAX_AMT (comma-formatted) -> DECIMAL
  - Map PROD_STAT_CD to is_active BOOLEAN (ACT -> True, INA -> False)
  - Parse PROD_EFF_DT, PROD_EXP_DT (MM/DD/YYYY) -> DATE
  - Add surrogate product_id
  - Add ingestion metadata columns
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
import logging

from transformations import (
    parse_date_col,
    parse_amount_col,
    parse_int_col,
    expand_boolean_status_col,
    add_ingestion_metadata,
    log_bad_records,
    drop_flag_columns,
    PRODUCT_STATUS_MAP,
)

logger = logging.getLogger("cdw_migration.ingest_loan_products")

DEFAULT_SOURCE_PATH = "/mnt/landing/cdw/CDW_LN_PROD"
DEFAULT_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"


def read_source(spark: SparkSession, source_path: str = DEFAULT_SOURCE_PATH,
                source_format: str = DEFAULT_SOURCE_FORMAT) -> DataFrame:
    """Read legacy CDW_LN_PROD data from the landing zone."""
    if source_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "")
            .option("emptyValue", "")
            .csv(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from %s (%s)", df.count(), source_path, source_format)
    return df


def transform(df: DataFrame) -> DataFrame:
    """
    Apply all transformations to convert legacy CDW_LN_PROD columns
    to the modern loan_products schema.
    """
    # --- Generate surrogate key ---
    df = df.withColumn("product_id", F.monotonically_increasing_id() + 1)

    # --- Direct copy columns (rename from legacy to modern) ---
    df = (
        df
        .withColumnRenamed("PROD_CD", "code")
        .withColumnRenamed("PROD_DESC_TXT", "name")
        .withColumnRenamed("PROD_TYP_CD", "type")
        .withColumnRenamed("PROD_RT_TYP", "rate_type")
    )

    # --- Type conversions ---
    # Parse term months: string -> INT
    df = parse_int_col(df, "PROD_TERM_MOS", "term_months")

    # Parse min/max amounts: comma-formatted string -> DECIMAL(12,2)
    df = parse_amount_col(df, "PROD_MIN_AMT", "min_amount", precision=12, scale=2)
    df = parse_amount_col(df, "PROD_MAX_AMT", "max_amount", precision=12, scale=2)

    # Parse effective/expiration dates: MM/DD/YYYY -> DATE
    df = parse_date_col(df, "PROD_EFF_DT", "effective_date")
    df = parse_date_col(df, "PROD_EXP_DT", "expiration_date")

    # --- Status code to boolean ---
    # ACT -> True, INA -> False
    df = expand_boolean_status_col(df, "PROD_STAT_CD", "is_active", PRODUCT_STATUS_MAP)

    # --- Add ingestion metadata ---
    df = add_ingestion_metadata(df, "CDW_LN_PROD")

    # --- Log data quality issues ---
    log_bad_records(df, TARGET_TABLE)

    # --- Drop flag columns ---
    df = drop_flag_columns(df)

    # Select target columns in correct order
    target_columns = [
        "product_id", "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "is_active", "effective_date",
        "expiration_date", "_ingestion_ts", "_source_system",
    ]
    df = df.select(*target_columns)

    return df


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    """Write the transformed loan_products DataFrame to the Delta Lake table."""
    (
        df.write
        .format("delta")
        .mode(mode)
        .saveAsTable(TARGET_TABLE)
    )
    logger.info("Wrote %d rows to %s", df.count(), TARGET_TABLE)


def run(spark: SparkSession, source_path: str = DEFAULT_SOURCE_PATH,
        source_format: str = DEFAULT_SOURCE_FORMAT) -> DataFrame:
    """Execute the full loan_products ingestion pipeline."""
    logger.info("Starting loan_products ingestion from %s", source_path)
    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform(raw_df)
    write_target(transformed_df)
    logger.info("Loan products ingestion complete.")
    return transformed_df


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_LoanProducts_Ingestion").getOrCreate()
    try:
        src_path = dbutils.widgets.get("source_path")  # noqa: F821
    except Exception:
        src_path = DEFAULT_SOURCE_PATH
    try:
        src_fmt = dbutils.widgets.get("source_format")  # noqa: F821
    except Exception:
        src_fmt = DEFAULT_SOURCE_FORMAT

    run(spark, src_path, src_fmt)
