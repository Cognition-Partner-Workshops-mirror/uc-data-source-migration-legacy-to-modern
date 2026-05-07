"""
Ingest legacy CDW_LN_PROD data into modern Delta Lake loan_products table.

Source: CSV/Parquet export of CDW_LN_PROD
Target: loan_warehouse.loan_products (Delta Lake)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transformations import (
    parse_date_col,
    parse_amount_col,
    parse_int_col,
    expand_status_to_bool,
    flag_parse_failures,
    quarantine_bad_records,
    PRODUCT_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy-exports/CDW_LN_PROD/"
LEGACY_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_migration.loan_warehouse.loan_products"
QUARANTINE_PATH = "dbfs:/mnt/migration-quarantine/loan_products/"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "nullValue": "",
    "emptyValue": "",
}


def read_legacy_products(spark: SparkSession) -> DataFrame:
    """Read legacy loan product data."""
    reader = spark.read.format(LEGACY_SOURCE_FORMAT)
    if LEGACY_SOURCE_FORMAT == "csv":
        reader = reader.options(**CSV_OPTIONS)
    return reader.load(LEGACY_SOURCE_PATH)


def transform_products(df: DataFrame) -> DataFrame:
    """Transform CDW_LN_PROD to modern loan_products schema."""

    # --- Date columns ---
    df = parse_date_col(df, "PROD_EFF_DT", "effective_date")
    df = parse_date_col(df, "PROD_EXP_DT", "expiration_date")

    # --- Numeric columns ---
    df = parse_int_col(df, "PROD_TERM_MOS", "term_months")
    df = parse_amount_col(df, "PROD_MIN_AMT", "min_amount")
    df = parse_amount_col(df, "PROD_MAX_AMT", "max_amount")

    # --- Status -> Boolean: ACT -> true, INA -> false ---
    df = expand_status_to_bool(df, "PROD_STAT_CD", "is_active", PRODUCT_STATUS_MAP)

    # --- Parse failure flags ---
    df = flag_parse_failures(df, "PROD_EFF_DT", "effective_date", "_bad_eff_dt")
    df = flag_parse_failures(df, "PROD_MIN_AMT", "min_amount", "_bad_min_amt")
    df = flag_parse_failures(df, "PROD_TERM_MOS", "term_months", "_bad_term")

    # --- Direct-copy renames ---
    df = (
        df
        .withColumn("code", F.col("PROD_CD"))
        .withColumn("name", F.col("PROD_DESC_TXT"))
        .withColumn("type", F.col("PROD_TYP_CD"))
        .withColumn("rate_type", F.col("PROD_RT_TYP"))
    )

    # --- Lineage ---
    df = (
        df
        .withColumn("_migration_source", F.lit("CDW_LN_PROD"))
        .withColumn("_migrated_at", F.current_timestamp())
    )

    return df


def run_product_ingestion(spark: SparkSession) -> dict:
    """Execute loan product ingestion pipeline."""
    print("=" * 60)
    print("LOAN PRODUCT INGESTION: CDW_LN_PROD -> loan_products")
    print("=" * 60)

    raw_df = read_legacy_products(spark)
    source_count = raw_df.count()
    print(f"Source records read: {source_count}")

    transformed_df = transform_products(raw_df)

    good_df, bad_df = quarantine_bad_records(
        transformed_df, ["_bad_eff_dt", "_bad_min_amt", "_bad_term"]
    )
    bad_count = bad_df.count()
    if bad_count > 0:
        print(f"WARNING: {bad_count} records quarantined")
        bad_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)
    else:
        print("No records quarantined")

    final_columns = [
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "is_active",
        "effective_date", "expiration_date",
        "_migration_source", "_migrated_at",
    ]
    output_df = good_df.select(*final_columns)

    (
        output_df
        .write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    target_count = spark.table(TARGET_TABLE).count()
    print(f"Target records written: {target_count}")
    print("Loan product ingestion complete.")

    return {
        "source_count": source_count,
        "target_count": target_count,
        "quarantined_count": bad_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_Products").getOrCreate()
    stats = run_product_ingestion(spark)
    print(f"\nFinal stats: {stats}")
