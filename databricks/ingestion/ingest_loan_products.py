"""
Ingestion script: CDW_LN_PROD → loan_products (Delta Lake)

Reads legacy loan product data from CSV/Parquet source, applies transformations
per column_mappings.md, and writes to the modern loan_products Delta table.
"""

from pyspark.sql.functions import col, monotonically_increasing_id

from common import (
    get_spark,
    logger,
    parse_date_column,
    parse_amount_column,
    parse_integer_column,
    expand_status_to_boolean,
    log_record_counts,
    log_null_counts,
    write_delta,
    PRODUCT_STATUS_MAP,
)


def read_legacy_loan_products(spark, source_path: str):
    """Read legacy CDW_LN_PROD data from CSV or Parquet."""
    if source_path.endswith(".parquet"):
        df = spark.read.parquet(source_path)
    else:
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .csv(source_path)
        )
    logger.info(f"Read source file: {source_path}")
    return df


def transform_loan_products(df):
    """Apply transformations for loan products."""
    source_count = log_record_counts(df, "loan_products", "source")

    log_null_counts(df, "loan_products", ["PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD"])

    result = df.select(
        col("PROD_CD").alias("code"),
        col("PROD_DESC_TXT").alias("name"),
        col("PROD_TYP_CD").alias("type"),
        col("PROD_TERM_MOS"),
        col("PROD_RT_TYP").alias("rate_type"),
        col("PROD_MIN_AMT"),
        col("PROD_MAX_AMT"),
        col("PROD_STAT_CD"),
        col("PROD_EFF_DT"),
        col("PROD_EXP_DT"),
    )

    # Parse term months to integer
    result = parse_integer_column(result, "PROD_TERM_MOS", "term_months")
    result = result.drop("PROD_TERM_MOS")

    # Parse amount columns
    result = parse_amount_column(result, "PROD_MIN_AMT", "min_amount")
    result = result.drop("PROD_MIN_AMT")
    result = parse_amount_column(result, "PROD_MAX_AMT", "max_amount")
    result = result.drop("PROD_MAX_AMT")

    # Convert status to boolean
    result = expand_status_to_boolean(result, "PROD_STAT_CD", "is_active", PRODUCT_STATUS_MAP)
    result = result.drop("PROD_STAT_CD")

    # Parse dates
    result = parse_date_column(result, "PROD_EFF_DT", "effective_date")
    result = result.drop("PROD_EFF_DT")
    result = parse_date_column(result, "PROD_EXP_DT", "expiration_date")
    result = result.drop("PROD_EXP_DT")

    # Add surrogate key
    result = result.withColumn("id", monotonically_increasing_id())

    target_count = log_record_counts(result, "loan_products", "transformed")

    if source_count != target_count:
        logger.error(
            f"[loan_products] Record count mismatch! Source={source_count}, Target={target_count}"
        )

    return result


def run(source_path: str):
    """Main entry point for loan product ingestion."""
    spark = get_spark()
    logger.info("=== Starting Loan Product Ingestion ===")

    raw_df = read_legacy_loan_products(spark, source_path)
    transformed_df = transform_loan_products(raw_df)
    write_delta(transformed_df, "loan_products")

    logger.info("=== Loan Product Ingestion Complete ===")
    return transformed_df


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: spark-submit ingest_loan_products.py <source_path>")
        sys.exit(1)
    run(sys.argv[1])
