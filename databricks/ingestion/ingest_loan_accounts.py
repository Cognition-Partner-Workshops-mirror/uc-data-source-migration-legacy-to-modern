"""
Ingestion script: CDW_LN_ACCT → loan_accounts (Delta Lake)

Reads legacy loan account data, strips denormalized borrower fields,
applies transformations per column_mappings.md, resolves foreign keys,
and writes to the modern loan_accounts Delta table.
"""

from pyspark.sql.functions import col, monotonically_increasing_id

from common import (
    get_spark,
    logger,
    parse_date_column,
    parse_timestamp_column,
    parse_amount_column,
    parse_integer_column,
    expand_status_code,
    log_record_counts,
    log_null_counts,
    write_delta,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    CATALOG,
    SCHEMA,
)


def read_legacy_loan_accounts(spark, source_path: str):
    """Read legacy CDW_LN_ACCT data from CSV or Parquet."""
    if source_path.endswith(".parquet"):
        df = spark.read.parquet(source_path)
    else:
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .csv(source_path)
        )
    logger.info(f"Read source file: {source_path}")
    return df


def resolve_borrower_ids(spark, df):
    """
    Resolve BORR_ID to the modern borrowers.id via lookup.
    Records with unresolved borrower IDs are logged but retained with null borrower_id.
    """
    borrowers_df = spark.table(f"{CATALOG}.{SCHEMA}.borrowers").select(
        col("id").alias("borrower_id"),
        col("external_id"),
    )

    joined = df.join(borrowers_df, df["BORR_ID"] == borrowers_df["external_id"], "left")

    unresolved_count = joined.filter(col("borrower_id").isNull()).count()
    if unresolved_count > 0:
        logger.warning(
            f"[loan_accounts] {unresolved_count} records have unresolved borrower IDs"
        )

    return joined.drop("external_id")


def resolve_product_ids(spark, df):
    """
    Resolve PROD_CD to the modern loan_products.id via lookup.
    Records with unresolved product codes are logged but retained with null product_id.
    """
    products_df = spark.table(f"{CATALOG}.{SCHEMA}.loan_products").select(
        col("id").alias("product_id"),
        col("code").alias("product_code"),
    )

    joined = df.join(products_df, df["PROD_CD"] == products_df["product_code"], "left")

    unresolved_count = joined.filter(col("product_id").isNull()).count()
    if unresolved_count > 0:
        logger.warning(
            f"[loan_accounts] {unresolved_count} records have unresolved product codes"
        )

    return joined.drop("product_code")


def transform_loan_accounts(spark, df):
    """Apply transformations for loan accounts."""
    source_count = log_record_counts(df, "loan_accounts", "source")

    log_null_counts(df, "loan_accounts", ["LN_ACCT_NBR", "BORR_ID", "PROD_CD", "LN_ORIG_AMT"])

    # Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
    result = df.select(
        col("LN_ACCT_NBR").alias("account_number"),
        col("BORR_ID"),
        col("PROD_CD"),
        col("LN_ORIG_AMT"),
        col("LN_CURR_BAL"),
        col("LN_INT_RT"),
        col("LN_TERM_MOS"),
        col("LN_PMT_AMT"),
        col("LN_ORIG_DT"),
        col("LN_MAT_DT"),
        col("LN_1ST_PMT_DT"),
        col("LN_NXT_PMT_DT"),
        col("LN_STAT_CD"),
        col("LN_DLQ_DAYS"),
        col("LN_ESCROW_BAL"),
        col("LN_LTV_PCT"),
        col("PROP_ADDR_LN1").alias("property_address"),
        col("PROP_CTY_NM").alias("property_city"),
        col("PROP_ST_CD").alias("property_state"),
        col("PROP_ZIP_CD").alias("property_zip"),
        col("PROP_TYP_CD"),
        col("PROP_APRS_VAL"),
        col("LN_CRET_DT"),
        col("LN_UPDT_DT"),
    )

    # Resolve foreign keys
    result = resolve_borrower_ids(spark, result)
    result = resolve_product_ids(spark, result)
    result = result.drop("BORR_ID", "PROD_CD")

    # Parse amount columns
    result = parse_amount_column(result, "LN_ORIG_AMT", "original_amount")
    result = result.drop("LN_ORIG_AMT")
    result = parse_amount_column(result, "LN_CURR_BAL", "current_balance")
    result = result.drop("LN_CURR_BAL")
    result = parse_amount_column(result, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    result = result.drop("LN_INT_RT")
    result = parse_amount_column(result, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
    result = result.drop("LN_PMT_AMT")
    result = parse_amount_column(result, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
    result = result.drop("LN_ESCROW_BAL")
    result = parse_amount_column(result, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)
    result = result.drop("LN_LTV_PCT")
    result = parse_amount_column(result, "PROP_APRS_VAL", "appraised_value")
    result = result.drop("PROP_APRS_VAL")

    # Parse integer columns
    result = parse_integer_column(result, "LN_TERM_MOS", "term_months")
    result = result.drop("LN_TERM_MOS")
    result = parse_integer_column(result, "LN_DLQ_DAYS", "delinquency_days")
    result = result.drop("LN_DLQ_DAYS")

    # Parse date columns
    result = parse_date_column(result, "LN_ORIG_DT", "origination_date")
    result = result.drop("LN_ORIG_DT")
    result = parse_date_column(result, "LN_MAT_DT", "maturity_date")
    result = result.drop("LN_MAT_DT")
    result = parse_date_column(result, "LN_1ST_PMT_DT", "first_payment_date")
    result = result.drop("LN_1ST_PMT_DT")
    result = parse_date_column(result, "LN_NXT_PMT_DT", "next_payment_date")
    result = result.drop("LN_NXT_PMT_DT")

    # Parse timestamps
    result = parse_timestamp_column(result, "LN_CRET_DT", "created_at")
    result = result.drop("LN_CRET_DT")
    result = parse_timestamp_column(result, "LN_UPDT_DT", "updated_at")
    result = result.drop("LN_UPDT_DT")

    # Expand status codes
    result = expand_status_code(result, "LN_STAT_CD", "status", LOAN_STATUS_MAP)
    result = result.drop("LN_STAT_CD")

    # Expand property type codes
    result = expand_status_code(result, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)
    result = result.drop("PROP_TYP_CD")

    # Add surrogate key
    result = result.withColumn("id", monotonically_increasing_id())

    target_count = log_record_counts(result, "loan_accounts", "transformed")

    if source_count != target_count:
        logger.error(
            f"[loan_accounts] Record count mismatch! Source={source_count}, Target={target_count}"
        )

    return result


def run(source_path: str):
    """Main entry point for loan account ingestion."""
    spark = get_spark()
    logger.info("=== Starting Loan Account Ingestion ===")

    raw_df = read_legacy_loan_accounts(spark, source_path)
    transformed_df = transform_loan_accounts(spark, raw_df)
    write_delta(transformed_df, "loan_accounts", partition_cols=["status"])

    logger.info("=== Loan Account Ingestion Complete ===")
    return transformed_df


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: spark-submit ingest_loan_accounts.py <source_path>")
        sys.exit(1)
    run(sys.argv[1])
