"""
Ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy loan accounts table (simulated as CSV/Parquet source)
and transforms it into the modern loan_accounts Delta Lake table.

Key transformations:
  - Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
    and resolve borrower_id FK via BORR_ID -> borrowers.external_id lookup
  - Resolve product_id FK via PROD_CD -> loan_products.code lookup
  - Parse all amount strings (comma-formatted) to DECIMAL
  - Parse all date strings (MM/DD/YYYY) to DATE / TIMESTAMP
  - Expand loan status codes: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance
  - Expand property type codes: SFR->Single Family, CND->Condominium, etc.
  - Derive origination_year partition column from origination_date
  - Add surrogate loan_account_id and ingestion metadata
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
import logging

from transformations import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_status_col,
    add_ingestion_metadata,
    log_bad_records,
    drop_flag_columns,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

logger = logging.getLogger("cdw_migration.ingest_loan_accounts")

DEFAULT_SOURCE_PATH = "/mnt/landing/cdw/CDW_LN_ACCT"
DEFAULT_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"


def read_source(spark: SparkSession, source_path: str = DEFAULT_SOURCE_PATH,
                source_format: str = DEFAULT_SOURCE_FORMAT) -> DataFrame:
    """Read legacy CDW_LN_ACCT data from the landing zone."""
    if source_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "")
            .option("emptyValue", "")
            .csv(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from %s (%s)", df.count(), source_path, source_format)
    return df


def resolve_borrower_fk(df: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Resolve the borrower foreign key by looking up borrower_id from
    loan_warehouse.borrowers using the legacy BORR_ID -> external_id mapping.

    Records that cannot be resolved will have borrower_id set to NULL and
    are flagged with '_unresolved_borrower_id' for investigation.
    """
    borrowers_df = spark.table("loan_warehouse.borrowers").select(
        F.col("borrower_id").alias("_resolved_borrower_id"),
        F.col("external_id").alias("_borr_external_id"),
    )
    df = df.join(
        borrowers_df,
        df["BORR_ID"] == borrowers_df["_borr_external_id"],
        "left"
    )
    # Flag unresolved FK references (source BORR_ID not found in borrowers)
    df = df.withColumn(
        "_unresolved_borrower_id",
        F.when(F.col("_resolved_borrower_id").isNull() & F.col("BORR_ID").isNotNull(),
               F.lit(True)).otherwise(F.lit(False))
    )
    df = df.withColumn("borrower_id", F.col("_resolved_borrower_id"))
    # Clean up join helper columns
    df = df.drop("_resolved_borrower_id", "_borr_external_id")
    return df


