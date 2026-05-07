"""
Ingest CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy loan accounts table, applies all transformations
(type parsing, status expansion, property type expansion), resolves
foreign keys to borrowers and loan_products, strips denormalized
borrower columns, and writes to the modern Delta Lake table.

Usage:
    from ingestion.ingest_loan_accounts import run
    report_df = run(spark, source_path="...", source_format="csv")
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from transform_utils import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    collect_bad_value_report,
    drop_flag_columns,
    expand_status_col,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
)

TARGET_TABLE = "loan_warehouse.loan_accounts"
SOURCE_TABLE = "CDW_LN_ACCT"


def read_source(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
) -> DataFrame:
    reader = spark.read.format(source_format)
    if source_format == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(source_path)


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    # --- direct renames ---
    df = (
        df.withColumnRenamed("LN_ACCT_NBR", "account_number")
        .withColumnRenamed("PROP_ADDR_LN1", "property_address")
        .withColumnRenamed("PROP_CTY_NM", "property_city")
        .withColumnRenamed("PROP_ST_CD", "property_state")
        .withColumnRenamed("PROP_ZIP_CD", "property_zip")
    )

    # --- amount conversions ---
    df = parse_amount_col(df, "LN_ORIG_AMT", "original_amount")
    df = parse_amount_col(df, "LN_CURR_BAL", "current_balance")
    df = parse_amount_col(df, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    df = parse_amount_col(df, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
    df = parse_amount_col(df, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
    df = parse_amount_col(df, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)
    df = parse_amount_col(df, "PROP_APRS_VAL", "appraised_value")

    # --- integer conversions ---
    df = parse_int_col(df, "LN_TERM_MOS", "term_months")
    df = parse_int_col(df, "LN_DLQ_DAYS", "delinquency_days")

    # --- date conversions ---
    df = parse_date_col(df, "LN_ORIG_DT", "origination_date")
    df = parse_date_col(df, "LN_MAT_DT", "maturity_date")
    df = parse_date_col(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date_col(df, "LN_NXT_PMT_DT", "next_payment_date")
    df = parse_timestamp_col(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "LN_UPDT_DT", "updated_at")

    # --- status expansion ---
    df = expand_status_col(df, "LN_STAT_CD", "status", LOAN_STATUS_MAP)

    # --- property type expansion ---
    df = expand_status_col(df, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)

    # --- FK resolution: borrower_id ---
    borrowers = spark.table("loan_warehouse.borrowers").select(
        F.col("borrower_id"), F.col("external_id"),
    )
    df = df.join(
        borrowers,
        df["BORR_ID"] == borrowers["external_id"],
        "left",
    )
    unmatched_borrowers = df.filter(F.col("borrower_id").isNull()).count()
    if unmatched_borrowers > 0:
        print(
            f"[{SOURCE_TABLE}] WARNING: {unmatched_borrowers} rows have no "
            f"matching borrower (BORR_ID not found in borrowers.external_id)"
        )
    df = df.drop("external_id")

    # --- FK resolution: product_id ---
    products = spark.table("loan_warehouse.loan_products").select(
        F.col("product_id"), F.col("code"),
    )
    df = df.join(
        products,
        df["PROD_CD"] == products["code"],
        "left",
    )
    unmatched_products = df.filter(F.col("product_id").isNull()).count()
    if unmatched_products > 0:
        print(
            f"[{SOURCE_TABLE}] WARNING: {unmatched_products} rows have no "
            f"matching product (PROD_CD not found in loan_products.code)"
        )
    df = df.drop("code")

    # --- drop legacy columns ---
    legacy_cols = [
        "BORR_ID", "BORR_FST_NM", "BORR_LST_NM", "BORR_SSN_LST4",
        "PROD_CD",
        "LN_ORIG_AMT", "LN_CURR_BAL", "LN_INT_RT", "LN_TERM_MOS",
        "LN_PMT_AMT", "LN_ORIG_DT", "LN_MAT_DT", "LN_1ST_PMT_DT",
        "LN_NXT_PMT_DT", "LN_STAT_CD", "LN_DLQ_DAYS", "LN_ESCROW_BAL",
        "LN_LTV_PCT", "PROP_TYP_CD", "PROP_APRS_VAL",
        "LN_CRET_DT", "LN_UPDT_DT",
    ]
    df = df.drop(*legacy_cols)

    # --- lineage ---
    df = df.withColumn("_migration_source", F.lit(SOURCE_TABLE))
    df = df.withColumn("_migrated_at", F.current_timestamp())

    return df


def run(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
    write_mode: str = "overwrite",
) -> DataFrame:
    raw_df = read_source(spark, source_path, source_format)
    source_count = raw_df.count()
    print(f"[{SOURCE_TABLE}] Source row count: {source_count}")

    transformed_df = transform(raw_df, spark)

    bad_report = collect_bad_value_report(transformed_df, SOURCE_TABLE)
    bad_count = bad_report.count()
    if bad_count > 0:
        print(f"[{SOURCE_TABLE}] WARNING: {bad_count} parse issues detected")
        bad_report.show(truncate=False)

    clean_df = drop_flag_columns(transformed_df)

    final_df = clean_df.select(
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment",
        "origination_date", "maturity_date",
        "first_payment_date", "next_payment_date",
        "status", "delinquency_days", "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state",
        "property_zip", "property_type", "appraised_value",
        "created_at", "updated_at",
        "_migration_source", "_migrated_at",
    )

    final_df.write.format("delta").mode(write_mode).partitionBy("status").saveAsTable(TARGET_TABLE)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[{SOURCE_TABLE}] Target row count: {target_count}")

    if source_count != target_count:
        print(
            f"[{SOURCE_TABLE}] ERROR: Row count mismatch! "
            f"source={source_count}, target={target_count}"
        )

    return bad_report
