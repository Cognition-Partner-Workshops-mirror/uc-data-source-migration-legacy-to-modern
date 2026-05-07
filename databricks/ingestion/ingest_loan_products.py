"""
Ingest CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan products table exported as CSV/Parquet, converts
string-encoded terms and amounts to proper types, maps status codes to
boolean is_active, and writes to the modern Delta Lake table.

Usage:
    from ingestion.ingest_loan_products import run
    report_df = run(spark, source_path="...", source_format="csv")
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import BooleanType

from transform_utils import (
    PRODUCT_STATUS_MAP,
    collect_bad_value_report,
    drop_flag_columns,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
)

TARGET_TABLE = "loan_warehouse.loan_products"
SOURCE_TABLE = "CDW_LN_PROD"


def read_source(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
) -> DataFrame:
    reader = spark.read.format(source_format)
    if source_format == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(source_path)


def transform(df: DataFrame) -> DataFrame:
    # --- direct renames ---
    df = (
        df.withColumnRenamed("PROD_CD", "code")
        .withColumnRenamed("PROD_DESC_TXT", "name")
        .withColumnRenamed("PROD_TYP_CD", "type")
        .withColumnRenamed("PROD_RT_TYP", "rate_type")
    )

    # --- type conversions ---
    df = parse_int_col(df, "PROD_TERM_MOS", "term_months")
    df = parse_amount_col(df, "PROD_MIN_AMT", "min_amount")
    df = parse_amount_col(df, "PROD_MAX_AMT", "max_amount")
    df = parse_date_col(df, "PROD_EFF_DT", "effective_date")
    df = parse_date_col(df, "PROD_EXP_DT", "expiration_date")

    # --- status -> boolean is_active ---
    status_map = F.create_map(
        *[item for pair in PRODUCT_STATUS_MAP.items() for item in (F.lit(pair[0]), F.lit(pair[1]))]
    )
    df = df.withColumn(
        "is_active",
        status_map[F.upper(F.trim(F.col("PROD_STAT_CD")))].cast(BooleanType()),
    )
    df = df.withColumn(
        "_unmapped_is_active",
        F.when(
            F.col("PROD_STAT_CD").isNotNull() & F.col("is_active").isNull(),
            F.col("PROD_STAT_CD"),
        ),
    )
    # Default unknown statuses to active
    df = df.withColumn(
        "is_active",
        F.coalesce(F.col("is_active"), F.lit(True)),
    )

    # --- drop transformed legacy columns ---
    df = df.drop("PROD_TERM_MOS", "PROD_MIN_AMT", "PROD_MAX_AMT",
                  "PROD_EFF_DT", "PROD_EXP_DT", "PROD_STAT_CD")

    # --- lineage ---
    df = df.withColumn("_migration_source", F.lit(SOURCE_TABLE))
    df = df.withColumn("_migrated_at", F.current_timestamp())

    return df


def run(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
    write_mode: str = "overwrite",
) -> DataFrame:
    raw_df = read_source(spark, source_path, source_format)
    source_count = raw_df.count()
    print(f"[{SOURCE_TABLE}] Source row count: {source_count}")

    transformed_df = transform(raw_df)

    bad_report = collect_bad_value_report(transformed_df, SOURCE_TABLE)
    bad_count = bad_report.count()
    if bad_count > 0:
        print(f"[{SOURCE_TABLE}] WARNING: {bad_count} parse issues detected")
        bad_report.show(truncate=False)

    clean_df = drop_flag_columns(transformed_df)

    final_df = clean_df.select(
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "is_active",
        "effective_date", "expiration_date",
        "_migration_source", "_migrated_at",
    )

    final_df.write.format("delta").mode(write_mode).saveAsTable(TARGET_TABLE)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[{SOURCE_TABLE}] Target row count: {target_count}")

    if source_count != target_count:
        print(
            f"[{SOURCE_TABLE}] ERROR: Row count mismatch! "
            f"source={source_count}, target={target_count}"
        )

    return bad_report
