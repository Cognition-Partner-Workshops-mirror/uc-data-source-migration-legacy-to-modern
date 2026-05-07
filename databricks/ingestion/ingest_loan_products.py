"""
Ingest legacy CDW_LN_PROD into Delta Lake loan_products table.

Source : CSV/Parquet export of CDW_LN_PROD
Target : loan_warehouse.loan_products (Delta Lake)

Transformations:
  - PROD_TERM_MOS         : VARCHAR    -> INT
  - PROD_MIN_AMT/MAX_AMT  : "50,000"   -> DECIMAL(12,2)
  - PROD_STAT_CD          : ACT/INA    -> BOOLEAN is_active
  - PROD_EFF_DT/EXP_DT   : MM/DD/YYYY -> DATE
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from .transforms import (
    parse_date,
    parse_amount,
    parse_int,
    parse_boolean_status,
    add_ingestion_timestamp,
    log_malformed_rows,
)

REQUIRED_COLS = ["code", "name", "type", "term_months", "rate_type"]


def read_source(spark: SparkSession, source_path: str, source_format: str = "csv") -> DataFrame:
    reader = spark.read.format(source_format)
    if source_format == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(source_path)


def transform(df: DataFrame) -> DataFrame:
    return (
        df
        .select(
            F.trim(F.col("PROD_CD")).alias("code"),
            F.trim(F.col("PROD_DESC_TXT")).alias("name"),
            F.trim(F.col("PROD_TYP_CD")).alias("type"),
            parse_int("PROD_TERM_MOS").alias("term_months"),
            F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
            parse_amount("PROD_MIN_AMT").alias("min_amount"),
            parse_amount("PROD_MAX_AMT").alias("max_amount"),
            parse_boolean_status("PROD_STAT_CD").alias("is_active"),
            parse_date("PROD_EFF_DT").alias("effective_date"),
            parse_date("PROD_EXP_DT").alias("expiration_date"),
        )
    )


def run(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.loan_products",
    error_path: str = "dbfs:/mnt/quarantine/loan_products/",
    source_format: str = "csv",
    write_mode: str = "append",
) -> dict:
    raw_df = read_source(spark, source_path, source_format)
    source_count = raw_df.count()
    print(f"[loan_products] Source rows read: {source_count}")

    transformed_df = transform(raw_df)
    transformed_df = add_ingestion_timestamp(transformed_df)

    valid_df, quarantine_count = log_malformed_rows(
        transformed_df, REQUIRED_COLS, "CDW_LN_PROD", error_path
    )
    print(f"[loan_products] Quarantined rows: {quarantine_count}")

    valid_count = valid_df.count()
    (
        valid_df
        .write
        .format("delta")
        .mode(write_mode)
        .option("mergeSchema", "true")
        .saveAsTable(target_table)
    )
    print(f"[loan_products] Rows written to {target_table}: {valid_count}")

    return {
        "table": target_table,
        "source_count": source_count,
        "valid_count": valid_count,
        "quarantine_count": quarantine_count,
    }
