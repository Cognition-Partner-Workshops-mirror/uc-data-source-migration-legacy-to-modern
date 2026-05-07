"""
Ingest CDW_LN_ACCT (legacy) -> loan_accounts (Delta Lake).

Source: CSV or Parquet export of the CDW_LN_ACCT table.
Target: loan_warehouse.loan_accounts Delta table.

Key transformations:
  - DROP denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
    and resolve borrower_id via FK lookup against the borrowers table
  - Resolve product_id via FK lookup against the loan_products table
  - Parse all date strings (MM/DD/YYYY) to DateType / TimestampType
  - Parse all amount strings (comma-formatted) to DecimalType
  - Expand loan status codes (ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE)
  - Expand property type codes (SFR->Single Family, etc.)
  - Derive origination_year from origination_date for analytics
  - Generate surrogate id
  - Flag (not drop) rows with quality issues
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from databricks.ingestion.transformations import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    add_row_quality_flag,
    expand_status_col,
    log_null_counts,
    parse_amount_col,
    parse_date_col,
    parse_decimal_col,
    parse_int_col,
    parse_timestamp_col,
)
from databricks.schemas.loan_accounts import (
    LOAN_ACCOUNTS_PARTITION_COLS,
    LOAN_ACCOUNTS_PATH,
)

logger = logging.getLogger("loan_migration.ingest_loan_accounts")

REQUIRED_COLS = [
    "account_number", "borrower_id", "product_id",
    "original_amount", "current_balance", "interest_rate",
    "term_months", "monthly_payment", "origination_date",
    "maturity_date", "status",
]

SOURCE_FILE_DEFAULT = "/mnt/legacy/CDW_LN_ACCT"


def read_source(spark: SparkSession, path: str = SOURCE_FILE_DEFAULT, fmt: str = "csv") -> DataFrame:
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _build_borrower_lookup(spark: SparkSession) -> DataFrame:
    """
    Build a lookup DataFrame mapping legacy BORR_ID (external_id)
    to the modern borrowers surrogate id.
    """
    borrowers_df = spark.read.format("delta").load("/mnt/delta/loan_warehouse/borrowers")
    return borrowers_df.select(
        F.col("id").alias("_borrower_pk"),
        F.col("external_id").alias("_borr_ext_id"),
    )


def _build_product_lookup(spark: SparkSession) -> DataFrame:
    """
    Build a lookup DataFrame mapping legacy PROD_CD
    to the modern loan_products surrogate id.
    """
    products_df = spark.read.format("delta").load("/mnt/delta/loan_warehouse/loan_products")
    return products_df.select(
        F.col("id").alias("_product_pk"),
        F.col("code").alias("_prod_code"),
    )


def transform(source_df: DataFrame, spark: SparkSession) -> DataFrame:
    """Apply all transformations including FK resolution."""

    borrower_lookup = _build_borrower_lookup(spark)
    product_lookup = _build_product_lookup(spark)

    # Base transformations (column renames + type conversions)
    base = source_df.select(
        F.monotonically_increasing_id().alias("id"),
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("_legacy_borr_id"),
        F.col("PROD_CD").alias("_legacy_prod_cd"),
        parse_amount_col("LN_ORIG_AMT", "original_amount"),
        parse_amount_col("LN_CURR_BAL", "current_balance"),
        parse_decimal_col("LN_INT_RT", "interest_rate", 5, 3),
        parse_int_col("LN_TERM_MOS", "term_months"),
        parse_amount_col("LN_PMT_AMT", "monthly_payment", 10, 2),
        parse_date_col("LN_ORIG_DT", "origination_date"),
        parse_date_col("LN_MAT_DT", "maturity_date"),
        parse_date_col("LN_1ST_PMT_DT", "first_payment_date"),
        parse_date_col("LN_NXT_PMT_DT", "next_payment_date"),
        expand_status_col("LN_STAT_CD", LOAN_STATUS_MAP, "status"),
        parse_int_col("LN_DLQ_DAYS", "delinquency_days"),
        parse_amount_col("LN_ESCROW_BAL", "escrow_balance", 10, 2),
        parse_decimal_col("LN_LTV_PCT", "ltv_percent", 5, 2),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_status_col("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
        parse_amount_col("PROP_APRS_VAL", "appraised_value"),
        parse_timestamp_col("LN_CRET_DT", "created_at"),
        parse_timestamp_col("LN_UPDT_DT", "updated_at"),
        # Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) dropped
    )

    # Resolve borrower FK
    with_borrower = base.join(
        borrower_lookup,
        base["_legacy_borr_id"] == borrower_lookup["_borr_ext_id"],
        "left",
    ).withColumn("borrower_id", F.col("_borrower_pk"))

    unresolved_borrowers = with_borrower.filter(F.col("borrower_id").isNull()).count()
    if unresolved_borrowers > 0:
        logger.warning(
            "loan_accounts: %d records have unresolvable borrower IDs",
            unresolved_borrowers,
        )

    # Resolve product FK
    with_product = with_borrower.join(
        product_lookup,
        with_borrower["_legacy_prod_cd"] == product_lookup["_prod_code"],
        "left",
    ).withColumn("product_id", F.col("_product_pk"))

    unresolved_products = with_product.filter(F.col("product_id").isNull()).count()
    if unresolved_products > 0:
        logger.warning(
            "loan_accounts: %d records have unresolvable product codes",
            unresolved_products,
        )

    # Derive origination_year for analytics
    result = with_product.withColumn(
        "origination_year", F.year(F.col("origination_date"))
    )

    # Select final columns in schema order
    final = result.select(
        "id", "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "first_payment_date", "next_payment_date",
        "status", "delinquency_days", "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state",
        "property_zip", "property_type", "appraised_value",
        "origination_year", "created_at", "updated_at",
    )

    return add_row_quality_flag(final, REQUIRED_COLS)


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    clean_df = df.drop("_has_quality_issue")
    writer = clean_df.write.format("delta").mode(mode)
    if LOAN_ACCOUNTS_PARTITION_COLS:
        writer = writer.partitionBy(*LOAN_ACCOUNTS_PARTITION_COLS)
    writer.save(LOAN_ACCOUNTS_PATH)
    logger.info("Wrote loan_accounts to %s", LOAN_ACCOUNTS_PATH)


def run(spark: SparkSession, source_path: str = SOURCE_FILE_DEFAULT, fmt: str = "csv") -> dict:
    logger.info("Starting loan_accounts ingestion from %s", source_path)

    source_df = read_source(spark, source_path, fmt)
    source_count = source_df.count()
    logger.info("Source row count: %d", source_count)

    transformed_df = transform(source_df, spark)
    target_count = transformed_df.count()

    null_issues = log_null_counts(transformed_df, "loan_accounts", REQUIRED_COLS)
    quality_issues = transformed_df.filter(F.col("_has_quality_issue")).count()

    write_target(transformed_df)

    summary = {
        "table": "loan_accounts",
        "source_count": source_count,
        "target_count": target_count,
        "records_with_quality_issues": quality_issues,
        "null_counts": null_issues,
    }
    logger.info("Loan accounts ingestion complete: %s", summary)
    return summary
