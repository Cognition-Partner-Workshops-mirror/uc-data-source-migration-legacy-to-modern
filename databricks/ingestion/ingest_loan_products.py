"""Ingest legacy CDW_LN_PROD into Delta Lake ``loan_warehouse.loan_products``.

Reads from a CSV/Parquet source file that mirrors the legacy CDW_LN_PROD
table structure. Applies type conversions, status-to-boolean conversion,
and null auditing before writing to the target Delta table.

Usage:
    from databricks.ingestion.ingest_loan_products import run
    run(spark, source_path="...", target_table="loan_warehouse.loan_products")
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from databricks.ingestion.utils import (
    PRODUCT_STATUS_MAP,
    add_ingestion_metadata,
    expand_status_bool,
    log_null_counts,
    parse_amount,
    parse_date,
    parse_int,
)

EXPECTED_COLUMNS = [
    "PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD", "PROD_TERM_MOS",
    "PROD_RT_TYP", "PROD_MIN_AMT", "PROD_MAX_AMT", "PROD_STAT_CD",
    "PROD_EFF_DT", "PROD_EXP_DT",
]

REQUIRED_FIELDS = ["PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD"]


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv") -> DataFrame:
    if file_format == "parquet":
        return spark.read.parquet(source_path)
    return spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)


def validate_schema(df: DataFrame) -> DataFrame:
    missing = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Source is missing expected columns: {sorted(missing)}")
    return df


def quarantine_bad_rows(df: DataFrame) -> tuple:
    condition = F.lit(True)
    for col_name in REQUIRED_FIELDS:
        condition = condition & F.col(col_name).isNotNull() & (F.trim(F.col(col_name)) != "")
    good_df = df.filter(condition)
    quarantine_df = df.filter(~condition)

    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        print(f"[WARN] Quarantined {quarantine_count} loan product rows with missing required fields.")

    return good_df, quarantine_df


def transform(df: DataFrame) -> DataFrame:
    # Date conversions
    df = parse_date(df, "PROD_EFF_DT", "effective_date")
    df = parse_date(df, "PROD_EXP_DT", "expiration_date")

    # Numeric conversions
    df = parse_int(df, "PROD_TERM_MOS", "term_months")
    df = parse_amount(df, "PROD_MIN_AMT", "min_amount", precision=12, scale=2)
    df = parse_amount(df, "PROD_MAX_AMT", "max_amount", precision=12, scale=2)

    # Status to boolean
    df = expand_status_bool(df, "PROD_STAT_CD", PRODUCT_STATUS_MAP, "is_active")

    # Rename direct-copy columns
    df = (
        df.withColumnRenamed("PROD_CD", "code")
        .withColumnRenamed("PROD_DESC_TXT", "name")
        .withColumnRenamed("PROD_TYP_CD", "type")
        .withColumnRenamed("PROD_RT_TYP", "rate_type")
    )

    df = add_ingestion_metadata(df, "CDW_LN_PROD")

    final_columns = [
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "is_active",
        "effective_date", "expiration_date",
        "_ingestion_ts", "_source_system",
    ]
    return df.select(*final_columns)


def write_target(df: DataFrame, target_table: str, mode: str = "overwrite") -> None:
    df.write.format("delta").mode(mode).saveAsTable(target_table)
    row_count = df.count()
    print(f"[INFO] Wrote {row_count} rows to {target_table}.")


def run(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.loan_products",
    file_format: str = "csv",
    quarantine_path: str | None = None,
) -> dict:
    print(f"[INFO] Starting loan product ingestion from {source_path}")

    raw_df = read_source(spark, source_path, file_format)
    raw_df = validate_schema(raw_df)
    raw_count = raw_df.count()
    print(f"[INFO] Source row count: {raw_count}")

    good_df, quarantine_df = quarantine_bad_rows(raw_df)
    log_null_counts(good_df, "CDW_LN_PROD (pre-transform)", EXPECTED_COLUMNS)

    transformed_df = transform(good_df)
    write_target(transformed_df, target_table)

    quarantine_count = quarantine_df.count()
    if quarantine_count > 0 and quarantine_path:
        quarantine_df.write.format("delta").mode("overwrite").save(quarantine_path)
        print(f"[WARN] {quarantine_count} quarantined rows written to {quarantine_path}")

    return {
        "source_count": raw_count,
        "loaded_count": raw_count - quarantine_count,
        "quarantined_count": quarantine_count,
        "target_table": target_table,
    }
