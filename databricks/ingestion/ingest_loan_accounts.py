"""
Ingest CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy loan accounts table, resolves FK references to borrowers
and loan_products already loaded into Delta, drops denormalized borrower
columns, and writes the typed loan_accounts fact table.

Execution order: run AFTER ingest_borrowers.py and ingest_loan_products.py.

Usage:
    spark-submit ingest_loan_accounts.py --source /mnt/landing/cdw_ln_acct --format csv
"""

import logging
from argparse import ArgumentParser

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status_code_preserving,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_int,
    parse_legacy_timestamp,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ingest_loan_accounts")

TARGET_TABLE = "loan_warehouse.loan_accounts"


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def resolve_borrower_ids(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join with the borrowers Delta table to resolve BORR_ID -> borrower_id."""
    borrowers = spark.read.table("loan_warehouse.borrowers").select(
        F.col("borrower_id"), F.col("external_id")
    )
    joined = df.join(borrowers, df["BORR_ID"] == borrowers["external_id"], "left")

    unresolved = joined.filter(F.col("borrower_id").isNull())
    unresolved_count = unresolved.count()
    if unresolved_count > 0:
        logger.warning(
            "Found %d loan accounts with unresolved BORR_ID (no matching borrower).",
            unresolved_count,
        )
        unresolved.select("LN_ACCT_NBR", "BORR_ID").show(truncate=False)

    return joined


def resolve_product_ids(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join with the loan_products Delta table to resolve PROD_CD -> product_id."""
    products = spark.read.table("loan_warehouse.loan_products").select(
        F.col("product_id"), F.col("code").alias("_prod_code")
    )
    joined = df.join(products, df["PROD_CD"] == products["_prod_code"], "left")

    unresolved = joined.filter(F.col("product_id").isNull())
    unresolved_count = unresolved.count()
    if unresolved_count > 0:
        logger.warning(
            "Found %d loan accounts with unresolved PROD_CD (no matching product).",
            unresolved_count,
        )
        unresolved.select("LN_ACCT_NBR", "PROD_CD").show(truncate=False)

    return joined


def transform(spark: SparkSession, df: DataFrame) -> tuple:
    source_count = df.count()
    logger.info("Source CDW_LN_ACCT row count: %d", source_count)

    # Resolve foreign keys
    df = resolve_borrower_ids(spark, df)
    df = resolve_product_ids(spark, df)

    transformed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("borrower_id"),
        F.col("product_id"),
        parse_legacy_amount("LN_ORIG_AMT").alias("original_amount"),
        parse_legacy_amount("LN_CURR_BAL").alias("current_balance"),
        parse_legacy_amount("LN_INT_RT", precision=5, scale=3).alias("interest_rate"),
        parse_legacy_int("LN_TERM_MOS").alias("term_months"),
        parse_legacy_amount("LN_PMT_AMT", precision=10, scale=2).alias("monthly_payment"),
        parse_legacy_date("LN_ORIG_DT").alias("origination_date"),
        parse_legacy_date("LN_MAT_DT").alias("maturity_date"),
        parse_legacy_date("LN_1ST_PMT_DT").alias("first_payment_date"),
        parse_legacy_date("LN_NXT_PMT_DT").alias("next_payment_date"),
        expand_status_code_preserving("LN_STAT_CD", LOAN_STATUS_MAP).alias("status"),
        parse_legacy_int("LN_DLQ_DAYS").alias("delinquency_days"),
        parse_legacy_amount("LN_ESCROW_BAL", precision=10, scale=2).alias("escrow_balance"),
        parse_legacy_amount("LN_LTV_PCT", precision=5, scale=2).alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_status_code_preserving("PROP_TYP_CD", PROPERTY_TYPE_MAP).alias(
            "property_type"
        ),
        parse_legacy_amount("PROP_APRS_VAL").alias("appraised_value"),
        parse_legacy_timestamp("LN_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("LN_UPDT_DT").alias("updated_at"),
        F.col("LN_ACCT_NBR").alias("_legacy_ln_acct_nbr"),
        F.current_timestamp().alias("_ingestion_ts"),
    )

    # Quality: required fields
    null_required = transformed.filter(
        F.col("account_number").isNull()
        | F.col("borrower_id").isNull()
        | F.col("product_id").isNull()
        | F.col("original_amount").isNull()
        | F.col("current_balance").isNull()
        | F.col("origination_date").isNull()
    )
    null_count = null_required.count()
    if null_count > 0:
        logger.warning(
            "Found %d loan account rows with NULL required fields. Quarantining.",
            null_count,
        )

    good = transformed.filter(
        F.col("account_number").isNotNull()
        & F.col("borrower_id").isNotNull()
        & F.col("product_id").isNotNull()
        & F.col("original_amount").isNotNull()
        & F.col("current_balance").isNotNull()
        & F.col("origination_date").isNotNull()
    )
    quarantine = transformed.filter(
        F.col("account_number").isNull()
        | F.col("borrower_id").isNull()
        | F.col("product_id").isNull()
        | F.col("original_amount").isNull()
        | F.col("current_balance").isNull()
        | F.col("origination_date").isNull()
    )

    logger.info(
        "Transform complete: %d good rows, %d quarantined (source: %d)",
        good.count(),
        quarantine.count(),
        source_count,
    )
    return good, quarantine


def write_target(good: DataFrame, quarantine: DataFrame, quarantine_path: str) -> None:
    good.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)
    logger.info("Wrote %d rows to %s", good.count(), TARGET_TABLE)

    if quarantine.count() > 0:
        quarantine.write.format("delta").mode("overwrite").save(quarantine_path)
        logger.info("Wrote %d quarantined rows to %s", quarantine.count(), quarantine_path)


def main(source_path: str, source_format: str, quarantine_path: str) -> None:
    spark = SparkSession.builder.appName("CDW_LN_ACCT_Ingestion").getOrCreate()

    logger.info("Reading source from %s (format=%s)", source_path, source_format)
    raw = read_source(spark, source_path, source_format)

    good, quarantine = transform(spark, raw)
    write_target(good, quarantine, quarantine_path)
    logger.info("Loan account ingestion complete.")


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Ingest CDW_LN_ACCT into loan_accounts Delta table"
    )
    parser.add_argument("--source", required=True, help="Path to source data")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"])
    parser.add_argument(
        "--quarantine",
        default="/mnt/quarantine/loan_accounts",
        help="Path for quarantined records",
    )
    args = parser.parse_args()
    main(args.source, args.format, args.quarantine)
