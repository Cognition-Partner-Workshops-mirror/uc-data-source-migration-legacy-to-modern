"""
ingest_loan_products.py — PySpark ingestion script for CDW_LN_PROD → loan_products.

Reads the legacy loan product reference data, applies type conversions and
code expansions per column_mappings.md, and writes to the Delta Lake
`loan_warehouse.loan_products` table.

Transformation summary:
  - Date strings (MM/DD/YYYY) → DateType
  - Amount strings with commas → DecimalType
  - Term months string → IntegerType
  - Status code ACT → true, INA → false (boolean)
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
import logging

from common_transforms import (
    parse_date_col,
    parse_amount_col,
    parse_int_col,
    expand_code_to_bool,
    log_null_counts,
    add_ingestion_metadata,
    PRODUCT_STATUS_MAP,
)

logger = logging.getLogger("cdw_migration.loan_products")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/legacy-extract/CDW_LN_PROD"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"


def read_source(spark: SparkSession) -> "DataFrame":
    """Read the legacy CDW_LN_PROD extract (CSV or Parquet)."""
    if SOURCE_FORMAT == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "NULL")
            .option("emptyValue", "")
            .csv(SOURCE_PATH)
        )
    else:
        df = spark.read.parquet(SOURCE_PATH)

    logger.info("Read %d rows from %s (%s)", df.count(), SOURCE_PATH, SOURCE_FORMAT)
    return df


def transform(df: "DataFrame") -> "DataFrame":
    """Apply all column mappings and type conversions for loan products."""

    # --- Date columns ---
    df = parse_date_col(df, "PROD_EFF_DT", "effective_date")
    df = parse_date_col(df, "PROD_EXP_DT", "expiration_date")

    # --- Numeric columns ---
    df = parse_int_col(df, "PROD_TERM_MOS", "term_months")
    df = parse_amount_col(df, "PROD_MIN_AMT", "min_amount", precision=12, scale=2)
    df = parse_amount_col(df, "PROD_MAX_AMT", "max_amount", precision=12, scale=2)

    # --- Status code → boolean ---
    df = expand_code_to_bool(df, "PROD_STAT_CD", "is_active", PRODUCT_STATUS_MAP)

    # --- Direct-copy renames ---
    df = (
        df
        .withColumnRenamed("PROD_CD", "code")
        .withColumnRenamed("PROD_DESC_TXT", "name")
        .withColumnRenamed("PROD_TYP_CD", "type")
        .withColumnRenamed("PROD_RT_TYP", "rate_type")
    )

    # --- Drop original columns that have been transformed ---
    df = df.drop("PROD_EFF_DT", "PROD_EXP_DT", "PROD_TERM_MOS",
                 "PROD_MIN_AMT", "PROD_MAX_AMT", "PROD_STAT_CD")

    # --- Add ingestion metadata ---
    df = add_ingestion_metadata(df, "CDW_LN_PROD")

    # --- Select final column order ---
    df = df.select(
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount",
        "is_active", "effective_date", "expiration_date",
        "_ingestion_ts", "_source_system",
    )

    return df


def validate_pre_write(df: "DataFrame") -> None:
    """Log NULL counts on required fields before writing."""
    critical_cols = ["code", "name", "type", "is_active"]
    log_null_counts(df, critical_cols, TARGET_TABLE)


def write_target(df: "DataFrame") -> None:
    """Write loan products to Delta Lake with MERGE upsert on product code."""
    from delta.tables import DeltaTable

    spark = df.sparkSession
    if DeltaTable.isDeltaTable(spark, TARGET_TABLE):
        target = DeltaTable.forName(spark, TARGET_TABLE)
        (
            target.alias("tgt")
            .merge(df.alias("src"), "tgt.code = src.code")
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )
        logger.info("MERGE completed into %s", TARGET_TABLE)
    else:
        (
            df.write
            .format("delta")
            .mode("overwrite")
            .saveAsTable(TARGET_TABLE)
        )
        logger.info("Initial load completed into %s", TARGET_TABLE)


def main():
    """Entry point — orchestrates read → transform → validate → write."""
    spark = SparkSession.builder.appName("CDW Migration — Loan Products").getOrCreate()
    logger.info("Starting loan products ingestion from %s", SOURCE_PATH)

    raw_df = read_source(spark)
    transformed_df = transform(raw_df)
    validate_pre_write(transformed_df)
    write_target(transformed_df)

    logger.info("Loan products ingestion complete. Rows written: %d", transformed_df.count())


if __name__ == "__main__":
    main()
