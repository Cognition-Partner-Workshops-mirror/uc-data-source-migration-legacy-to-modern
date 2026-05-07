"""
Ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy loan accounts table (simulated as CSV/Parquet),
strips denormalized borrower fields, applies type conversions and status
expansion, derives the origination_year partition column, and writes to
Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from databricks.ingestion.transforms import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_status,
    quarantine_nulls,
    log_row_counts,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    logger,
)

TARGET_TABLE = "loan_warehouse.loan_accounts"
SOURCE_TABLE = "CDW_LN_ACCT"
REQUIRED_COLS = [
    "account_number", "borrower_external_id", "product_code",
    "original_amount", "current_balance", "interest_rate",
    "term_months", "monthly_payment", "origination_date", "maturity_date",
]


def read_source(spark: SparkSession, source_path: str, source_format: str = "csv") -> DataFrame:
    """Read legacy loan account data from CSV or Parquet source files."""
    if source_format == "csv":
        df = (
            spark.read.format("csv")
            .option("header", "true")
            .option("inferSchema", "false")
            .load(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from %s (%s)", df.count(), source_path, source_format)
    return df


def transform(df: DataFrame) -> DataFrame:
    """Transform legacy loan account data to modern schema.

    Key transformations:
        - Drop denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
        - Retain BORR_ID as borrower_external_id for FK join
        - Parse all date strings from MM/DD/YYYY to DateType / TimestampType
        - Parse amount strings (with commas) to DecimalType
        - Parse interest rate, term, delinquency days, LTV to numeric types
        - Expand loan status codes (ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE)
        - Expand property type codes (SFR->Single Family, etc.)
        - Derive origination_year partition column from origination_date
    """
    # Rename and keep only needed columns
    df = (
        df.withColumnRenamed("LN_ACCT_NBR", "account_number")
        .withColumnRenamed("BORR_ID", "borrower_external_id")
        .withColumnRenamed("PROD_CD", "product_code")
    )

    # Drop denormalized borrower fields
    cols_to_drop = ["BORR_FST_NM", "BORR_LST_NM", "BORR_SSN_LST4"]
    for col_name in cols_to_drop:
        if col_name in df.columns:
            df = df.drop(col_name)

    # Parse amount fields
    df = parse_amount_col(df, "LN_ORIG_AMT", "original_amount")
    df = parse_amount_col(df, "LN_CURR_BAL", "current_balance")
    df = parse_amount_col(df, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    df = parse_amount_col(df, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
    df = parse_amount_col(df, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
    df = parse_amount_col(df, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)
    df = parse_amount_col(df, "PROP_APRS_VAL", "appraised_value")

    # Parse integer fields
    df = parse_int_col(df, "LN_TERM_MOS", "term_months")
    df = parse_int_col(df, "LN_DLQ_DAYS", "delinquency_days")

    # Parse date fields
    df = parse_date_col(df, "LN_ORIG_DT", "origination_date")
    df = parse_date_col(df, "LN_MAT_DT", "maturity_date")
    df = parse_date_col(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date_col(df, "LN_NXT_PMT_DT", "next_payment_date")
    df = parse_timestamp_col(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "LN_UPDT_DT", "updated_at")

    # Expand status codes
    df = expand_status(df, "LN_STAT_CD", "status", LOAN_STATUS_MAP, default="ACTIVE")

    # Expand property type codes
    df = expand_status(df, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)

    # Rename property address columns
    df = (
        df.withColumnRenamed("PROP_ADDR_LN1", "property_address")
        .withColumnRenamed("PROP_CTY_NM", "property_city")
        .withColumnRenamed("PROP_ST_CD", "property_state")
        .withColumnRenamed("PROP_ZIP_CD", "property_zip")
    )

    # Derive partition column
    df = df.withColumn("origination_year", F.year(F.col("origination_date")))

    # Add migration metadata
    df = df.withColumn("_migration_source", F.lit(SOURCE_TABLE))
    df = df.withColumn("_migrated_at", F.current_timestamp())

    # Select final columns
    df = df.select(
        "account_number", "borrower_external_id", "product_code",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment",
        "origination_date", "maturity_date",
        "first_payment_date", "next_payment_date",
        "status", "delinquency_days", "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state", "property_zip",
        "property_type", "appraised_value",
        "created_at", "updated_at",
        "origination_year",
        "_migration_source", "_migrated_at",
    )

    return df


def load(df: DataFrame, mode: str = "overwrite"):
    """Write transformed loan account DataFrame to Delta Lake."""
    df.write.format("delta").mode(mode).partitionBy("origination_year").saveAsTable(TARGET_TABLE)
    logger.info("Wrote %d rows to %s", df.count(), TARGET_TABLE)


def run(spark: SparkSession, source_path: str, source_format: str = "csv",
        write_mode: str = "overwrite"):
    """Execute the full loan account ingestion pipeline.

    Returns:
        Tuple of (valid_df, quarantine_df).
    """
    logger.info("=== Starting loan account ingestion from %s ===", source_path)

    raw_df = read_source(spark, source_path, source_format)
    transformed_df = transform(raw_df)

    valid_df, quarantine_df = quarantine_nulls(transformed_df, REQUIRED_COLS, TARGET_TABLE)
    src_count, tgt_count = log_row_counts(raw_df, valid_df, TARGET_TABLE)

    load(valid_df, mode=write_mode)

    logger.info("=== Loan account ingestion complete: %d/%d rows loaded ===", tgt_count, src_count)
    return valid_df, quarantine_df
