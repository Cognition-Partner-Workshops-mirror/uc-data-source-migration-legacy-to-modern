"""
PySpark Ingestion Script: CDW_LN_PROD -> loan_products
=======================================================
Reads legacy loan product reference data, converts all-VARCHAR columns to
proper Spark SQL types, converts the status code to a boolean is_active flag,
and writes to the Delta Lake loan_products table.

Transformation Summary:
  - PROD_TERM_MOS   -> IntegerType
  - PROD_MIN_AMT, PROD_MAX_AMT -> DecimalType(12,2) (commas removed)
  - PROD_STAT_CD    -> BooleanType (ACT -> true, INA -> false)
  - PROD_EFF_DT, PROD_EXP_DT -> DateType (MM/DD/YYYY -> DATE)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, DecimalType
import logging

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "/mnt/legacy-data/CDW_LN_PROD"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_products"

logger = logging.getLogger("ingest_loan_products")
logging.basicConfig(level=logging.INFO)


def read_legacy_source(spark: SparkSession, path: str) -> DataFrame:
    """Read legacy CDW_LN_PROD data from CSV or Parquet source files."""
    try:
        df = spark.read.parquet(path)
        logger.info("Read legacy loan product data from Parquet: %s", path)
    except Exception:
        df = spark.read.option("header", "true").option("inferSchema", "false").csv(path)
        logger.info("Read legacy loan product data from CSV: %s", path)
    logger.info("Source row count: %d", df.count())
    return df


def parse_legacy_date(col_name: str):
    """Convert MM/DD/YYYY VARCHAR string to DateType."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_amount(col_name: str):
    """Remove commas and dollar signs from VARCHAR amount, cast to DecimalType."""
    return F.regexp_replace(F.col(col_name), "[,$]", "").cast(DecimalType(12, 2))


def transform_loan_products(df: DataFrame) -> DataFrame:
    """Apply column transformations per data/mappings/column_mappings.md.

    Key conversions:
      - PROD_STAT_CD: ACT -> true (is_active), anything else -> false
      - PROD_TERM_MOS: VARCHAR -> INT
      - Amount fields: comma-formatted string -> DECIMAL(12,2)
      - Date fields: MM/DD/YYYY -> DATE
    """
    return (
        df
        .withColumn("code", F.col("PROD_CD"))
        .withColumn("name", F.col("PROD_DESC_TXT"))
        .withColumn("type", F.col("PROD_TYP_CD"))
        .withColumn("term_months", F.col("PROD_TERM_MOS").cast(IntegerType()))
        .withColumn("rate_type", F.col("PROD_RT_TYP"))
        .withColumn("min_amount", parse_legacy_amount("PROD_MIN_AMT"))
        .withColumn("max_amount", parse_legacy_amount("PROD_MAX_AMT"))
        # Status to boolean: ACT means active, everything else is inactive
        .withColumn("is_active", F.when(F.col("PROD_STAT_CD") == "ACT", F.lit(True)).otherwise(F.lit(False)))
        .withColumn("effective_date", parse_legacy_date("PROD_EFF_DT"))
        .withColumn("expiration_date", parse_legacy_date("PROD_EXP_DT"))
        # Lineage metadata
        .withColumn("_legacy_source", F.lit("CDW_LN_PROD"))
        .withColumn("_ingested_at", F.current_timestamp())
        .select(
            "code", "name", "type", "term_months", "rate_type",
            "min_amount", "max_amount", "is_active",
            "effective_date", "expiration_date",
            "_legacy_source", "_ingested_at"
        )
    )


def quarantine_bad_records(df: DataFrame) -> tuple:
    """Separate records with null required fields.

    Returns (good_df, bad_df). Bad records are written to a quarantine table
    for manual review rather than being silently dropped.
    """
    required_not_null = (
        F.col("code").isNotNull()
        & F.col("name").isNotNull()
        & F.col("type").isNotNull()
        & F.col("term_months").isNotNull()
        & F.col("min_amount").isNotNull()
        & F.col("max_amount").isNotNull()
        & F.col("effective_date").isNotNull()
        & F.col("expiration_date").isNotNull()
    )

    good_df = df.filter(required_not_null)
    bad_df = df.filter(~required_not_null)

    bad_count = bad_df.count()
    if bad_count > 0:
        logger.warning("Quarantined %d loan product records with null required fields", bad_count)

    return good_df, bad_df


def write_to_delta(df: DataFrame, table: str, mode: str = "overwrite"):
    """Write DataFrame to a Delta Lake table."""
    df.write.format("delta").mode(mode).saveAsTable(table)
    logger.info("Wrote %d rows to %s", df.count(), table)


def run(spark: SparkSession):
    """Main entry point: read -> transform -> quarantine -> write."""
    logger.info("=== Starting loan product ingestion ===")

    raw_df = read_legacy_source(spark, LEGACY_SOURCE_PATH)
    transformed_df = transform_loan_products(raw_df)
    good_df, bad_df = quarantine_bad_records(transformed_df)

    write_to_delta(good_df, TARGET_TABLE, mode="overwrite")
    if bad_df.count() > 0:
        write_to_delta(bad_df, QUARANTINE_TABLE, mode="overwrite")

    logger.info("=== Loan product ingestion complete ===")


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestLoanProducts").getOrCreate()
    run(spark)
