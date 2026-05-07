"""
Ingest legacy CDW_LN_PROD → modern loan_products Delta Lake table.

Source : CSV/Parquet export of CDW_LN_PROD
Target : loan_warehouse.loan_products (Delta Lake)

Transformations:
  - Parse amount strings (with commas) → DecimalType
  - Parse term months string → IntegerType
  - Parse date strings (MM/DD/YYYY) → DateType
  - Convert status code to boolean (ACT → true, INA → false)
"""

import logging
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType,
)

from transforms import (
    parse_legacy_date,
    parse_legacy_amount,
    parse_legacy_int,
    PRODUCT_STATUS_MAP,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_loan_products")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

LEGACY_SCHEMA = StructType([
    StructField("PROD_CD", StringType(), False),
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

SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_ln_prod/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_PATH = "dbfs:/mnt/quarantine/loan_products/"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH, fmt: str = SOURCE_FORMAT) -> DataFrame:
    reader = spark.read.schema(LEGACY_SCHEMA)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.format(fmt).load(path)


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    # Build boolean mapping expression
    status_map = F.create_map(
        [F.lit(x) for kv in PRODUCT_STATUS_MAP.items() for x in (kv[0], kv[1])]
    )

    transformed = df.select(
        F.trim(F.col("PROD_CD")).alias("code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.trim(F.col("PROD_TYP_CD")).alias("type"),
        parse_legacy_int("PROD_TERM_MOS").alias("term_months"),
        F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
        parse_legacy_amount("PROD_MIN_AMT", 12, 2).alias("min_amount"),
        parse_legacy_amount("PROD_MAX_AMT", 12, 2).alias("max_amount"),
        F.coalesce(status_map[F.trim(F.col("PROD_STAT_CD"))], F.lit(False)).alias("is_active"),
        parse_legacy_date("PROD_EFF_DT").alias("effective_date"),
        parse_legacy_date("PROD_EXP_DT").alias("expiration_date"),
        F.current_timestamp().alias("_migration_ts"),
        F.lit("CDW_LN_PROD").alias("_source_system"),
    )

    valid_condition = (
        F.col("code").isNotNull()
        & F.col("name").isNotNull()
        & F.col("type").isNotNull()
        & F.col("term_months").isNotNull()
        & F.col("rate_type").isNotNull()
    )

    good_df = transformed.filter(valid_condition)
    quarantine_df = transformed.filter(~valid_condition)

    return good_df, quarantine_df


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    good_count = good_df.count()
    quarantine_count = quarantine_df.count()

    logger.info("Loan products — good: %d, quarantined: %d", good_count, quarantine_count)

    if quarantine_count > 0:
        logger.warning("Writing %d quarantined loan product records to %s", quarantine_count, QUARANTINE_PATH)
        quarantine_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)

    good_df.write.mode("overwrite").format("delta").saveAsTable(TARGET_TABLE)

    logger.info("Loan product ingestion complete → %s", TARGET_TABLE)
    return {"good": good_count, "quarantined": quarantine_count}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession) -> dict:
    logger.info("Starting loan product ingestion from %s", SOURCE_PATH)
    raw_df = read_source(spark)
    source_count = raw_df.count()
    logger.info("Source record count: %d", source_count)

    good_df, quarantine_df = transform(raw_df)
    result = write_target(good_df, quarantine_df)
    result["source_count"] = source_count
    return result


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest_CDW_LN_PROD").getOrCreate()
    run(spark)
