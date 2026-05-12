"""
Ingestion script: CDW_LN_PROD → loan_warehouse.loan_products

Reads the legacy loan products table (simulated as CSV/Parquet),
applies all transformations from column_mappings.md, and writes
to the modern Delta Lake loan_products table.

Execution order: Run SECOND — loan_products is referenced by loan_accounts.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from transforms import (
    parse_legacy_date,
    parse_legacy_integer,
    parse_legacy_amount,
    expand_product_status_to_boolean,
)

# =============================================================================
# Configuration
# =============================================================================
LEGACY_SOURCE_PATH = "/mnt/legacy-data/CDW_LN_PROD"
LEGACY_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_PATH = "/mnt/migration/quarantine/loan_products"


def read_legacy_products(spark: SparkSession) -> DataFrame:
    """Read legacy loan product data. All columns as STRING."""
    return (
        spark.read
        .format(LEGACY_SOURCE_FORMAT)
        .option("header", "true")
        .option("inferSchema", "false")
        .load(LEGACY_SOURCE_PATH)
    )


def transform_products(df: DataFrame) -> DataFrame:
    """
    Apply all transformations documented in column_mappings.md § CDW_LN_PROD → loan_products.
    """
    return df.select(
        # Direct copy
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),

        # Numeric parsing
        parse_legacy_integer(F.col("PROD_TERM_MOS")).alias("term_months"),

        # Direct copy
        F.col("PROD_RT_TYP").alias("rate_type"),

        # Amount parsing: remove commas, cast to decimal
        parse_legacy_amount(F.col("PROD_MIN_AMT")).alias("min_amount"),
        parse_legacy_amount(F.col("PROD_MAX_AMT")).alias("max_amount"),

        # Status → boolean: ACT→true, INA→false
        expand_product_status_to_boolean(F.col("PROD_STAT_CD")).alias("is_active"),

        # Date parsing
        parse_legacy_date(F.col("PROD_EFF_DT")).alias("effective_date"),
        parse_legacy_date(F.col("PROD_EXP_DT")).alias("expiration_date"),
    )


def quarantine_invalid_records(df: DataFrame) -> tuple:
    """Separate valid from invalid records. Required: code, name, type, term_months, rate_type."""
    required_fields = ["code", "name", "type", "term_months", "rate_type"]

    null_condition = F.lit(False)
    for field in required_fields:
        null_condition = null_condition | F.col(field).isNull()

    valid_df = df.filter(~null_condition)
    quarantine_df = df.filter(null_condition)
    return valid_df, quarantine_df


def run_ingestion():
    """Main ingestion entry point."""
    spark = SparkSession.builder.appName("Ingest CDW_LN_PROD → loan_products").getOrCreate()

    print("=" * 60)
    print("INGESTION: CDW_LN_PROD → loan_warehouse.loan_products")
    print("=" * 60)

    legacy_df = read_legacy_products(spark)
    source_count = legacy_df.count()
    print(f"Source records read: {source_count}")

    transformed_df = transform_products(legacy_df)
    valid_df, quarantine_df = quarantine_invalid_records(transformed_df)
    quarantine_count = quarantine_df.count()
    valid_count = valid_df.count()

    if quarantine_count > 0:
        print(f"WARNING: {quarantine_count} record(s) quarantined")
        quarantine_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)
    else:
        print("All records passed validation")

    valid_df.write.mode("overwrite").format("delta").saveAsTable(TARGET_TABLE)
    print(f"Target records written: {valid_count}")
    print(f"Reconciliation: {source_count} → {valid_count} (+{quarantine_count} quarantined)")


if __name__ == "__main__":
    run_ingestion()
