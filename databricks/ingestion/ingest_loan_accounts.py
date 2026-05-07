"""
Ingest legacy CDW_LN_ACCT into Delta Lake loan_accounts table.

Reads legacy loan account data (denormalized), strips redundant borrower
columns, applies type conversions, expands status/property-type codes,
derives the origination_year partition key, and writes to
loan_warehouse.loan_accounts.

Usage:
    spark-submit ingest_loan_accounts.py [--source /mnt/landing/cdw_ln_acct.csv]
"""

import sys
import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transform_utils import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    collect_parse_errors,
    drop_parse_error_columns,
    expand_status_column,
    parse_amount_column,
    parse_date_column,
    parse_int_column,
    parse_timestamp_column,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_loan_accounts")

DEFAULT_SOURCE_PATH = "/mnt/landing/cdw_ln_acct"
DEFAULT_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(path)
    logger.info("Read %d rows from source %s (%s)", df.count(), path, fmt)
    return df


def transform_loan_accounts(df: DataFrame) -> DataFrame:
    """Apply all transformations for CDW_LN_ACCT -> loan_accounts."""
    logger.info("Starting loan account transformations")

    # -- Drop denormalized borrower columns (use FK instead) ----------------
    denorm_cols = ["BORR_FST_NM", "BORR_LST_NM", "BORR_SSN_LST4"]
    dropped_count = 0
    for col_name in denorm_cols:
        if col_name in df.columns:
            df = df.drop(col_name)
            dropped_count += 1
    logger.info("Dropped %d denormalized borrower columns", dropped_count)

    # -- Date fields --------------------------------------------------------
    df = parse_date_column(df, "LN_ORIG_DT", "origination_date")
    df = parse_date_column(df, "LN_MAT_DT", "maturity_date")
    df = parse_date_column(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date_column(df, "LN_NXT_PMT_DT", "next_payment_date")
    df = parse_timestamp_column(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp_column(df, "LN_UPDT_DT", "updated_at")

    # -- Numeric / amount fields --------------------------------------------
    df = parse_amount_column(df, "LN_ORIG_AMT", "original_amount")
    df = parse_amount_column(df, "LN_CURR_BAL", "current_balance")
    df = parse_amount_column(df, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    df = parse_int_column(df, "LN_TERM_MOS", "term_months")
    df = parse_amount_column(df, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
    df = parse_int_column(df, "LN_DLQ_DAYS", "delinquency_days")
    df = parse_amount_column(df, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
    df = parse_amount_column(df, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)
    df = parse_amount_column(df, "PROP_APRS_VAL", "appraised_value")

    # -- Status / code expansion --------------------------------------------
    df = expand_status_column(df, "LN_STAT_CD", "status", LOAN_STATUS_MAP)
    df = expand_status_column(df, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)

    # -- Direct-copy renames ------------------------------------------------
    df = (
        df.withColumnRenamed("LN_ACCT_NBR", "account_number")
          .withColumnRenamed("BORR_ID", "borrower_external_id")
          .withColumnRenamed("PROD_CD", "product_code")
          .withColumnRenamed("PROP_ADDR_LN1", "property_address")
          .withColumnRenamed("PROP_CTY_NM", "property_city")
          .withColumnRenamed("PROP_ST_CD", "property_state")
          .withColumnRenamed("PROP_ZIP_CD", "property_zip")
    )

    # -- Derived partition key ----------------------------------------------
    df = df.withColumn(
        "origination_year",
        F.year(F.col("origination_date")),
    )

    # -- Lineage metadata ---------------------------------------------------
    df = (
        df.withColumn("_migration_source", F.lit("CDW_LN_ACCT"))
          .withColumn("_migrated_at", F.current_timestamp())
    )

    return df


def validate_and_log_errors(df: DataFrame) -> DataFrame:
    error_summary = collect_parse_errors(df, "loan_accounts")
    if error_summary.count() > 0:
        logger.warning("Loan account parse errors detected:")
        error_summary.show(truncate=False)
    else:
        logger.info("No parse errors in loan account data")
    return drop_parse_error_columns(df)


def select_target_columns(df: DataFrame) -> DataFrame:
    return df.select(
        "account_number",
        "borrower_external_id",
        "product_code",
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
        "_migration_source",
        "_migrated_at",
    )


def write_to_delta(df: DataFrame, mode: str = "overwrite") -> None:
    record_count = df.count()
    logger.info("Writing %d loan account records to %s", record_count, TARGET_TABLE)
    (
        df.write
          .format("delta")
          .mode(mode)
          .option("mergeSchema", "true")
          .partitionBy("origination_year")
          .saveAsTable(TARGET_TABLE)
    )
    logger.info("Successfully wrote %d records to %s", record_count, TARGET_TABLE)


def run(source_path: str = DEFAULT_SOURCE_PATH, source_format: str = DEFAULT_SOURCE_FORMAT) -> None:
    spark = SparkSession.builder.appName("CDW_LoanAccount_Ingestion").getOrCreate()

    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform_loan_accounts(raw_df)
    clean_df = validate_and_log_errors(transformed_df)
    final_df = select_target_columns(clean_df)
    write_to_delta(final_df)

    logger.info("Loan account ingestion complete")


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE_PATH
    fmt = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SOURCE_FORMAT
    run(source_path=source, source_format=fmt)
