"""Ingest legacy CDW_LN_ACCT into modern loan_accounts Delta table.

Key transformations:
- Drop denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
- Resolve BORR_ID → borrower_id FK via borrowers table lookup
- Resolve PROD_CD → product_id FK via loan_products table lookup
- Expand status codes and property type codes
- Parse all date/amount/numeric string columns
"""

import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    drop_flag_columns,
    expand_status,
    log_parse_errors,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
)

logger = logging.getLogger("ingestion.loan_accounts")
logging.basicConfig(level=logging.INFO)

SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_ln_acct"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
BORROWER_TABLE = "loan_warehouse.borrowers"
PRODUCT_TABLE = "loan_warehouse.loan_products"


def read_source(spark: SparkSession, path: str = SOURCE_PATH, fmt: str = SOURCE_FORMAT) -> DataFrame:
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(path)


def resolve_borrower_fk(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Join to borrowers table to resolve BORR_ID → borrower_id (BIGINT FK)."""
    borrowers = spark.table(BORROWER_TABLE).select(
        F.col("id").alias("borrower_id"),
        F.col("external_id"),
    )
    df = df.join(borrowers, df["BORR_ID"] == borrowers["external_id"], "left")
    df = df.withColumn(
        "_flag_borrower_id_unresolved",
        F.when(F.col("borrower_id").isNull(), F.lit(True)).otherwise(F.lit(False)),
    )
    unresolved = df.filter(F.col("borrower_id").isNull()).count()
    if unresolved > 0:
        logger.warning("%d loan accounts have unresolved borrower_id", unresolved)
    return df.drop("BORR_ID", "external_id")


def resolve_product_fk(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Join to loan_products table to resolve PROD_CD → product_id (BIGINT FK)."""
    products = spark.table(PRODUCT_TABLE).select(
        F.col("id").alias("product_id"),
        F.col("code").alias("_prod_code"),
    )
    df = df.join(products, df["PROD_CD"] == products["_prod_code"], "left")
    df = df.withColumn(
        "_flag_product_id_unresolved",
        F.when(F.col("product_id").isNull(), F.lit(True)).otherwise(F.lit(False)),
    )
    unresolved = df.filter(F.col("product_id").isNull()).count()
    if unresolved > 0:
        logger.warning("%d loan accounts have unresolved product_id", unresolved)
    return df.drop("PROD_CD", "_prod_code")


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Apply all column mappings and type conversions for loan accounts."""

    # Drop denormalized borrower columns
    df = df.drop("BORR_FST_NM", "BORR_LST_NM", "BORR_SSN_LST4")

    # Rename direct-copy columns
    df = df.withColumnRenamed("LN_ACCT_NBR", "account_number")

    # Resolve foreign keys
    df = resolve_borrower_fk(df, spark)
    df = resolve_product_fk(df, spark)

    # Amount parsing
    df = parse_amount_col(df, "LN_ORIG_AMT", "original_amount")
    df = parse_amount_col(df, "LN_CURR_BAL", "current_balance")
    df = parse_amount_col(df, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    df = parse_amount_col(df, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
    df = parse_amount_col(df, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
    df = parse_amount_col(df, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)
    df = parse_amount_col(df, "PROP_APRS_VAL", "appraised_value")

    # Integer parsing
    df = parse_int_col(df, "LN_TERM_MOS", "term_months")
    df = parse_int_col(df, "LN_DLQ_DAYS", "delinquency_days")

    # Date parsing
    df = parse_date_col(df, "LN_ORIG_DT", "origination_date")
    df = parse_date_col(df, "LN_MAT_DT", "maturity_date")
    df = parse_date_col(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date_col(df, "LN_NXT_PMT_DT", "next_payment_date")

    # Timestamp parsing
    df = parse_timestamp_col(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "LN_UPDT_DT", "updated_at")

    # Status expansion
    df = expand_status(df, "LN_STAT_CD", "status", LOAN_STATUS_MAP)

    # Property type expansion
    df = expand_status(df, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)

    # Rename remaining property columns
    df = (
        df
        .withColumnRenamed("PROP_ADDR_LN1", "property_address")
        .withColumnRenamed("PROP_CTY_NM", "property_city")
        .withColumnRenamed("PROP_ST_CD", "property_state")
        .withColumnRenamed("PROP_ZIP_CD", "property_zip")
    )

    # Drop all replaced legacy source columns
    legacy_cols_to_drop = [
        "LN_ORIG_AMT", "LN_CURR_BAL", "LN_INT_RT", "LN_PMT_AMT",
        "LN_ESCROW_BAL", "LN_LTV_PCT", "PROP_APRS_VAL",
        "LN_TERM_MOS", "LN_DLQ_DAYS",
        "LN_ORIG_DT", "LN_MAT_DT", "LN_1ST_PMT_DT", "LN_NXT_PMT_DT",
        "LN_CRET_DT", "LN_UPDT_DT",
        "LN_STAT_CD", "PROP_TYP_CD",
    ]
    df = df.drop(*legacy_cols_to_drop)

    return df


def write_target(df: DataFrame, table: str = TARGET_TABLE) -> None:
    (
        df
        .write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(table)
    )


def run(spark: SparkSession) -> int:
    """Execute the loan account ingestion pipeline. Returns source row count."""
    logger.info("Reading legacy loan account data from %s", SOURCE_PATH)
    raw_df = read_source(spark)
    source_count = raw_df.count()
    logger.info("Source row count: %d", source_count)

    logger.info("Applying transformations (includes FK resolution)")
    transformed_df = transform(raw_df, spark)

    log_parse_errors(transformed_df, "loan_accounts", logger)
    clean_df = drop_flag_columns(transformed_df)

    logger.info("Writing to %s", TARGET_TABLE)
    write_target(clean_df)

    target_count = spark.table(TARGET_TABLE).count()
    logger.info("Target row count: %d", target_count)

    if source_count != target_count:
        logger.error(
            "Row count mismatch! source=%d target=%d", source_count, target_count
        )

    return source_count


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest_LoanAccounts").getOrCreate()
    run(spark)
