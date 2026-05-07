"""
Ingestion notebook: CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan-product reference data, applies type conversions and
status-code expansion, and writes to the modern Delta Lake table.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    expand_product_status_to_bool,
    parse_amount,
    parse_date_mmddyyyy,
    parse_int,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/legacy-export/CDW_LN_PROD"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"
WRITE_MODE = "overwrite"

# ---------------------------------------------------------------------------
# Spark
# ---------------------------------------------------------------------------
spark = SparkSession.builder.appName("ingest_loan_products").getOrCreate()
spark.conf.set("spark.sql.legacy.timeParserPolicy", "CORRECTED")

_LOG_TAG = "[ingest_loan_products]"


def _log(msg: str) -> None:
    print(f"{_LOG_TAG} {msg}")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(path: str, fmt: str) -> DataFrame:
    _log(f"Reading source from {path} (format={fmt})")
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(path)
    _log(f"Source row count: {df.count()}")
    return df


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame) -> DataFrame:
    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_int(F.col("PROD_TERM_MOS")).alias("term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount(F.col("PROD_MIN_AMT")).alias("min_amount"),
        parse_amount(F.col("PROD_MAX_AMT")).alias("max_amount"),
        expand_product_status_to_bool(F.col("PROD_STAT_CD")).alias("is_active"),
        parse_date_mmddyyyy(F.col("PROD_EFF_DT")).alias("effective_date"),
        parse_date_mmddyyyy(F.col("PROD_EXP_DT")).alias("expiration_date"),
    )

    null_codes = transformed.filter(F.col("code").isNull()).count()
    if null_codes > 0:
        _log(f"WARNING: {null_codes} rows have NULL product code")

    bad_term = transformed.filter(
        F.col("term_months").isNull() & df["PROD_TERM_MOS"].isNotNull()
    ).count()
    if bad_term > 0:
        _log(f"WARNING: {bad_term} rows had unparseable term_months values")

    _log(f"Transformed row count: {transformed.count()}")
    return transformed


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(df: DataFrame, table: str, mode: str) -> None:
    _log(f"Writing {df.count()} rows to {table} (mode={mode})")
    df.write.format("delta").mode(mode).option(
        "mergeSchema", "true"
    ).saveAsTable(table)
    _log("Write complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    source_df = read_source(SOURCE_PATH, SOURCE_FORMAT)
    transformed_df = transform(source_df)
    write_target(transformed_df, TARGET_TABLE, WRITE_MODE)
    _log("Loan product ingestion finished successfully.")


if __name__ == "__main__":
    main()
