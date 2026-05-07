"""
PySpark Ingestion Script: CDW_LN_PROD → loan_warehouse.loan_products

Reads from legacy loan product source and transforms into
the modern normalized loan_products table.

Anomalies handled:
  - ANO-001: Numeric amounts as strings with commas
  - ANO-002: Dates in MM/DD/YYYY string format
  - ANO-004: Status code expansion (ACT→true, INA→false)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DecimalType, IntegerType
)
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/legacy-cdw/CDW_LN_PROD"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"
DQ_LOG_TABLE = "loan_warehouse.data_quality_log"
RUN_ID = f"product_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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


def read_source(spark: SparkSession) -> DataFrame:
    if SOURCE_FORMAT == "csv":
        return (
            spark.read.schema(LEGACY_SCHEMA)
            .option("header", "true")
            .csv(SOURCE_PATH)
        )
    return spark.read.parquet(SOURCE_PATH)


def parse_legacy_date(col_name: str, alias: str) -> F.Column:
    return F.coalesce(
        F.to_date(F.col(col_name), "MM/dd/yyyy"),
        F.to_date(F.col(col_name), "yyyy-MM-dd"),
    ).alias(alias)


def parse_legacy_amount(col_name: str, alias: str) -> F.Column:
    cleaned = F.regexp_replace(F.col(col_name), r"[$,\s]", "")
    return cleaned.cast(DecimalType(12, 2)).alias(alias)


def transform(df: DataFrame) -> DataFrame:
    return df.select(
        F.trim(F.col("PROD_CD")).alias("code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.trim(F.col("PROD_TYP_CD")).alias("type"),
        F.col("PROD_TERM_MOS").cast(IntegerType()).alias("term_months"),
        F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
        parse_legacy_amount("PROD_MIN_AMT", "min_amount"),
        parse_legacy_amount("PROD_MAX_AMT", "max_amount"),
        F.when(
            F.upper(F.trim(F.col("PROD_STAT_CD"))) == "ACT", F.lit(True)
        ).otherwise(F.lit(False)).alias("is_active"),
        parse_legacy_date("PROD_EFF_DT", "effective_date"),
        parse_legacy_date("PROD_EXP_DT", "expiration_date"),
        F.current_timestamp().alias("_ingestion_ts"),
        F.lit("CDW").alias("_source_system"),
    )


def detect_anomalies(source_df: DataFrame, spark: SparkSession) -> DataFrame:
    anomalies = []

    # Null required fields
    for col_name in ["PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD"]:
        null_records = source_df.filter(
            F.col(col_name).isNull() | (F.trim(F.col(col_name)) == "")
        ).select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_LN_PROD").alias("source_table"),
            F.coalesce(F.col("PROD_CD"), F.lit("UNKNOWN")).alias("source_record_id"),
            F.lit(col_name).alias("column_name"),
            F.lit("NULL_REQUIRED").alias("anomaly_type"),
            F.lit("CRITICAL").alias("severity"),
            F.lit(f"Required field {col_name} is null/blank").alias("description"),
            F.col(col_name).alias("original_value"),
            F.lit(None).cast(StringType()).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
        anomalies.append(null_records)

    # Unparseable amounts
    for col_name in ["PROD_MIN_AMT", "PROD_MAX_AMT"]:
        cleaned = F.regexp_replace(F.col(col_name), r"[$,\s]", "")
        bad = source_df.filter(
            F.col(col_name).isNotNull() & cleaned.cast(DecimalType(12, 2)).isNull()
        ).select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_LN_PROD").alias("source_table"),
            F.col("PROD_CD").alias("source_record_id"),
            F.lit(col_name).alias("column_name"),
            F.lit("PARSE_FAILURE").alias("anomaly_type"),
            F.lit("CRITICAL").alias("severity"),
            F.lit(f"{col_name} could not be parsed to decimal").alias("description"),
            F.col(col_name).alias("original_value"),
            F.lit(None).cast(StringType()).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
        anomalies.append(bad)

    if anomalies:
        from functools import reduce
        return reduce(DataFrame.unionByName, anomalies)
    return spark.createDataFrame([], schema=StructType([]))


def run(spark: SparkSession) -> dict:
    print(f"[{RUN_ID}] Starting loan product ingestion...")
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"[{RUN_ID}] Source rows: {source_count}")

    anomaly_df = detect_anomalies(source_df, spark)
    anomaly_count = anomaly_df.count()
    print(f"[{RUN_ID}] Anomalies detected: {anomaly_count}")
    if anomaly_count > 0:
        anomaly_df.write.mode("append").saveAsTable(DQ_LOG_TABLE)

    transformed_df = transform(source_df)
    transformed_df.createOrReplaceTempView("products_staging")
    spark.sql(f"""
        MERGE INTO {TARGET_TABLE} AS target
        USING products_staging AS source
        ON target.code = source.code
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[{RUN_ID}] Target rows: {target_count}")
    return {
        "run_id": RUN_ID,
        "source_count": source_count,
        "target_count": target_count,
        "anomaly_count": anomaly_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW Product Ingestion").getOrCreate()
    result = run(spark)
    print(f"Ingestion complete: {result}")
