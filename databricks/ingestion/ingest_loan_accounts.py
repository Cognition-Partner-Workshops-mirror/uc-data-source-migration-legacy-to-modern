"""
Ingestion script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads the legacy loan account extract, strips denormalized borrower fields,
resolves foreign keys to the modern borrowers and loan_products tables, and
applies type conversions.

Prerequisite: borrowers and loan_products must be ingested first.

Usage:
    spark-submit ingest_loan_accounts.py --source /mnt/landing/cdw_ln_acct/
"""

import argparse
import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status_code,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_integer,
    parse_legacy_timestamp,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_loan_accounts")

TARGET_TABLE = "loan_warehouse.loan_accounts"


def read_source(spark: SparkSession, source_path: str) -> DataFrame:
    """Read the legacy loan account extract."""
    if source_path.endswith(".parquet") or source_path.endswith("/parquet"):
        return spark.read.parquet(source_path)
    return spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)


def resolve_borrower_keys(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join against the modern borrowers table to resolve borrower_key from external_id."""
    borrowers = spark.table("loan_warehouse.borrowers").select(
        F.col("borrower_key"),
        F.col("external_id").alias("_borr_ext_id"),
    )
    joined = df.join(borrowers, df["BORR_ID"] == borrowers["_borr_ext_id"], "left")

    unmatched = joined.filter(F.col("borrower_key").isNull()).count()
    if unmatched > 0:
        logger.error("Loan accounts with no matching borrower: %d", unmatched)
        # Log the unmatched IDs for investigation
        unmatched_ids = (
            joined.filter(F.col("borrower_key").isNull())
            .select("LN_ACCT_NBR", "BORR_ID")
            .collect()
        )
        for row in unmatched_ids:
            logger.error(
                "  Unmatched: account=%s, borrower_id=%s",
                row["LN_ACCT_NBR"], row["BORR_ID"],
            )

    return joined


def resolve_product_keys(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join against the modern loan_products table to resolve product_key from code."""
    products = spark.table("loan_warehouse.loan_products").select(
        F.col("product_key"),
        F.col("code").alias("_prod_code"),
    )
    joined = df.join(products, df["PROD_CD"] == products["_prod_code"], "left")

    unmatched = joined.filter(F.col("product_key").isNull()).count()
    if unmatched > 0:
        logger.error("Loan accounts with no matching product: %d", unmatched)
        unmatched_ids = (
            joined.filter(F.col("product_key").isNull())
            .select("LN_ACCT_NBR", "PROD_CD")
            .collect()
        )
        for row in unmatched_ids:
            logger.error(
                "  Unmatched: account=%s, product_code=%s",
                row["LN_ACCT_NBR"], row["PROD_CD"],
            )

    return joined


def transform(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Apply all column mappings, FK resolution, and type conversions."""
    source_count = df.count()
    logger.info("Source CDW_LN_ACCT row count: %d", source_count)

    # Resolve foreign keys
    df = resolve_borrower_keys(spark, df)
    df = resolve_product_keys(spark, df)

    transformed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("borrower_key"),
        F.col("product_key"),
        parse_legacy_amount("LN_ORIG_AMT").alias("original_amount"),
        parse_legacy_amount("LN_CURR_BAL").alias("current_balance"),
        F.regexp_replace(F.col("LN_INT_RT"), ",", "").cast("decimal(5,3)").alias("interest_rate"),
        parse_legacy_integer("LN_TERM_MOS").alias("term_months"),
        parse_legacy_amount("LN_PMT_AMT", 10, 2).alias("monthly_payment"),
        parse_legacy_date("LN_ORIG_DT").alias("origination_date"),
        parse_legacy_date("LN_MAT_DT").alias("maturity_date"),
        parse_legacy_date("LN_1ST_PMT_DT").alias("first_payment_date"),
        parse_legacy_date("LN_NXT_PMT_DT").alias("next_payment_date"),
        expand_status_code("LN_STAT_CD", LOAN_STATUS_MAP).alias("status"),
        parse_legacy_integer("LN_DLQ_DAYS").alias("delinquency_days"),
        parse_legacy_amount("LN_ESCROW_BAL", 10, 2).alias("escrow_balance"),
        F.regexp_replace(F.col("LN_LTV_PCT"), ",", "").cast("decimal(5,2)").alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_status_code("PROP_TYP_CD", PROPERTY_TYPE_MAP).alias("property_type"),
        parse_legacy_amount("PROP_APRS_VAL").alias("appraised_value"),
        parse_legacy_timestamp("LN_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("LN_UPDT_DT").alias("updated_at"),
        F.lit("CDW_LN_ACCT").alias("_migration_source"),
        F.current_timestamp().alias("_migrated_at"),
    )

    # Log null required fields
    for col_name in ["account_number", "borrower_key", "product_key",
                     "original_amount", "current_balance", "interest_rate",
                     "term_months", "monthly_payment", "origination_date", "maturity_date"]:
        null_count = transformed.filter(F.col(col_name).isNull()).count()
        if null_count > 0:
            logger.warning("Records with NULL %s: %d", col_name, null_count)

    target_count = transformed.count()
    logger.info("Transformed row count: %d", target_count)
    if source_count != target_count:
        logger.error(
            "ROW COUNT MISMATCH: source=%d, transformed=%d", source_count, target_count
        )

    return transformed


def write_target(df: DataFrame) -> None:
    """Write the transformed loan accounts to Delta Lake."""
    df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).partitionBy("status").saveAsTable(TARGET_TABLE)
    logger.info("Successfully wrote %d rows to %s", df.count(), TARGET_TABLE)


def main(source_path: str) -> None:
    spark = SparkSession.builder.appName("Ingest_CDW_LN_ACCT").getOrCreate()
    try:
        raw_df = read_source(spark, source_path)
        transformed_df = transform(spark, raw_df)
        write_target(transformed_df)
    except Exception:
        logger.exception("Loan account ingestion failed")
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_ACCT to Delta Lake")
    parser.add_argument("--source", required=True, help="Path to legacy loan account CSV/Parquet")
    args = parser.parse_args()
    main(args.source)
