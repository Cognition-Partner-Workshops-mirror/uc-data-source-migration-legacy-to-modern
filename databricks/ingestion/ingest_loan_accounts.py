"""
Ingest legacy CDW_LN_ACCT into Delta Lake loan_accounts table.

Source : CSV/Parquet export of CDW_LN_ACCT
Target : loan_warehouse.loan_accounts (Delta Lake)

Key transformations:
  - Drop denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  - Resolve BORR_ID -> borrower_key via lookup against borrowers table
  - Resolve PROD_CD -> product_key via lookup against loan_products table
  - Parse all amount strings (LN_ORIG_AMT, LN_CURR_BAL, etc.) -> DECIMAL
  - Parse date strings -> DATE
  - Expand LN_STAT_CD (ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE)
  - Expand PROP_TYP_CD (SFR->Single Family, CND->Condominium, etc.)
  - Derive origination_year partition column from origination_date
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from .transforms import (
    parse_date,
    parse_timestamp,
    parse_amount,
    parse_int,
    expand_status,
    add_ingestion_timestamp,
    log_malformed_rows,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

REQUIRED_COLS = [
    "account_number",
    "borrower_key",
    "product_key",
    "original_amount",
    "current_balance",
    "interest_rate",
    "term_months",
    "monthly_payment",
    "origination_date",
    "maturity_date",
]


def read_source(spark: SparkSession, source_path: str, source_format: str = "csv") -> DataFrame:
    reader = spark.read.format(source_format)
    if source_format == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(source_path)


def transform(
    df: DataFrame,
    borrowers_df: DataFrame,
    products_df: DataFrame,
) -> DataFrame:
    """
    Transform CDW_LN_ACCT and resolve foreign keys.

    Parameters:
        df           : Raw CDW_LN_ACCT DataFrame
        borrowers_df : The borrowers Delta table (must have external_id, borrower_key)
        products_df  : The loan_products Delta table (must have code, product_key)
    """
    # Resolve borrower FK
    borrower_lookup = borrowers_df.select(
        F.col("external_id").alias("_borr_ext_id"),
        F.col("borrower_key"),
    )

    # Resolve product FK
    product_lookup = products_df.select(
        F.col("code").alias("_prod_cd"),
        F.col("product_key"),
    )

    transformed = (
        df
        .select(
            F.trim(F.col("LN_ACCT_NBR")).alias("account_number"),
            F.trim(F.col("BORR_ID")).alias("_borr_id_lookup"),
            F.trim(F.col("PROD_CD")).alias("_prod_cd_lookup"),
            parse_amount("LN_ORIG_AMT").alias("original_amount"),
            parse_amount("LN_CURR_BAL").alias("current_balance"),
            parse_amount("LN_INT_RT", 5, 3).alias("interest_rate"),
            parse_int("LN_TERM_MOS").alias("term_months"),
            parse_amount("LN_PMT_AMT", 10, 2).alias("monthly_payment"),
            parse_date("LN_ORIG_DT").alias("origination_date"),
            parse_date("LN_MAT_DT").alias("maturity_date"),
            parse_date("LN_1ST_PMT_DT").alias("first_payment_date"),
            parse_date("LN_NXT_PMT_DT").alias("next_payment_date"),
            expand_status("LN_STAT_CD", LOAN_STATUS_MAP).alias("status"),
            parse_int("LN_DLQ_DAYS").alias("delinquency_days"),
            parse_amount("LN_ESCROW_BAL", 10, 2).alias("escrow_balance"),
            parse_amount("LN_LTV_PCT", 5, 2).alias("ltv_percent"),
            F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
            F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
            F.trim(F.col("PROP_ST_CD")).alias("property_state"),
            F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
            expand_status("PROP_TYP_CD", PROPERTY_TYPE_MAP, "Other").alias("property_type"),
            parse_amount("PROP_APRS_VAL").alias("appraised_value"),
            parse_timestamp("LN_CRET_DT").alias("created_at"),
            parse_timestamp("LN_UPDT_DT").alias("updated_at"),
        )
    )

    # Join to resolve borrower_key
    transformed = transformed.join(
        borrower_lookup,
        transformed["_borr_id_lookup"] == borrower_lookup["_borr_ext_id"],
        "left",
    ).drop("_borr_id_lookup", "_borr_ext_id")

    # Join to resolve product_key
    transformed = transformed.join(
        product_lookup,
        transformed["_prod_cd_lookup"] == product_lookup["_prod_cd"],
        "left",
    ).drop("_prod_cd_lookup", "_prod_cd")

    # Derive partition column
    transformed = transformed.withColumn(
        "origination_year", F.year(F.col("origination_date"))
    )

    return transformed


def run(
    spark: SparkSession,
    source_path: str,
    borrowers_table: str = "loan_warehouse.borrowers",
    products_table: str = "loan_warehouse.loan_products",
    target_table: str = "loan_warehouse.loan_accounts",
    error_path: str = "dbfs:/mnt/quarantine/loan_accounts/",
    source_format: str = "csv",
    write_mode: str = "append",
) -> dict:
    raw_df = read_source(spark, source_path, source_format)
    source_count = raw_df.count()
    print(f"[loan_accounts] Source rows read: {source_count}")

    # Read dimension tables for FK resolution
    borrowers_df = spark.table(borrowers_table)
    products_df = spark.table(products_table)

    transformed_df = transform(raw_df, borrowers_df, products_df)
    transformed_df = add_ingestion_timestamp(transformed_df)

    # Log unresolved FK lookups as warnings
    unresolved_borrower = transformed_df.filter(F.col("borrower_key").isNull()).count()
    unresolved_product = transformed_df.filter(F.col("product_key").isNull()).count()
    if unresolved_borrower > 0:
        print(f"[loan_accounts] WARNING: {unresolved_borrower} rows with unresolved borrower_key")
    if unresolved_product > 0:
        print(f"[loan_accounts] WARNING: {unresolved_product} rows with unresolved product_key")

    valid_df, quarantine_count = log_malformed_rows(
        transformed_df, REQUIRED_COLS, "CDW_LN_ACCT", error_path
    )
    print(f"[loan_accounts] Quarantined rows: {quarantine_count}")

    valid_count = valid_df.count()
    (
        valid_df
        .write
        .format("delta")
        .mode(write_mode)
        .partitionBy("origination_year")
        .option("mergeSchema", "true")
        .saveAsTable(target_table)
    )
    print(f"[loan_accounts] Rows written to {target_table}: {valid_count}")

    return {
        "table": target_table,
        "source_count": source_count,
        "valid_count": valid_count,
        "quarantine_count": quarantine_count,
        "unresolved_borrower_keys": unresolved_borrower,
        "unresolved_product_keys": unresolved_product,
    }
