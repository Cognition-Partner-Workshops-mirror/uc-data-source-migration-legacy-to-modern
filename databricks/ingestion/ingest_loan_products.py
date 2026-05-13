"""
PySpark ingestion script: CDW_LN_PROD → loan_warehouse.loan_products

Reads legacy loan product data, applies type conversions and status-to-boolean
transformation, and writes to a Delta Lake table.

Mapping reference: data/mappings/column_mappings.md § CDW_LN_PROD → loan_products

Usage:
    spark-submit ingest_loan_products.py --source /mnt/landing/cdw_ln_prod/ --format csv
"""

import argparse
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from transformations import (
    parse_legacy_date,
    parse_legacy_amount,
    parse_legacy_integer,
    expand_product_status,
)

TARGET_TABLE = "loan_warehouse.loan_products"


def read_source(spark: SparkSession, source_path: str, fmt: str) -> DataFrame:
    """Read legacy CDW_LN_PROD data from CSV or Parquet."""
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(source_path)
    elif fmt == "parquet":
        return reader.parquet(source_path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def transform_loan_products(df: DataFrame) -> DataFrame:
    """
    Apply all transformations from legacy CDW_LN_PROD to modern loan_products schema.
    Product is a small reference table — all records are expected to be valid.
    """
    # Tag records missing the required product code
    df = df.withColumn(
        "_has_required_fields",
        F.col("PROD_CD").isNotNull() & F.col("PROD_DESC_TXT").isNotNull(),
    )

    quarantine_df = df.filter(~F.col("_has_required_fields"))
    if quarantine_df.count() > 0:
        print(
            f"WARNING: {quarantine_df.count()} product records missing required fields. "
            f"Writing to quarantine."
        )
        quarantine_df.show(truncate=False)

    valid_df = df.filter(F.col("_has_required_fields"))

    result = valid_df.select(
        F.col("PROD_CD").alias("code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        # Numeric parsing: VARCHAR → INT
        parse_legacy_integer("PROD_TERM_MOS", "term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        # Amount parsing: VARCHAR with commas → DECIMAL
        parse_legacy_amount("PROD_MIN_AMT", "min_amount"),
        parse_legacy_amount("PROD_MAX_AMT", "max_amount"),
        # Status → boolean: ACT→true, INA→false
        expand_product_status("PROD_STAT_CD", "is_active"),
        # Date parsing: MM/DD/YYYY → DATE
        parse_legacy_date("PROD_EFF_DT", "effective_date"),
        parse_legacy_date("PROD_EXP_DT", "expiration_date"),
        # Audit columns
        F.current_timestamp().alias("_ingestion_ts"),
        F.lit("CDW_LN_PROD").alias("_source_system"),
    )

    return result


def write_to_delta(df: DataFrame, mode: str = "overwrite"):
    """Write transformed loan products to Delta table (no partitioning — small table)."""
    df.write.format("delta").mode(mode).saveAsTable(TARGET_TABLE)
    print(f"Successfully wrote {df.count()} records to {TARGET_TABLE}")


def main():
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_PROD → loan_products")
    parser.add_argument("--source", required=True, help="Path to source data files")
    parser.add_argument(
        "--format", default="csv", choices=["csv", "parquet"], help="Source file format"
    )
    parser.add_argument(
        "--mode", default="overwrite", choices=["overwrite", "append"], help="Write mode"
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_LN_PROD_Ingestion").getOrCreate()

    print(f"Reading source data from {args.source} (format={args.format})")
    source_df = read_source(spark, args.source, args.format)
    source_count = source_df.count()
    print(f"Source record count: {source_count}")

    print("Applying transformations...")
    transformed_df = transform_loan_products(source_df)
    target_count = transformed_df.count()
    print(f"Transformed record count: {target_count}")

    if source_count != target_count:
        print(
            f"WARNING: Row count mismatch — source={source_count}, target={target_count}."
        )

    print(f"Writing to Delta table {TARGET_TABLE} (mode={args.mode})")
    write_to_delta(transformed_df, args.mode)

    spark.stop()


if __name__ == "__main__":
    main()
