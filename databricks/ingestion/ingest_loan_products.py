"""
PySpark Ingestion Script: Loan Products
Source: CDW_LN_PROD (legacy CSV/Parquet extract)
Target: loan_warehouse.loan_products (Delta Lake)

Transformations applied:
  - PROD_TERM_MOS (string) -> term_months (IntegerType)
  - PROD_MIN_AMT / PROD_MAX_AMT (comma-formatted string) -> DecimalType
  - PROD_STAT_CD (ACT/INA) -> is_active (BooleanType)
  - PROD_EFF_DT / PROD_EXP_DT (MM/DD/YYYY) -> DateType
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from utils import (
    PRODUCT_STATUS_MAP,
    col_expand_boolean,
    col_parse_amount,
    col_parse_date,
    col_parse_int,
    log_row_counts,
    quarantine_malformed_rows,
    tag_migration_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/legacy-extracts/CDW_LN_PROD/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_products"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "quote": '"',
    "escape": '"',
}


def read_source(spark: SparkSession):
    """Read the legacy CDW_LN_PROD extract."""
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for key, val in CSV_OPTIONS.items():
            reader = reader.option(key, val)
    return reader.load(SOURCE_PATH)


def transform(df):
    """Apply all column mappings and type conversions."""
    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        col_parse_int("PROD_TERM_MOS", "term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        col_parse_amount("PROD_MIN_AMT", "min_amount"),
        col_parse_amount("PROD_MAX_AMT", "max_amount"),
        col_expand_boolean("PROD_STAT_CD", PRODUCT_STATUS_MAP, "is_active"),
        col_parse_date("PROD_EFF_DT", "effective_date"),
        col_parse_date("PROD_EXP_DT", "expiration_date"),
    )
    return transformed


def run(spark: SparkSession):
    """Execute the full loan product ingestion pipeline."""
    print(f"[MIGRATION] Starting loan product ingestion from {SOURCE_PATH}")

    # Read
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"[MIGRATION] Read {source_count} rows from CDW_LN_PROD")

    # Transform
    transformed_df = transform(source_df)

    # Add migration metadata
    transformed_df = tag_migration_metadata(transformed_df, "CDW_LN_PROD")

    # Quarantine rows with NULL in required fields
    required_cols = ["code", "name", "type", "term_months", "rate_type"]
    valid_df, quarantine_df = quarantine_malformed_rows(
        transformed_df, required_cols, "CDW_LN_PROD", spark
    )

    # Write quarantined rows
    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        print(f"[MIGRATION] WARNING: {quarantine_count} rows quarantined for loan_products")
        quarantine_df.write.format("delta").mode("append").saveAsTable(QUARANTINE_TABLE)

    # Deduplicate on product code
    from pyspark.sql.window import Window
    dedup_window = Window.partitionBy("code").orderBy(F.lit(1))
    valid_df = (
        valid_df
        .withColumn("_row_num", F.row_number().over(dedup_window))
        .filter(F.col("_row_num") == 1)
        .drop("_row_num")
    )

    # Write to Delta Lake target
    target_count = valid_df.count()
    valid_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    # Reconciliation
    stats = log_row_counts(spark, source_count, target_count, quarantine_count, "loan_products")
    print(f"[MIGRATION] Loan product ingestion complete")
    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_LoanProducts").getOrCreate()
    try:
        run(spark)
    finally:
        spark.stop()
