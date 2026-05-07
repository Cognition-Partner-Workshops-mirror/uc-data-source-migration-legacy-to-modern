"""
PySpark ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan product reference table and transforms all-VARCHAR columns
into properly typed Delta Lake columns per column_mappings.md.

Key transformations:
- Parse term months string to IntegerType
- Parse min/max amount strings to DecimalType
- Convert product status code to boolean (ACT -> true, INA -> false)
- Parse date strings (MM/DD/YYYY) to DateType
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    read_legacy_csv,
    read_legacy_parquet,
    parse_legacy_date,
    parse_legacy_amount,
    parse_legacy_integer,
    add_pipeline_metadata,
    log_parse_errors,
    PRODUCT_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/cdw/CDW_LN_PROD/"
TARGET_TABLE = "loan_warehouse.loan_products"
SOURCE_FORMAT = "csv"


def read_source(spark: SparkSession) -> DataFrame:
    """Read the legacy loan product data from the landing zone."""
    if SOURCE_FORMAT == "parquet":
        return read_legacy_parquet(spark, SOURCE_PATH)
    return read_legacy_csv(spark, SOURCE_PATH)


def transform(df: DataFrame) -> DataFrame:
    """
    Apply all transformations from CDW_LN_PROD to modern loan_products schema.

    Product status (ACT/INA) is converted to a boolean is_active column
    rather than a string expansion, since products are either available or not.
    """
    # --- Step 1: Rename columns from cryptic legacy names ---
    renamed = (
        df
        .withColumnRenamed("PROD_CD", "code")
        .withColumnRenamed("PROD_DESC_TXT", "name")
        .withColumnRenamed("PROD_TYP_CD", "type")
        .withColumnRenamed("PROD_RT_TYP", "rate_type")
    )

    # --- Step 2: Parse term months string to integer ---
    renamed = parse_legacy_integer(renamed, "PROD_TERM_MOS", "term_months")

    # --- Step 3: Parse min/max amount strings to decimal ---
    renamed = parse_legacy_amount(renamed, "PROD_MIN_AMT", "min_amount")
    renamed = parse_legacy_amount(renamed, "PROD_MAX_AMT", "max_amount")

    # --- Step 4: Convert status code to boolean is_active ---
    # ACT -> true, INA -> false; unknown codes default to false for safety
    status_map_expr = F.create_map(
        *[item for pair in PRODUCT_STATUS_MAP.items()
          for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )
    renamed = renamed.withColumn(
        "is_active",
        F.coalesce(
            status_map_expr[F.upper(F.trim(F.col("PROD_STAT_CD")))],
            F.lit(False)
        )
    )
    # Flag rows with unrecognized product status codes
    renamed = renamed.withColumn(
        "is_active_unmapped",
        ~F.upper(F.trim(F.col("PROD_STAT_CD"))).isin(list(PRODUCT_STATUS_MAP.keys()))
    )

    # --- Step 5: Parse effective/expiration date strings to DateType ---
    renamed = parse_legacy_date(renamed, "PROD_EFF_DT", "effective_date")
    renamed = parse_legacy_date(renamed, "PROD_EXP_DT", "expiration_date")

    # --- Step 6: Add pipeline metadata ---
    renamed = add_pipeline_metadata(renamed, "CDW_LN_PROD")

    # --- Step 7: Select final columns ---
    result = renamed.select(
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
        "_ingested_at",
        "_source_system",
    )

    return result


def load(df: DataFrame):
    """Write the transformed product data to the Delta Lake target table."""
    (
        df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )


def run(spark: SparkSession):
    """Main entry point: read -> transform -> load for loan products."""
    raw_df = read_source(spark)
    transformed_df = transform(raw_df)

    # Log parse issues before loading
    log_parse_errors(transformed_df, "loan_products", [
        "term_months_parse_error",
        "min_amount_parse_error",
        "max_amount_parse_error",
        "is_active_unmapped",
        "effective_date_parse_error",
        "expiration_date_parse_error",
    ])

    load(transformed_df)
    print(f"[loan_products] Ingestion complete. Rows written: {transformed_df.count()}")


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_LN_PROD_Ingestion").getOrCreate()
    run(spark)
