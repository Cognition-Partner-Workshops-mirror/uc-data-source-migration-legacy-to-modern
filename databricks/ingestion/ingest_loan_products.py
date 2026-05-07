"""
PySpark ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads legacy loan product reference data, applies column mappings and
type conversions, and writes to the modern Delta Lake loan_products table.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

try:
    from transforms import (
        parse_legacy_date,
        parse_legacy_amount,
        parse_legacy_integer,
        PRODUCT_STATUS_MAP,
    )
except ImportError:
    pass


LEGACY_SOURCE_PATH = "/mnt/legacy-cdw/CDW_LN_PROD"
TARGET_TABLE = "loan_warehouse.loan_products"
SOURCE_FORMAT = "csv"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "quote": '"',
    "escape": '"',
}


def read_legacy_products(spark: SparkSession) -> DataFrame:
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for k, v in CSV_OPTIONS.items():
            reader = reader.option(k, v)
    return reader.load(LEGACY_SOURCE_PATH)


def transform_products(raw: DataFrame) -> DataFrame:
    """
    Apply column mappings from CDW_LN_PROD -> loan_products:
    - Rename columns to meaningful names
    - Parse term_months (string -> int), min/max amounts (string -> decimal)
    - Convert PROD_STAT_CD to boolean is_active
    - Parse effective/expiration dates
    """
    stat_col = F.trim(F.upper(F.col("PROD_STAT_CD")))
    is_active_expr = F.when(stat_col == "ACT", F.lit(True)).otherwise(F.lit(False))

    transformed = (
        raw
        .withColumn("code", F.trim(F.col("PROD_CD")))
        .withColumn("name", F.col("PROD_DESC_TXT"))
        .withColumn("type", F.col("PROD_TYP_CD"))
        .withColumn("term_months", parse_legacy_integer("PROD_TERM_MOS"))
        .withColumn("rate_type", F.col("PROD_RT_TYP"))
        .withColumn("min_amount", parse_legacy_amount("PROD_MIN_AMT"))
        .withColumn("max_amount", parse_legacy_amount("PROD_MAX_AMT"))
        .withColumn("is_active", is_active_expr)
        .withColumn("effective_date", parse_legacy_date("PROD_EFF_DT"))
        .withColumn("expiration_date", parse_legacy_date("PROD_EXP_DT"))
        .withColumn("_legacy_prod_cd", F.col("PROD_CD"))
    )

    return transformed.select(
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "is_active",
        "effective_date", "expiration_date", "_legacy_prod_cd",
    )


def write_products(df: DataFrame, mode: str = "overwrite") -> None:
    (
        df.write
        .format("delta")
        .mode(mode)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )


def run(spark: SparkSession = None) -> int:
    if spark is None:
        spark = SparkSession.builder.getOrCreate()

    print("=" * 70)
    print("INGESTION: CDW_LN_PROD -> loan_warehouse.loan_products")
    print("=" * 70)

    raw = read_legacy_products(spark)
    source_count = raw.count()
    print(f"Source rows read: {source_count}")

    transformed = transform_products(raw)
    target_count = transformed.count()
    print(f"Target rows to write: {target_count}")

    write_products(transformed)
    print(f"SUCCESS: {target_count} rows written to {TARGET_TABLE}")

    return target_count


if __name__ == "__main__":
    run()
