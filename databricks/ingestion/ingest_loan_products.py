"""
PySpark ingestion script: CDW_LN_PROD → loan_warehouse.loan_products

Reads legacy loan product data from CSV/Parquet source files, applies all
transformations defined in data/mappings/column_mappings.md, and writes
to the Delta Lake loan_products table.

Transformations applied:
  - PROD_TERM_MOS (string) → term_months (INT)
  - PROD_MIN_AMT, PROD_MAX_AMT (comma strings) → DECIMAL(12,2)
  - PROD_STAT_CD (ACT/INA) → is_active (BOOLEAN)
  - PROD_EFF_DT, PROD_EXP_DT (MM/DD/YYYY) → DATE

Usage:
  Run as a Databricks notebook or submit via spark-submit.
  Must be executed BEFORE ingest_loan_accounts.py (products must exist for FK lookups).
"""

import logging
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
)

# Import shared transformation utilities
from transform_utils import (
    parse_date_col,
    parse_amount_col,
    parse_int_col,
    expand_status_to_bool,
    add_etl_metadata,
    tag_malformed_rows,
    PRODUCT_STATUS_MAP,
)

# =============================================================================
# Configuration
# =============================================================================
SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_ln_prod/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"
WRITE_MODE = "overwrite"

# =============================================================================
# Logging setup
# =============================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_loan_products")

# =============================================================================
# Legacy source schema
# =============================================================================
LEGACY_SCHEMA = StructType([
    StructField("PROD_CD", StringType(), True),
    StructField("PROD_DESC_TXT", StringType(), True),
    StructField("PROD_TYP_CD", StringType(), True),
    StructField("PROD_TERM_MOS", StringType(), True),
    StructField("PROD_RT_TYP", StringType(), True),
    StructField("PROD_MIN_AMT", StringType(), True),
    StructField("PROD_MAX_AMT", StringType(), True),
    StructField("PROD_STAT_CD", StringType(), True),
    StructField("PROD_EFF_DT", StringType(), True),
    StructField("PROD_EXP_DT", StringType(), True),
])


def read_source(spark):
    """Read the legacy CDW_LN_PROD data from the configured source path and format."""
    logger.info(f"Reading source data from {SOURCE_PATH} (format={SOURCE_FORMAT})")
    if SOURCE_FORMAT == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .schema(LEGACY_SCHEMA)
            .csv(SOURCE_PATH)
        )
    elif SOURCE_FORMAT == "parquet":
        df = spark.read.schema(LEGACY_SCHEMA).parquet(SOURCE_PATH)
    else:
        raise ValueError(f"Unsupported source format: {SOURCE_FORMAT}")

    record_count = df.count()
    logger.info(f"Read {record_count} records from legacy CDW_LN_PROD")
    return df


def transform(df):
    """
    Apply all column mappings and transformations to convert legacy loan product
    data to the modern loan_products schema.
    """
    logger.info("Applying transformations for CDW_LN_PROD → loan_products")

    # Tag rows with potential quality issues
    df_tagged = tag_malformed_rows(df, [
        (F.col("PROD_CD").isNull(), "NULL_PROD_CD"),
        (F.col("PROD_DESC_TXT").isNull(), "NULL_DESCRIPTION"),
        (F.col("PROD_TYP_CD").isNull(), "NULL_TYPE"),
        (F.col("PROD_TERM_MOS").isNotNull() &
         ~F.col("PROD_TERM_MOS").rlike(r"^\d+$"), "MALFORMED_TERM"),
    ])

    # Log flagged records
    flagged = df_tagged.filter(F.col("_quality_flags").isNotNull())
    flagged_count = flagged.count()
    if flagged_count > 0:
        logger.warning(
            f"Found {flagged_count} records with quality issues in CDW_LN_PROD. "
            "Records preserved — not dropped."
        )
        flagged.select("PROD_CD", "_quality_flags").show(truncate=False)

    # Apply column transformations per the mapping document
    transformed = df_tagged.select(
        # Surrogate key
        F.monotonically_increasing_id().alias("product_id"),

        # Natural key: direct copy
        F.trim(F.col("PROD_CD")).alias("code"),

        # Product attributes
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.trim(F.col("PROD_TYP_CD")).alias("type"),
        parse_int_col("PROD_TERM_MOS", "term_months"),
        F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),

        # Amount fields: remove commas, parse to decimal
        parse_amount_col("PROD_MIN_AMT", "min_amount"),
        parse_amount_col("PROD_MAX_AMT", "max_amount"),

        # Status: convert to boolean (ACT→true, INA→false)
        expand_status_to_bool("PROD_STAT_CD", PRODUCT_STATUS_MAP, "is_active"),

        # Date fields: parse MM/DD/YYYY → DATE
        parse_date_col("PROD_EFF_DT", "effective_date"),
        parse_date_col("PROD_EXP_DT", "expiration_date"),
    )

    # Add ETL metadata
    transformed = add_etl_metadata(transformed, "CDW_LN_PROD")

    logger.info(f"Transformation complete. Output row count: {transformed.count()}")
    return transformed


def write_target(df):
    """Write the transformed loan products DataFrame to the Delta Lake target table."""
    logger.info(f"Writing to {TARGET_TABLE} (mode={WRITE_MODE})")
    (
        df.write
        .format("delta")
        .mode(WRITE_MODE)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info(f"Successfully wrote data to {TARGET_TABLE}")


def main():
    """Main entry point: read → transform → write for loan products ingestion."""
    spark = SparkSession.builder.appName("Ingest_CDW_LN_PROD").getOrCreate()
    logger.info("=" * 70)
    logger.info("Starting loan product ingestion: CDW_LN_PROD → loan_warehouse.loan_products")
    logger.info("=" * 70)

    try:
        source_df = read_source(spark)
        target_df = transform(source_df)
        write_target(target_df)
        logger.info("Loan product ingestion completed successfully")
    except Exception as e:
        logger.error(f"Loan product ingestion FAILED: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
