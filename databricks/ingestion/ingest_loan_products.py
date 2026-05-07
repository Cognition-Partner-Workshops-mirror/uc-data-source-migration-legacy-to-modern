"""
PySpark ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads legacy loan product data, applies transformations, writes to Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DecimalType, IntegerType
)

LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_LN_PROD/"
TARGET_TABLE = "loan_warehouse.loan_products"
DATE_FORMAT = "MM/dd/yyyy"

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


def parse_legacy_amount(col_name: str):
    """Strip non-numeric chars and cast to DecimalType for amount fields."""
    cleaned = F.regexp_replace(F.col(col_name), r"[^0-9.\-]", "")
    return F.when(
        (F.col(col_name).isNull()) | (F.trim(F.col(col_name)) == ""),
        F.lit(None).cast(DecimalType(12, 2))
    ).otherwise(cleaned.cast(DecimalType(12, 2)))


def read_legacy_products(spark: SparkSession) -> DataFrame:
    return (
        spark.read
        .option("header", "true")
        .schema(LEGACY_SCHEMA)
        .csv(LEGACY_SOURCE_PATH)
    )


def transform_products(df: DataFrame) -> DataFrame:
    """Map legacy product columns to modern schema with proper types."""
    return df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        F.col("PROD_TERM_MOS").cast(IntegerType()).alias("term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_legacy_amount("PROD_MIN_AMT").alias("min_amount"),
        parse_legacy_amount("PROD_MAX_AMT").alias("max_amount"),
        F.when(F.col("PROD_STAT_CD") == "ACT", F.lit(True))
         .otherwise(F.lit(False)).alias("is_active"),
        F.to_date(F.col("PROD_EFF_DT"), DATE_FORMAT).alias("effective_date"),
        F.to_date(F.col("PROD_EXP_DT"), DATE_FORMAT).alias("expiration_date"),
    )


def run(spark: SparkSession):
    print("=== Loan Product Ingestion: START ===")

    raw_df = read_legacy_products(spark)
    source_count = raw_df.count()
    print(f"Source record count: {source_count}")

    transformed_df = transform_products(raw_df)

    # Drop records missing required fields (product code or description)
    good_df = transformed_df.filter(
        F.col("code").isNotNull() & F.col("name").isNotNull()
    )
    good_count = good_df.count()
    dropped = source_count - good_count
    if dropped > 0:
        print(f"WARNING: {dropped} records dropped due to missing code or name")

    (
        good_df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )
    print(f"Wrote {good_count} records to {TARGET_TABLE}")
    print("=== Loan Product Ingestion: COMPLETE ===")
    return source_count, good_count, dropped


if __name__ == "__main__":
    spark = SparkSession.builder.getOrCreate()
    run(spark)
