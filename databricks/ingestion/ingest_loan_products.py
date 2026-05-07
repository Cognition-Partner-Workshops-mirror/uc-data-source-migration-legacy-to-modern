"""
Ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan products extract (CSV or Parquet), applies column
renaming, type conversions, and status-to-boolean mapping, then writes to
the Delta Lake loan_products table.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PRODUCT_STATUS_MAP,
    expand_codes_to_bool,
    parse_amount,
    parse_int,
    parse_legacy_date,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "/mnt/landing/cdw_ln_prod/"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_PATH = "/mnt/quarantine/cdw_ln_prod/"


def read_source(spark: SparkSession, path: str) -> DataFrame:
    """Read legacy loan products extract."""
    try:
        return spark.read.parquet(path)
    except Exception:
        return spark.read.option("header", "true").option("inferSchema", "false").csv(path)


def transform_loan_products(raw: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Apply all column mappings and type conversions."""
    transformed = raw.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_int("PROD_TERM_MOS", "term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount("PROD_MIN_AMT", "min_amount"),
        parse_amount("PROD_MAX_AMT", "max_amount"),
        expand_codes_to_bool("PROD_STAT_CD", PRODUCT_STATUS_MAP, "is_active"),
        parse_legacy_date("PROD_EFF_DT", "effective_date"),
        parse_legacy_date("PROD_EXP_DT", "expiration_date"),
    )

    transformed = transformed.withColumn(
        "_has_error",
        (
            F.col("code").isNull()
            | F.col("name").isNull()
            | F.col("type").isNull()
            | F.col("term_months").isNull()
            | F.col("rate_type").isNull()
        ),
    )

    good_df = transformed.filter(~F.col("_has_error")).drop("_has_error")
    quarantine_df = transformed.filter(F.col("_has_error")).drop("_has_error")

    return good_df, quarantine_df


def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    """Write results to Delta Lake and quarantine bad records."""
    source_count = good_df.count() + quarantine_df.count()

    good_df = good_df.withColumn("_ingestion_ts", F.current_timestamp())

    good_df.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    target_count = good_df.count()
    quarantine_count = quarantine_df.count()

    if quarantine_count > 0:
        quarantine_df.write.format("delta").mode("append").save(QUARANTINE_PATH)
        print(
            f"WARNING: {quarantine_count} loan product records quarantined to {QUARANTINE_PATH}"
        )

    return {
        "table": "loan_products",
        "source_count": source_count,
        "target_count": target_count,
        "quarantine_count": quarantine_count,
    }


def run(spark: SparkSession | None = None) -> dict:
    """Main entry point."""
    if spark is None:
        spark = SparkSession.builder.appName("IngestLoanProducts").getOrCreate()

    print("--- Ingesting CDW_LN_PROD -> loan_products ---")
    raw = read_source(spark, SOURCE_PATH)
    print(f"Source record count: {raw.count()}")

    good_df, quarantine_df = transform_loan_products(raw)
    stats = write_target(good_df, quarantine_df)

    print(f"Target records written: {stats['target_count']}")
    print(f"Quarantined records:    {stats['quarantine_count']}")
    return stats


if __name__ == "__main__":
    run()
