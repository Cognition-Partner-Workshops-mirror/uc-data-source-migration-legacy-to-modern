"""
Ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy denormalized loan accounts table, strips the embedded
borrower fields (using FK to borrowers table instead), applies type
conversions, expands status/property codes, and writes to Delta Lake.

Requires borrowers and loan_products tables to be loaded first for FK
resolution (borrower external_id -> borrower_id, product code -> product_id).

Usage:
    spark-submit --master local[*] ingest_loan_accounts.py \
        --source-path /mnt/legacy/cdw_ln_acct \
        --source-format csv \
        --target-table loan_warehouse.loan_accounts \
        --borrower-table loan_warehouse.borrowers \
        --product-table loan_warehouse.loan_products \
        --error-path /mnt/migration/errors/loan_accounts
"""

import argparse
import logging
import sys
from datetime import datetime

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status_col,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_loan_accounts")


def read_source(spark: SparkSession, path: str, fmt: str) -> DataFrame:
    reader = spark.read.option("header", "true")
    if fmt == "csv":
        reader = reader.option("inferSchema", "false")
    return reader.format(fmt).load(path)


def resolve_borrower_fk(spark: SparkSession, borrower_table: str) -> DataFrame:
    """Load borrower lookup: external_id -> borrower_id."""
    return spark.table(borrower_table).select(
        F.col("borrower_id"),
        F.col("external_id").alias("_borr_external_id"),
    )


def resolve_product_fk(spark: SparkSession, product_table: str) -> DataFrame:
    """Load product lookup: code -> product_id."""
    return spark.table(product_table).select(
        F.col("product_id"),
        F.col("code").alias("_prod_code"),
    )


def transform(
    df: DataFrame,
    borrower_lookup: DataFrame,
    product_lookup: DataFrame,
) -> tuple[DataFrame, DataFrame]:
    run_ts = datetime.utcnow().isoformat()

    # Expand property type codes
    prop_type_expr = F.col("PROP_TYP_CD")
    for code, label in PROPERTY_TYPE_MAP.items():
        prop_type_expr = F.when(F.col("PROP_TYP_CD") == code, F.lit(label)).otherwise(
            prop_type_expr
        )

    # Core transformations (drop denormalized borrower fields)
    transformed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("_borr_external_id"),
        F.col("PROD_CD").alias("_prod_code"),
        parse_amount_col("LN_ORIG_AMT").alias("original_amount"),
        parse_amount_col("LN_CURR_BAL").alias("current_balance"),
        parse_amount_col("LN_INT_RT", 5, 3).alias("interest_rate"),
        parse_int_col("LN_TERM_MOS").alias("term_months"),
        parse_amount_col("LN_PMT_AMT", 10, 2).alias("monthly_payment"),
        parse_date_col("LN_ORIG_DT").alias("origination_date"),
        parse_date_col("LN_MAT_DT").alias("maturity_date"),
        parse_date_col("LN_1ST_PMT_DT").alias("first_payment_date"),
        parse_date_col("LN_NXT_PMT_DT").alias("next_payment_date"),
        expand_status_col("LN_STAT_CD", LOAN_STATUS_MAP).alias("status"),
        parse_int_col("LN_DLQ_DAYS").alias("delinquency_days"),
        parse_amount_col("LN_ESCROW_BAL", 10, 2).alias("escrow_balance"),
        parse_amount_col("LN_LTV_PCT", 5, 2).alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        prop_type_expr.alias("property_type"),
        parse_amount_col("PROP_APRS_VAL").alias("appraised_value"),
        parse_timestamp_col("LN_CRET_DT").alias("created_at"),
        parse_timestamp_col("LN_UPDT_DT").alias("updated_at"),
        F.lit("CDW_LN_ACCT").alias("_migration_source"),
        F.lit(run_ts).cast("timestamp").alias("_migrated_at"),
    )

    # Derive partition column
    transformed = transformed.withColumn(
        "origination_year", F.year(F.col("origination_date"))
    )

    # Resolve borrower FK
    transformed = transformed.join(
        borrower_lookup, on="_borr_external_id", how="left"
    )

    # Resolve product FK
    transformed = transformed.join(
        product_lookup, on="_prod_code", how="left"
    )

    # Drop join keys
    transformed = transformed.drop("_borr_external_id", "_prod_code")

    # Validate required fields and FK resolution
    required_cols = ["account_number", "borrower_id", "product_id", "original_amount", "current_balance"]
    error_condition = F.lit(False)
    for col_name in required_cols:
        error_condition = error_condition | F.col(col_name).isNull()

    error_df = transformed.filter(error_condition).withColumn(
        "_error_reason",
        F.concat_ws(
            "; ",
            *[F.when(F.col(c).isNull(), F.lit(f"{c} is NULL")) for c in required_cols],
        ),
    )
    good_df = transformed.filter(~error_condition)

    return good_df, error_df


def write_target(df: DataFrame, table: str) -> None:
    df.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(table)


def write_errors(df: DataFrame, path: str) -> None:
    if df.count() > 0:
        df.write.format("delta").mode("append").save(path)
        logger.warning("Wrote %d error records to %s", df.count(), path)
    else:
        logger.info("No error records to write.")


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_ACCT -> loan_accounts")
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--target-table", default="loan_warehouse.loan_accounts")
    parser.add_argument("--borrower-table", default="loan_warehouse.borrowers")
    parser.add_argument("--product-table", default="loan_warehouse.loan_products")
    parser.add_argument("--error-path", default="/mnt/migration/errors/loan_accounts")
    opts = parser.parse_args(args)

    spark = SparkSession.builder.appName("Ingest_LoanAccounts").getOrCreate()

    logger.info("Reading legacy loan accounts from %s (%s)", opts.source_path, opts.source_format)
    source_df = read_source(spark, opts.source_path, opts.source_format)
    source_count = source_df.count()
    logger.info("Source row count: %d", source_count)

    borrower_lookup = resolve_borrower_fk(spark, opts.borrower_table)
    product_lookup = resolve_product_fk(spark, opts.product_table)

    good_df, error_df = transform(source_df, borrower_lookup, product_lookup)
    good_count = good_df.count()
    error_count = error_df.count()
    logger.info("Transformed: %d good, %d errors", good_count, error_count)

    write_target(good_df, opts.target_table)
    write_errors(error_df, opts.error_path)

    logger.info(
        "Loan accounts ingestion complete. Source=%d, Loaded=%d, Errors=%d",
        source_count,
        good_count,
        error_count,
    )

    if source_count != good_count + error_count:
        logger.error(
            "ROW COUNT MISMATCH: source=%d != good(%d) + error(%d)",
            source_count,
            good_count,
            error_count,
        )
        sys.exit(1)

    spark.stop()


if __name__ == "__main__":
    main()
