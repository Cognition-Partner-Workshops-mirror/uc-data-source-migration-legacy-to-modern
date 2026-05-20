"""
ingest_loan_products.py — PySpark ingestion script for the loan_products dimension table.

Reads from the legacy CDW_LN_PROD source (simulated as CSV/Parquet), applies
all required transformations per column_mappings.md, and writes to the Delta Lake
loan_management.loan_products table.

Source: CDW_LN_PROD (legacy all-VARCHAR loan products)
Target: loan_management.loan_products (typed Delta Lake table)

Transformations:
  - PROD_TERM_MOS (VARCHAR) → term_months (INT)
  - PROD_MIN_AMT / PROD_MAX_AMT ("50,000") → min_amount / max_amount (DECIMAL)
  - PROD_STAT_CD (ACT/INA) → is_active (BOOLEAN)
  - PROD_EFF_DT / PROD_EXP_DT (MM/DD/YYYY) → effective_date / expiration_date (DATE)
"""

from pyspark.sql import SparkSession, functions as F

from common_transforms import (
    parse_date_col,
    parse_amount_col,
    parse_int_col,
    expand_status_to_bool,
    add_parse_error_flags,
    log_transformation_summary,
    PRODUCT_STATUS_MAP,
)

# =============================================================================
# Configuration — update these paths for your Databricks environment
# =============================================================================
SOURCE_PATH = "/mnt/legacy-data/cdw_ln_prod/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_management.loan_products"


def read_source(spark, path=SOURCE_PATH, fmt=SOURCE_FORMAT):
    """
    Read the legacy CDW_LN_PROD source data.
    All columns are read as strings to match the legacy all-VARCHAR schema.
    """
    if fmt == "csv":
        return (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .csv(path)
        )
    elif fmt == "parquet":
        return spark.read.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform_loan_products(df):
    """
    Apply all transformations to convert legacy CDW_LN_PROD columns
    to the modern loan_products schema per column_mappings.md.
    """
    # Rename direct-copy columns
    transformed = (
        df
        .withColumnRenamed("PROD_CD", "code")
        .withColumnRenamed("PROD_DESC_TXT", "name")
        .withColumnRenamed("PROD_TYP_CD", "type")
        .withColumnRenamed("PROD_RT_TYP", "rate_type")
    )

    # Parse term months: VARCHAR → INT
    transformed = parse_int_col(transformed, "PROD_TERM_MOS", "term_months")

    # Parse min/max amounts: comma-formatted strings → DECIMAL(12,2)
    transformed = parse_amount_col(transformed, "PROD_MIN_AMT", "min_amount")
    transformed = parse_amount_col(transformed, "PROD_MAX_AMT", "max_amount")

    # Expand product status to boolean: ACT → true, INA → false
    transformed = expand_status_to_bool(
        transformed, "PROD_STAT_CD", "is_active", PRODUCT_STATUS_MAP
    )

    # Parse effective/expiration dates: MM/DD/YYYY → DATE
    transformed = parse_date_col(transformed, "PROD_EFF_DT", "effective_date")
    transformed = parse_date_col(transformed, "PROD_EXP_DT", "expiration_date")

    # Add parse error flags for data quality monitoring
    transformed = add_parse_error_flags(
        transformed,
        date_cols=[
            ("PROD_EFF_DT", "effective_date"),
            ("PROD_EXP_DT", "expiration_date"),
        ],
        amount_cols=[
            ("PROD_MIN_AMT", "min_amount"),
            ("PROD_MAX_AMT", "max_amount"),
        ],
    )

    # Select only modern schema columns
    result = transformed.select(
        "code",
        "name",
        "type",
        "term_months",
        "rate_type",
        "min_amount",
        "max_amount",
        "is_active",
        "effective_date",
        "expiration_date",
        "_parse_errors",
    )

    return result


def write_target(df, table=TARGET_TABLE, mode="overwrite"):
    """
    Write the transformed loan product data to the Delta Lake target table.
    """
    (
        df
        .drop("_parse_errors")
        .write
        .format("delta")
        .mode(mode)
        .saveAsTable(table)
    )


def run(spark=None):
    """
    Main entry point: read legacy loan product data, transform, validate, and write.
    Returns a summary dict with row counts for reconciliation.
    """
    if spark is None:
        spark = SparkSession.builder.appName("IngestLoanProducts").getOrCreate()

    print("=" * 60)
    print("Starting loan product ingestion from CDW_LN_PROD")
    print("=" * 60)

    # Step 1: Read legacy source
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"Source rows read: {source_count}")

    # Step 2: Transform to modern schema
    transformed_df = transform_loan_products(source_df)

    # Step 3: Log transformation summary
    total, errors = log_transformation_summary(transformed_df, "loan_products")

    # Step 4: Write to Delta Lake target
    write_target(transformed_df)
    print(f"Successfully wrote {total} rows to {TARGET_TABLE}")

    return {"source_count": source_count, "target_count": total, "error_count": errors}


if __name__ == "__main__":
    run()