def resolve_product_fk(df: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Resolve the product foreign key by looking up product_id from
    loan_warehouse.loan_products using the legacy PROD_CD -> code mapping.

    Records that cannot be resolved will have product_id set to NULL
    and are flagged with '_unresolved_product_id'.
    """
    products_df = spark.table("loan_warehouse.loan_products").select(
        F.col("product_id").alias("_resolved_product_id"),
        F.col("code").alias("_prod_code"),
    )
    df = df.join(
        products_df,
        df["PROD_CD"] == products_df["_prod_code"],
        "left"
    )
    # Flag unresolved FK references
    df = df.withColumn(
        "_unresolved_product_id",
        F.when(F.col("_resolved_product_id").isNull() & F.col("PROD_CD").isNotNull(),
               F.lit(True)).otherwise(F.lit(False))
    )
    df = df.withColumn("product_id", F.col("_resolved_product_id"))
    # Clean up join helper columns
    df = df.drop("_resolved_product_id", "_prod_code")
    return df


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Apply all transformations to convert legacy CDW_LN_ACCT columns
    to the modern loan_accounts schema.
    """
    # --- Generate surrogate key ---
    df = df.withColumn("loan_account_id", F.monotonically_increasing_id() + 1)

    # --- Rename natural key column ---
    df = df.withColumnRenamed("LN_ACCT_NBR", "account_number")

    # --- Resolve foreign keys from dimension tables ---
    df = resolve_borrower_fk(df, spark)
    df = resolve_product_fk(df, spark)

    # --- Parse financial amounts: comma-formatted strings -> DECIMAL ---
    df = parse_amount_col(df, "LN_ORIG_AMT", "original_amount", precision=12, scale=2)
    df = parse_amount_col(df, "LN_CURR_BAL", "current_balance", precision=12, scale=2)
    df = parse_amount_col(df, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    df = parse_amount_col(df, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
    df = parse_amount_col(df, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
    df = parse_amount_col(df, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)
    df = parse_amount_col(df, "PROP_APRS_VAL", "appraised_value", precision=12, scale=2)

    # --- Parse term months: string -> INT ---
    df = parse_int_col(df, "LN_TERM_MOS", "term_months")

    # --- Parse delinquency days: string -> INT ---
    df = parse_int_col(df, "LN_DLQ_DAYS", "delinquency_days")

    # --- Parse loan dates: MM/DD/YYYY -> DATE ---
    df = parse_date_col(df, "LN_ORIG_DT", "origination_date")
    df = parse_date_col(df, "LN_MAT_DT", "maturity_date")
    df = parse_date_col(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date_col(df, "LN_NXT_PMT_DT", "next_payment_date")

    # --- Parse audit timestamps: MM/DD/YYYY -> TIMESTAMP ---
    df = parse_timestamp_col(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "LN_UPDT_DT", "updated_at")

    # --- Expand loan status codes ---
    # ACT -> Active, CLO -> Closed, DFT -> Default, FRB -> Forbearance
    df = expand_status_col(df, "LN_STAT_CD", "status", LOAN_STATUS_MAP)

    # --- Expand property type codes ---
    # SFR -> Single Family, CND -> Condominium, MFR -> Multi-Family, TWN -> Townhouse
    df = expand_status_col(df, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)

    # --- Direct copy property address columns ---
    df = (
        df
        .withColumnRenamed("PROP_ADDR_LN1", "property_address")
        .withColumnRenamed("PROP_CTY_NM", "property_city")
        .withColumnRenamed("PROP_ST_CD", "property_state")
        .withColumnRenamed("PROP_ZIP_CD", "property_zip")
    )

    # --- Derive partition column: origination_year from origination_date ---
    df = df.withColumn("origination_year", F.year(F.col("origination_date")))

    # --- Add ingestion metadata ---
    df = add_ingestion_metadata(df, "CDW_LN_ACCT")

    # --- Log data quality issues (includes unresolved FK flags) ---
    log_bad_records(df, TARGET_TABLE)

    # Log unresolved FK counts separately for clarity
    unresolved_borrowers = df.filter(F.col("_unresolved_borrower_id") == True).count()  # noqa: E712
    unresolved_products = df.filter(F.col("_unresolved_product_id") == True).count()  # noqa: E712
    if unresolved_borrowers > 0:
        logger.warning("[%s] %d records with unresolved borrower FK", TARGET_TABLE, unresolved_borrowers)
    if unresolved_products > 0:
        logger.warning("[%s] %d records with unresolved product FK", TARGET_TABLE, unresolved_products)

    # --- Drop flag columns and legacy source columns ---
    df = drop_flag_columns(df)
    df = df.drop("_unresolved_borrower_id", "_unresolved_product_id")

    # Select only the target columns in the correct order
    target_columns = [
        "loan_account_id", "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate", "term_months",
        "monthly_payment", "origination_date", "maturity_date",
        "first_payment_date", "next_payment_date", "status",
        "delinquency_days", "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state",
        "property_zip", "property_type", "appraised_value",
        "created_at", "updated_at", "_ingestion_ts", "_source_system",
        # Partition columns
        "origination_year",
    ]
    df = df.select(*target_columns)

    return df


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    """Write the transformed loan_accounts DataFrame to the Delta Lake table."""
    (
        df.write
        .format("delta")
        .mode(mode)
        .partitionBy("status", "origination_year")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info("Wrote %d rows to %s", df.count(), TARGET_TABLE)


def run(spark: SparkSession, source_path: str = DEFAULT_SOURCE_PATH,
        source_format: str = DEFAULT_SOURCE_FORMAT) -> DataFrame:
    """
    Execute the full loan_accounts ingestion pipeline.
    REQUIRES: borrowers and loan_products tables must be populated first.
    """
    logger.info("Starting loan_accounts ingestion from %s", source_path)
    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform(raw_df, spark)
    write_target(transformed_df)
    logger.info("Loan accounts ingestion complete.")
    return transformed_df


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_LoanAccounts_Ingestion").getOrCreate()
    try:
        src_path = dbutils.widgets.get("source_path")  # noqa: F821
    except Exception:
        src_path = DEFAULT_SOURCE_PATH
    try:
        src_fmt = dbutils.widgets.get("source_format")  # noqa: F821
    except Exception:
        src_fmt = DEFAULT_SOURCE_FORMAT

    run(spark, src_path, src_fmt)
