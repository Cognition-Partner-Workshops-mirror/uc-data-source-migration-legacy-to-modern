"""
Ingest loan products from legacy CDW_LN_PROD into Delta Lake ``loan_warehouse.loan_products``.

Transformations applied:
  - PROD_TERM_MOS (string)            -> term_months     (IntegerType)
  - PROD_MIN_AMT / PROD_MAX_AMT       -> min/max_amount  (Decimal)
  - PROD_STAT_CD (ACT/INA)            -> is_active       (BooleanType)
  - PROD_EFF_DT / PROD_EXP_DT         -> effective/expiration_date (DateType)

Usage:
    spark-submit ingest_loan_products.py --source /mnt/landing/cdw_ln_prod --format csv
"""

import argparse
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import BooleanType

from common_utils import (
    PRODUCT_STATUS_MAP,
    collect_parse_errors,
    drop_audit_columns,
    log_error_summary,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    read_legacy_source,
)

TARGET_TABLE = "loan_warehouse.loan_products"
SOURCE_SYSTEM = "CDW_LN_PROD"
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_ln_prod"


def transform_loan_products(raw_df):
    """Apply all column-level transformations to a raw CDW_LN_PROD DataFrame."""

    df = raw_df

    # --- Numeric conversions ---
    df = parse_int_col(df, "PROD_TERM_MOS", "term_months")
    df = parse_amount_col(df, "PROD_MIN_AMT", "min_amount", precision=12, scale=2)
    df = parse_amount_col(df, "PROD_MAX_AMT", "max_amount", precision=12, scale=2)

    # --- Date conversions ---
    df = parse_date_col(df, "PROD_EFF_DT", "effective_date")
    df = parse_date_col(df, "PROD_EXP_DT", "expiration_date")

    # --- Boolean status conversion ---
    # ACT -> true, INA -> false; anything else -> null with a flag
    is_active_expr = F.when(
        F.upper(F.trim(F.col("PROD_STAT_CD"))) == "ACT", F.lit(True)
    ).when(
        F.upper(F.trim(F.col("PROD_STAT_CD"))) == "INA", F.lit(False)
    ).otherwise(F.lit(None).cast(BooleanType()))

    err_flag = F.when(
        F.col("PROD_STAT_CD").isNotNull()
        & ~F.upper(F.trim(F.col("PROD_STAT_CD"))).isin("ACT", "INA"),
        True,
    ).otherwise(False)

    df = (
        df.withColumn("is_active", is_active_expr)
          .withColumn("__is_active_unmapped", err_flag)
    )

    # --- Direct-copy renames ---
    df = (
        df.withColumn("code", F.col("PROD_CD"))
          .withColumn("name", F.col("PROD_DESC_TXT"))
          .withColumn("type", F.col("PROD_TYP_CD"))
          .withColumn("rate_type", F.col("PROD_RT_TYP"))
    )

    # --- Metadata ---
    df = (
        df.withColumn("_migration_ts", F.current_timestamp())
          .withColumn("_source_system", F.lit(SOURCE_SYSTEM))
    )

    return df


def run(spark, source_path, source_format="csv", write_mode="overwrite"):
    """End-to-end ingestion pipeline for loan products."""

    print(f"=== Ingesting {SOURCE_SYSTEM} -> {TARGET_TABLE} ===")
    print(f"  Source: {source_path} ({source_format})")

    raw_df = read_legacy_source(spark, source_path, fmt=source_format)
    source_count = raw_df.count()
    print(f"  Source row count: {source_count}")

    if source_count == 0:
        print("  WARNING: Source is empty. Skipping ingestion.")
        return {"source_count": 0, "target_count": 0, "errors": {}}

    transformed_df = transform_loan_products(raw_df)

    error_summary = log_error_summary(transformed_df, SOURCE_SYSTEM)
    error_rows = collect_parse_errors(transformed_df)
    error_count = error_rows.count()
    if error_count > 0:
        print(f"  WARNING: {error_count} row(s) had parse issues — writing anyway.")
        error_rows.write.mode("overwrite").parquet(
            f"/mnt/migration_errors/{SOURCE_SYSTEM}_errors"
        )

    final_df = drop_audit_columns(transformed_df).select(
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
        "_migration_ts",
        "_source_system",
    )

    (
        final_df.write
        .format("delta")
        .mode(write_mode)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    target_count = spark.table(TARGET_TABLE).count()
    print(f"  Target row count: {target_count}")
    print(f"  Reconciliation: source={source_count}, target={target_count}, "
          f"match={source_count == target_count}")
    print(f"=== {SOURCE_SYSTEM} ingestion complete ===\n")

    return {
        "source_count": source_count,
        "target_count": target_count,
        "errors": error_summary,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_PROD into Delta Lake")
    parser.add_argument("--source", default=DEFAULT_SOURCE_PATH)
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    spark = SparkSession.builder.appName("IngestLoanProducts").getOrCreate()
    result = run(spark, args.source, args.format, args.mode)
    if result["source_count"] != result["target_count"]:
        print("ERROR: Row count mismatch!")
        sys.exit(1)
