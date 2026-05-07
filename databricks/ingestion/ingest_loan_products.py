"""
Ingestion script: CDW_LN_PROD → loan_warehouse.loan_products

Reads legacy loan product catalog from CSV/Parquet source, transforms
VARCHAR columns to proper types, and writes to Delta Lake.

Usage (Databricks notebook):
    %run ./common
    %run ./ingest_loan_products
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

from common import (
    PRODUCT_STATUS_MAP,
    expand_status_to_bool,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_int,
    tag_ingestion_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "dbfs:/mnt/legacy-extracts/cdw_ln_prod/"
TARGET_TABLE = "loan_warehouse.loan_products"
SOURCE_FORMAT = "csv"

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


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def extract(spark: SparkSession) -> DataFrame:
    reader = spark.read.format(SOURCE_FORMAT).schema(LEGACY_SCHEMA)
    if SOURCE_FORMAT == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(SOURCE_PATH)
    print(f"[ingest_loan_products] Extracted {df.count()} rows from {SOURCE_PATH}")
    return df


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame) -> DataFrame:
    transformed = df.select(
        F.trim(F.col("PROD_CD")).alias("code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.upper(F.trim(F.col("PROD_TYP_CD"))).alias("type"),
        parse_legacy_int("PROD_TERM_MOS").alias("term_months"),
        F.upper(F.trim(F.col("PROD_RT_TYP"))).alias("rate_type"),
        parse_legacy_amount("PROD_MIN_AMT").alias("min_amount"),
        parse_legacy_amount("PROD_MAX_AMT").alias("max_amount"),
        expand_status_to_bool("PROD_STAT_CD", PRODUCT_STATUS_MAP).alias("is_active"),
        parse_legacy_date("PROD_EFF_DT").alias("effective_date"),
        parse_legacy_date("PROD_EXP_DT").alias("expiration_date"),
    )

    transformed = tag_ingestion_metadata(transformed, "CDW_LN_PROD")

    # Quarantine rows with missing product code
    quarantined = transformed.withColumn(
        "_quarantine",
        F.col("code").isNull() | (F.col("code") == ""),
    )

    quarantine_count = quarantined.filter(F.col("_quarantine")).count()
    if quarantine_count > 0:
        print(f"[ingest_loan_products] WARNING: {quarantine_count} rows with missing product code")

    clean = quarantined.filter(~F.col("_quarantine")).drop("_quarantine")
    print(f"[ingest_loan_products] Transformed {clean.count()} clean rows")
    return clean


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load(df: DataFrame):
    df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)
    print(f"[ingest_loan_products] Loaded data into {TARGET_TABLE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession):
    raw = extract(spark)
    clean = transform(raw)
    load(clean)
    print("[ingest_loan_products] Pipeline complete")


if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestLoanProducts").getOrCreate()
    run(spark)
