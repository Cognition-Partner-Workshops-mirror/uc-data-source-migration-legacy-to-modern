"""
Ingestion script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads the legacy loan accounts table, applies column renames, type
conversions, status expansion, property type expansion, and drops
denormalized borrower columns in favor of FK references.

Requires that borrowers and loan_products tables are already populated so
that FK lookups can resolve legacy IDs to modern surrogate keys.

Usage (Databricks notebook cell):
    ingest_loan_accounts(spark, source_path="/mnt/landing/cdw_ln_acct/")
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from databricks.ingestion.common import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_int,
    parse_percent,
    parse_rate,
    parse_timestamp,
)

logger = logging.getLogger("migration.ingest_loan_accounts")

TARGET_TABLE = "loan_warehouse.loan_accounts"
SOURCE_TABLE = "CDW_LN_ACCT"


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv") -> DataFrame:
    if file_format == "parquet":
        return spark.read.parquet(source_path)
    return (
        spark.read.option("header", "true")
        .option("inferSchema", "false")
        .csv(source_path)
    )


def transform(spark: SparkSession, df: DataFrame) -> DataFrame:
    quarantine_condition = (
        F.col("LN_ACCT_NBR").isNull()
        | F.col("BORR_ID").isNull()
        | F.col("PROD_CD").isNull()
    )

    quarantined = df.filter(quarantine_condition)
    if quarantined.count() > 0:
        logger.warning(
            "Quarantined %d loan account records with null required fields",
            quarantined.count(),
        )
        quarantined.write.mode("append").format("delta").saveAsTable(
            "loan_warehouse._quarantine_loan_accounts"
        )

    clean = df.filter(~quarantine_condition)

    # Resolve borrower FK: legacy BORR_ID → modern borrowers.id
    borrowers = spark.table("loan_warehouse.borrowers").select(
        F.col("id").alias("_borrower_id"),
        F.col("external_id").alias("_borr_ext_id"),
    )

    # Resolve product FK: legacy PROD_CD → modern loan_products.id
    products = spark.table("loan_warehouse.loan_products").select(
        F.col("id").alias("_product_id"),
        F.col("code").alias("_prod_code"),
    )

    joined = (
        clean.join(borrowers, clean["BORR_ID"] == borrowers["_borr_ext_id"], "left")
        .join(products, clean["PROD_CD"] == products["_prod_code"], "left")
    )

    # Log unresolved FKs
    unresolved_borrowers = joined.filter(F.col("_borrower_id").isNull())
    if unresolved_borrowers.count() > 0:
        logger.warning(
            "Found %d loan accounts with unresolved borrower FK (BORR_ID not in borrowers)",
            unresolved_borrowers.count(),
        )

    unresolved_products = joined.filter(F.col("_product_id").isNull())
    if unresolved_products.count() > 0:
        logger.warning(
            "Found %d loan accounts with unresolved product FK (PROD_CD not in loan_products)",
            unresolved_products.count(),
        )

    origination_date_col = parse_date(F.col("LN_ORIG_DT"))

    transformed = joined.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("_borrower_id").alias("borrower_id"),
        F.col("_product_id").alias("product_id"),
        parse_amount(F.col("LN_ORIG_AMT")).alias("original_amount"),
        parse_amount(F.col("LN_CURR_BAL")).alias("current_balance"),
        parse_rate(F.col("LN_INT_RT")).alias("interest_rate"),
        parse_int(F.col("LN_TERM_MOS")).alias("term_months"),
        parse_amount(F.col("LN_PMT_AMT"), 10, 2).alias("monthly_payment"),
        origination_date_col.alias("origination_date"),
        parse_date(F.col("LN_MAT_DT")).alias("maturity_date"),
        parse_date(F.col("LN_1ST_PMT_DT")).alias("first_payment_date"),
        parse_date(F.col("LN_NXT_PMT_DT")).alias("next_payment_date"),
        expand_status(F.col("LN_STAT_CD"), LOAN_STATUS_MAP).alias("status"),
        parse_int(F.col("LN_DLQ_DAYS")).alias("delinquency_days"),
        parse_amount(F.col("LN_ESCROW_BAL"), 10, 2).alias("escrow_balance"),
        parse_percent(F.col("LN_LTV_PCT")).alias("ltv_percent"),
        F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
        F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
        F.trim(F.col("PROP_ST_CD")).alias("property_state"),
        F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
        expand_status(F.col("PROP_TYP_CD"), PROPERTY_TYPE_MAP).alias("property_type"),
        parse_amount(F.col("PROP_APRS_VAL")).alias("appraised_value"),
        parse_timestamp(F.col("LN_CRET_DT")).alias("created_at"),
        parse_timestamp(F.col("LN_UPDT_DT")).alias("updated_at"),
        F.year(origination_date_col).alias("origination_year"),
        F.lit(SOURCE_TABLE).alias("_migration_src"),
        F.current_timestamp().alias("_migrated_at"),
    )

    return transformed


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    df.write.format("delta").mode(mode).partitionBy("status").saveAsTable(TARGET_TABLE)


def ingest_loan_accounts(
    spark: SparkSession,
    source_path: str,
    file_format: str = "csv",
    write_mode: str = "overwrite",
) -> dict:
    logger.info("Starting loan account ingestion from %s", source_path)

    raw = read_source(spark, source_path, file_format)
    source_count = raw.count()
    logger.info("Read %d records from source", source_count)

    transformed = transform(spark, raw)
    target_count = transformed.count()
    logger.info("Transformed %d records (quarantined %d)", target_count, source_count - target_count)

    write_target(transformed, write_mode)
    logger.info("Wrote %d records to %s", target_count, TARGET_TABLE)

    return {"source_count": source_count, "target_count": target_count}
