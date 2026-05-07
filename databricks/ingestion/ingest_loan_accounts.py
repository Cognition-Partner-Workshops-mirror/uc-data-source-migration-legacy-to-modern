"""
Ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy loan accounts table, strips denormalized borrower fields,
converts types, expands status codes, and expands property type abbreviations.

Usage:
    spark-submit ingest_loan_accounts.py --source /mnt/legacy/CDW_LN_ACCT.csv
"""

import argparse
import sys

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status_col,
    log_rejected_rows,
    logger,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
    read_legacy_csv,
    read_legacy_parquet,
    write_delta,
)

TARGET_TABLE = "loan_warehouse.loan_accounts"


def transform_loan_accounts(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Transform legacy CDW_LN_ACCT records to modern loan_accounts schema.

    Denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
    are intentionally dropped. The borrower_external_id (BORR_ID) is retained
    as the FK reference to the borrowers dimension table.

    Returns:
        (valid_df, rejected_df)
    """
    logger.info("Starting loan account transformation. Source row count: %d", df.count())

    # Drop denormalized borrower columns per column_mappings.md
    renamed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("borrower_external_id"),
        # BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 intentionally dropped
        F.col("PROD_CD").alias("product_code"),
        F.col("LN_ORIG_AMT").alias("original_amount"),
        F.col("LN_CURR_BAL").alias("current_balance"),
        F.col("LN_INT_RT").alias("interest_rate"),
        F.col("LN_TERM_MOS").alias("term_months"),
        F.col("LN_PMT_AMT").alias("monthly_payment"),
        F.col("LN_ORIG_DT").alias("origination_date"),
        F.col("LN_MAT_DT").alias("maturity_date"),
        F.col("LN_1ST_PMT_DT").alias("first_payment_date"),
        F.col("LN_NXT_PMT_DT").alias("next_payment_date"),
        F.col("LN_STAT_CD").alias("status"),
        F.col("LN_DLQ_DAYS").alias("delinquency_days"),
        F.col("LN_ESCROW_BAL").alias("escrow_balance"),
        F.col("LN_LTV_PCT").alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        F.col("PROP_TYP_CD").alias("property_type"),
        F.col("PROP_APRS_VAL").alias("appraised_value"),
        F.col("LN_CRET_DT").alias("created_at"),
        F.col("LN_UPDT_DT").alias("updated_at"),
    )

    # Build property type expansion map
    prop_type_map_expr = F.create_map(
        [F.lit(x) for pair in PROPERTY_TYPE_MAP.items() for x in pair]
    )

    transformed = renamed.select(
        F.col("account_number"),
        F.col("borrower_external_id"),
        F.col("product_code"),
        parse_amount_col("original_amount"),
        parse_amount_col("current_balance"),
        parse_amount_col("interest_rate", precision=5, scale=3),
        parse_int_col("term_months"),
        parse_amount_col("monthly_payment", precision=10, scale=2),
        parse_date_col("origination_date"),
        parse_date_col("maturity_date"),
        parse_date_col("first_payment_date"),
        parse_date_col("next_payment_date"),
        expand_status_col("status", LOAN_STATUS_MAP, default="ACTIVE"),
        parse_int_col("delinquency_days"),
        parse_amount_col("escrow_balance", precision=10, scale=2),
        parse_amount_col("ltv_percent", precision=5, scale=2),
        F.col("property_address"),
        F.col("property_city"),
        F.col("property_state"),
        F.col("property_zip"),
        F.coalesce(prop_type_map_expr[F.col("property_type")], F.col("property_type")).alias("property_type"),
        parse_amount_col("appraised_value"),
        parse_timestamp_col("created_at"),
        parse_timestamp_col("updated_at"),
    )

    # Derive origination_year for partitioning helper
    transformed = transformed.withColumn(
        "origination_year",
        F.year(F.col("origination_date")),
    )

    transformed = (
        transformed
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit("CDW_LN_ACCT"))
    )

    # Required-field validation
    valid = transformed.filter(
        F.col("account_number").isNotNull()
        & F.col("borrower_external_id").isNotNull()
        & F.col("product_code").isNotNull()
        & F.col("original_amount").isNotNull()
        & F.col("current_balance").isNotNull()
        & F.col("interest_rate").isNotNull()
        & F.col("origination_date").isNotNull()
        & F.col("maturity_date").isNotNull()
    )
    rejected = transformed.filter(
        F.col("account_number").isNull()
        | F.col("borrower_external_id").isNull()
        | F.col("product_code").isNull()
        | F.col("original_amount").isNull()
        | F.col("current_balance").isNull()
        | F.col("interest_rate").isNull()
        | F.col("origination_date").isNull()
        | F.col("maturity_date").isNull()
    )

    logger.info(
        "Loan account transformation complete. Valid: %d, Rejected: %d",
        valid.count(), rejected.count(),
    )
    return valid, rejected


def run(spark: SparkSession, source_path: str, source_format: str = "csv") -> None:
    """Execute the loan account ingestion pipeline."""
    if source_format == "parquet":
        raw_df = read_legacy_parquet(spark, source_path)
    else:
        raw_df = read_legacy_csv(spark, source_path)

    valid_df, rejected_df = transform_loan_accounts(raw_df)

    log_rejected_rows(
        rejected_df,
        "Missing required fields (account_number, borrower_external_id, product_code, amounts, dates)",
        TARGET_TABLE,
    )

    write_delta(valid_df, TARGET_TABLE, mode="overwrite", partition_cols=["status"])
    logger.info("Loan account ingestion complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_ACCT into Delta Lake loan_accounts table")
    parser.add_argument("--source", required=True, help="Path to legacy CDW_LN_ACCT export (CSV or Parquet)")
    parser.add_argument("--format", default="csv", choices=["csv", "parquet"], help="Source file format")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Migration_LoanAccounts").getOrCreate()
    try:
        run(spark, args.source, args.format)
    except Exception:
        logger.exception("Loan account ingestion failed")
        sys.exit(1)
    finally:
        spark.stop()
