"""
Ingest loan accounts from legacy CDW_LN_ACCT into Delta Lake ``loan_warehouse.loan_accounts``.

Key transformations:
  - Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  - Resolve BORR_ID -> borrower_id FK via the already-ingested borrowers table
  - Resolve PROD_CD -> product_id FK via the already-ingested loan_products table
  - Parse all date, amount, and integer columns
  - Expand LN_STAT_CD (ACT/CLO/DFT/FRB) and PROP_TYP_CD (SFR/CND/MFR/TWN)

Usage:
    spark-submit ingest_loan_accounts.py --source /mnt/landing/cdw_ln_acct --format csv
"""

import argparse
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from common_utils import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    collect_parse_errors,
    drop_audit_columns,
    expand_status_col,
    log_error_summary,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
    read_legacy_source,
)

TARGET_TABLE = "loan_warehouse.loan_accounts"
SOURCE_SYSTEM = "CDW_LN_ACCT"
DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_ln_acct"


def transform_loan_accounts(raw_df, spark):
    """Apply all column-level transformations and FK resolution."""

    df = raw_df

    # --- Date conversions ---
    df = parse_date_col(df, "LN_ORIG_DT", "origination_date")
    df = parse_date_col(df, "LN_MAT_DT", "maturity_date")
    df = parse_date_col(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date_col(df, "LN_NXT_PMT_DT", "next_payment_date")
    df = parse_timestamp_col(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "LN_UPDT_DT", "updated_at")

    # --- Amount conversions ---
    df = parse_amount_col(df, "LN_ORIG_AMT", "original_amount", 12, 2)
    df = parse_amount_col(df, "LN_CURR_BAL", "current_balance", 12, 2)
    df = parse_amount_col(df, "LN_PMT_AMT", "monthly_payment", 10, 2)
    df = parse_amount_col(df, "LN_ESCROW_BAL", "escrow_balance", 10, 2)
    df = parse_amount_col(df, "PROP_APRS_VAL", "appraised_value", 12, 2)
    df = parse_amount_col(df, "LN_INT_RT", "interest_rate", 5, 3)
    df = parse_amount_col(df, "LN_LTV_PCT", "ltv_percent", 5, 2)

    # --- Integer conversions ---
    df = parse_int_col(df, "LN_TERM_MOS", "term_months")
    df = parse_int_col(df, "LN_DLQ_DAYS", "delinquency_days")

    # --- Status / code expansion ---
    df = expand_status_col(df, "LN_STAT_CD", "status", LOAN_STATUS_MAP)
    df = expand_status_col(df, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)

    # --- Direct-copy renames ---
    df = (
        df.withColumn("account_number", F.col("LN_ACCT_NBR"))
          .withColumn("property_address", F.col("PROP_ADDR_LN1"))
          .withColumn("property_city", F.col("PROP_CTY_NM"))
          .withColumn("property_state", F.col("PROP_ST_CD"))
          .withColumn("property_zip", F.col("PROP_ZIP_CD"))
    )

    # --- FK resolution: BORR_ID -> borrower_id ---
    borrowers_lkp = spark.table("loan_warehouse.borrowers").select(
        F.col("borrower_id").alias("_resolved_borrower_id"),
        F.col("external_id").alias("_borr_ext_id"),
    )
    df = df.join(
        borrowers_lkp,
        df["BORR_ID"] == borrowers_lkp["_borr_ext_id"],
        "left",
    )
    df = df.withColumn("borrower_id", F.col("_resolved_borrower_id"))
    # Flag unresolved borrower references
    df = df.withColumn(
        "__borrower_id_unresolved",
        F.when(F.col("borrower_id").isNull() & F.col("BORR_ID").isNotNull(), True)
         .otherwise(False),
    )

    # --- FK resolution: PROD_CD -> product_id ---
    products_lkp = spark.table("loan_warehouse.loan_products").select(
        F.col("product_id").alias("_resolved_product_id"),
        F.col("code").alias("_prod_code"),
    )
    df = df.join(
        products_lkp,
        df["PROD_CD"] == products_lkp["_prod_code"],
        "left",
    )
    df = df.withColumn("product_id", F.col("_resolved_product_id"))
    df = df.withColumn(
        "__product_id_unresolved",
        F.when(F.col("product_id").isNull() & F.col("PROD_CD").isNotNull(), True)
         .otherwise(False),
    )

    # --- Metadata ---
    df = (
        df.withColumn("_migration_ts", F.current_timestamp())
          .withColumn("_source_system", F.lit(SOURCE_SYSTEM))
    )

    return df


def run(spark, source_path, source_format="csv", write_mode="overwrite"):
    """End-to-end ingestion pipeline for loan accounts."""

    print(f"=== Ingesting {SOURCE_SYSTEM} -> {TARGET_TABLE} ===")
    print(f"  Source: {source_path} ({source_format})")

    raw_df = read_legacy_source(spark, source_path, fmt=source_format)
    source_count = raw_df.count()
    print(f"  Source row count: {source_count}")

    if source_count == 0:
        print("  WARNING: Source is empty. Skipping ingestion.")
        return {"source_count": 0, "target_count": 0, "errors": {}}

    transformed_df = transform_loan_accounts(raw_df, spark)

    error_summary = log_error_summary(transformed_df, SOURCE_SYSTEM)
    error_rows = collect_parse_errors(transformed_df)
    error_count = error_rows.count()
    if error_count > 0:
        print(f"  WARNING: {error_count} row(s) had parse issues — writing anyway.")
        error_rows.write.mode("overwrite").parquet(
            f"/mnt/migration_errors/{SOURCE_SYSTEM}_errors"
        )

    # Check for unresolved FK references
    unresolved_borrowers = transformed_df.filter(F.col("__borrower_id_unresolved") == True).count()  # noqa: E712
    unresolved_products = transformed_df.filter(F.col("__product_id_unresolved") == True).count()  # noqa: E712
    if unresolved_borrowers > 0:
        print(f"  WARNING: {unresolved_borrowers} row(s) with unresolved borrower FK")
    if unresolved_products > 0:
        print(f"  WARNING: {unresolved_products} row(s) with unresolved product FK")

    final_df = drop_audit_columns(transformed_df).select(
        "account_number",
        "borrower_id",
        "product_id",
        "original_amount",
        "current_balance",
        "interest_rate",
        "term_months",
        "monthly_payment",
        "origination_date",
        "maturity_date",
        "first_payment_date",
        "next_payment_date",
        "status",
        "delinquency_days",
        "escrow_balance",
        "ltv_percent",
        "property_address",
        "property_city",
        "property_state",
        "property_zip",
        "property_type",
        "appraised_value",
        "created_at",
        "updated_at",
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
        "unresolved_borrower_fks": unresolved_borrowers,
        "unresolved_product_fks": unresolved_products,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_ACCT into Delta Lake")
    parser.add_argument("--source", default=DEFAULT_SOURCE_PATH)
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    args = parser.parse_args()

    spark = SparkSession.builder.appName("IngestLoanAccounts").getOrCreate()
    result = run(spark, args.source, args.format, args.mode)
    if result["source_count"] != result["target_count"]:
        print("ERROR: Row count mismatch!")
        sys.exit(1)
