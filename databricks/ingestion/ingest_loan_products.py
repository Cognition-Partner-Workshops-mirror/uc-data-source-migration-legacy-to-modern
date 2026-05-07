"""
Ingestion script: CDW_LN_PROD → loan_warehouse.loan_products

Reads legacy loan product data, applies type conversions, and writes to Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from common_transforms import (
    parse_legacy_date,
    parse_legacy_amount,
    parse_legacy_integer,
    add_ingestion_metadata,
    flag_null_required_fields,
    log_rejected_records,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_LN_PROD/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_PATH = "dbfs:/mnt/legacy-cdw/quarantine/loan_products/"

REQUIRED_FIELDS = ["product_code", "name", "type", "term_months", "rate_type", "is_active"]

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "mode": "PERMISSIVE",
    "columnNameOfCorruptRecord": "_corrupt_record",
}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH) -> DataFrame:
    return (
        spark.read
        .format(SOURCE_FORMAT)
        .options(**CSV_OPTIONS)
        .load(path)
    )


def transform(df: DataFrame) -> DataFrame:
    return df.select(
        F.trim(F.col("PROD_CD")).alias("product_code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.trim(F.col("PROD_TYP_CD")).alias("type"),
        parse_legacy_integer("PROD_TERM_MOS", "term_months"),
        F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
        parse_legacy_amount("PROD_MIN_AMT", "min_amount"),
        parse_legacy_amount("PROD_MAX_AMT", "max_amount"),
        F.when(F.trim(F.col("PROD_STAT_CD")) == "ACT", F.lit(True))
         .otherwise(F.lit(False))
         .alias("is_active"),
        parse_legacy_date("PROD_EFF_DT", "effective_date"),
        parse_legacy_date("PROD_EXP_DT", "expiration_date"),
    )


def validate_and_split(df: DataFrame, spark: SparkSession) -> tuple:
    df = flag_null_required_fields(df, REQUIRED_FIELDS)
    valid_df, rejected_df = log_rejected_records(df, "_has_nulls", "loan_products", spark)
    valid_df = valid_df.drop("_has_nulls")
    return valid_df, rejected_df


def write_target(df: DataFrame) -> None:
    (
        df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )


def write_quarantine(df: DataFrame) -> None:
    if df.count() > 0:
        df.write.format("delta").mode("append").save(QUARANTINE_PATH)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession, source_path: str = SOURCE_PATH) -> dict:
    raw_df = read_source(spark, source_path)
    source_count = raw_df.count()

    transformed_df = transform(raw_df)
    transformed_df = add_ingestion_metadata(transformed_df)

    valid_df, rejected_df = validate_and_split(transformed_df, spark)
    valid_count = valid_df.count()
    rejected_count = rejected_df.count()

    write_target(valid_df)
    write_quarantine(rejected_df)

    summary = {
        "table": "loan_products",
        "source_count": source_count,
        "valid_count": valid_count,
        "rejected_count": rejected_count,
    }
    print(f"[loan_products] Ingested {valid_count}/{source_count} records "
          f"({rejected_count} quarantined)")
    return summary


if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestLoanProducts").getOrCreate()
    run(spark)
