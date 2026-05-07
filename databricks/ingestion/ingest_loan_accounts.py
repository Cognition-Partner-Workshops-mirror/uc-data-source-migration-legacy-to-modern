"""
Ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy loan accounts file, applies all type conversions, expands
status and property-type codes, drops denormalized borrower fields, resolves
FK references to borrowers and loan_products, and writes to Delta Lake.

Usage:
    spark-submit --master local[*] ingest_loan_accounts.py \
        --source /mnt/landing/cdw_ln_acct.csv \
        --format csv \
        --target loan_catalog.loan_warehouse.loan_accounts \
        --borrowers-table loan_catalog.loan_warehouse.borrowers \
        --products-table loan_catalog.loan_warehouse.loan_products
"""

import argparse
import logging
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from utils import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status_with_fallback,
    log_null_counts,
    parse_amount_expr,
    parse_date_expr,
    parse_int_expr,
    parse_rate_expr,
    parse_timestamp_expr,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("cdw_migration.loan_accounts")


def read_source(spark: SparkSession, path: str, fmt: str):
    if fmt == "csv":
        return spark.read.option("header", "true").option("inferSchema", "false").csv(path)
    elif fmt == "parquet":
        return spark.read.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform(df, spark: SparkSession, borrowers_table: str, products_table: str):
    source_count = df.count()
    logger.info("Source row count: %d", source_count)

    # ---- FK lookup DataFrames ----
    borrowers_df = spark.table(borrowers_table).select(
        F.col("borrower_id").alias("_b_id"),
        F.col("external_id").alias("_b_ext_id"),
    )
    products_df = spark.table(products_table).select(
        F.col("product_id").alias("_p_id"),
        F.col("code").alias("_p_code"),
    )

    # ---- Build property type expansion ----
    property_type_expr = expand_status_with_fallback("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type")

    # ---- Core transformations ----
    transformed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("_borr_id_lookup"),
        F.col("PROD_CD").alias("_prod_cd_lookup"),
        parse_amount_expr("LN_ORIG_AMT", "original_amount"),
        parse_amount_expr("LN_CURR_BAL", "current_balance"),
        parse_rate_expr("LN_INT_RT", "interest_rate"),
        parse_int_expr("LN_TERM_MOS", "term_months"),
        parse_amount_expr("LN_PMT_AMT", "monthly_payment", precision=10),
        parse_date_expr("LN_ORIG_DT", "origination_date"),
        parse_date_expr("LN_MAT_DT", "maturity_date"),
        parse_date_expr("LN_1ST_PMT_DT", "first_payment_date"),
        parse_date_expr("LN_NXT_PMT_DT", "next_payment_date"),
        expand_status_with_fallback("LN_STAT_CD", LOAN_STATUS_MAP, "status"),
        parse_int_expr("LN_DLQ_DAYS", "delinquency_days"),
        parse_amount_expr("LN_ESCROW_BAL", "escrow_balance", precision=10),
        F.col("LN_LTV_PCT").cast("decimal(5,2)").alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        property_type_expr,
        parse_amount_expr("PROP_APRS_VAL", "appraised_value"),
        parse_timestamp_expr("LN_CRET_DT", "created_at"),
        parse_timestamp_expr("LN_UPDT_DT", "updated_at"),
        F.current_timestamp().alias("_ingestion_ts"),
    )

    # ---- Resolve borrower FK ----
    transformed = transformed.join(
        borrowers_df,
        transformed["_borr_id_lookup"] == borrowers_df["_b_ext_id"],
        "left",
    ).withColumn("borrower_id", F.col("_b_id"))

    unresolved_borrowers = transformed.filter(F.col("borrower_id").isNull()).count()
    if unresolved_borrowers > 0:
        logger.warning(
            "%d loan accounts have no matching borrower (orphan BORR_ID). "
            "These rows are RETAINED with borrower_id=NULL for manual review.",
            unresolved_borrowers,
        )

    # ---- Resolve product FK ----
    transformed = transformed.join(
        products_df,
        transformed["_prod_cd_lookup"] == products_df["_p_code"],
        "left",
    ).withColumn("product_id", F.col("_p_id"))

    unresolved_products = transformed.filter(F.col("product_id").isNull()).count()
    if unresolved_products > 0:
        logger.warning(
            "%d loan accounts have no matching product (orphan PROD_CD). "
            "These rows are RETAINED with product_id=NULL for manual review.",
            unresolved_products,
        )

    # ---- Derive partition column ----
    transformed = transformed.withColumn(
        "origination_year", F.year(F.col("origination_date"))
    )

    # ---- Select final columns (drop lookup helpers) ----
    final = transformed.select(
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
        "origination_year",
        "_ingestion_ts",
    )

    required_cols = [
        "account_number", "borrower_id", "product_id", "original_amount",
        "current_balance", "interest_rate", "origination_date", "status",
    ]
    log_null_counts(final, "loan_accounts", required_cols)

    target_count = final.count()
    logger.info("Target row count: %d", target_count)
    if source_count != target_count:
        logger.error("ROW COUNT MISMATCH: source=%d, target=%d", source_count, target_count)

    return final


def write_target(df, target_table: str, mode: str = "overwrite"):
    logger.info("Writing %d rows to %s (mode=%s)", df.count(), target_table, mode)
    df.write.format("delta").mode(mode).partitionBy("origination_year").saveAsTable(target_table)
    logger.info("Write complete.")


def main():
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_ACCT into loan_accounts Delta table")
    parser.add_argument("--source", required=True, help="Path to legacy loan accounts source file")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    parser.add_argument("--target", default="loan_catalog.loan_warehouse.loan_accounts", help="Target Delta table")
    parser.add_argument("--borrowers-table", default="loan_catalog.loan_warehouse.borrowers", help="Borrowers table for FK resolution")
    parser.add_argument("--products-table", default="loan_catalog.loan_warehouse.loan_products", help="Loan products table for FK resolution")
    parser.add_argument("--mode", default="overwrite", choices=["overwrite", "append"], help="Write mode")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_LoanAccounts").getOrCreate()

    try:
        raw_df = read_source(spark, args.source, args.format)
        transformed_df = transform(raw_df, spark, args.borrowers_table, args.products_table)
        write_target(transformed_df, args.target, args.mode)
    except Exception:
        logger.exception("Loan accounts ingestion failed")
        sys.exit(1)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
