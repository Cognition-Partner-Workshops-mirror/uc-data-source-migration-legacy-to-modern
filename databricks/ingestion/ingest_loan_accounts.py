"""
ingest_loan_accounts.py — PySpark ingestion script for the loan_accounts fact table.

Reads from the legacy CDW_LN_ACCT source (simulated as CSV/Parquet), applies
all required transformations per column_mappings.md, and writes to the Delta Lake
loan_management.loan_accounts table.

Source: CDW_LN_ACCT (legacy denormalized, all-VARCHAR loan accounts)
Target: loan_management.loan_accounts (typed, normalized Delta Lake table)

Key transformations:
  - Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) dropped
  - BORR_ID kept as borrower_external_id for FK resolution
  - PROD_CD kept as product_code for FK resolution
  - All amount VARCHARs → DECIMAL (commas stripped)
  - All date VARCHARs (MM/DD/YYYY) → DATE
  - LN_STAT_CD expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
  - PROP_TYP_CD expanded: SFR→Single Family, CND→Condominium, etc.
"""

from pyspark.sql import SparkSession, functions as F

from common_transforms import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_status_col,
    add_parse_error_flags,
    log_transformation_summary,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

# =============================================================================
# Configuration — update these paths for your Databricks environment
# =============================================================================
SOURCE_PATH = "/mnt/legacy-data/cdw_ln_acct/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_management.loan_accounts"


def read_source(spark, path=SOURCE_PATH, fmt=SOURCE_FORMAT):
    """
    Read the legacy CDW_LN_ACCT source data.
    All columns are read as strings to match the legacy all-VARCHAR schema.
    """
    if fmt == "csv":
        return (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .csv(path)
        )
    elif fmt == "parquet":
        return spark.read.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform_loan_accounts(df):
    """
    Apply all transformations to convert legacy CDW_LN_ACCT columns
    to the modern loan_accounts schema per column_mappings.md.
    Denormalized borrower columns are dropped; FK references are preserved.
    """
    # Rename direct-copy columns
    transformed = (
        df
        .withColumnRenamed("LN_ACCT_NBR", "account_number")
        # Keep BORR_ID as FK reference to borrowers table
        .withColumnRenamed("BORR_ID", "borrower_external_id")
        # Keep PROD_CD as FK reference to loan_products table
        .withColumnRenamed("PROD_CD", "product_code")
        .withColumnRenamed("PROP_ADDR_LN1", "property_address")
        .withColumnRenamed("PROP_CTY_NM", "property_city")
        .withColumnRenamed("PROP_ST_CD", "property_state")
        .withColumnRenamed("PROP_ZIP_CD", "property_zip")
    )

    # Parse all amount columns: comma-formatted VARCHARs → DECIMAL
    transformed = parse_amount_col(transformed, "LN_ORIG_AMT", "original_amount")
    transformed = parse_amount_col(transformed, "LN_CURR_BAL", "current_balance")
    transformed = parse_amount_col(
        transformed, "LN_INT_RT", "interest_rate", precision=5, scale=3
    )
    transformed = parse_amount_col(
        transformed, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2
    )
    transformed = parse_amount_col(
        transformed, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2
    )
    transformed = parse_amount_col(
        transformed, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2
    )
    transformed = parse_amount_col(transformed, "PROP_APRS_VAL", "appraised_value")

    # Parse term months and delinquency days: VARCHAR → INT
    transformed = parse_int_col(transformed, "LN_TERM_MOS", "term_months")
    transformed = parse_int_col(transformed, "LN_DLQ_DAYS", "delinquency_days")

    # Parse all date columns: MM/DD/YYYY → DATE
    transformed = parse_date_col(transformed, "LN_ORIG_DT", "origination_date")
    transformed = parse_date_col(transformed, "LN_MAT_DT", "maturity_date")
    transformed = parse_date_col(transformed, "LN_1ST_PMT_DT", "first_payment_date")
    transformed = parse_date_col(transformed, "LN_NXT_PMT_DT", "next_payment_date")

    # Parse created/updated timestamps
    transformed = parse_timestamp_col(transformed, "LN_CRET_DT", "created_at")
    transformed = parse_timestamp_col(transformed, "LN_UPDT_DT", "updated_at")

    # Expand loan status code: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
    transformed = expand_status_col(
        transformed, "LN_STAT_CD", "status", LOAN_STATUS_MAP
    )

    # Expand property type code: SFR→Single Family, CND→Condominium, etc.
    transformed = expand_status_col(
        transformed, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP
    )

    # Add parse error flags for data quality monitoring
    transformed = add_parse_error_flags(
        transformed,
        date_cols=[
            ("LN_ORIG_DT", "origination_date"),
            ("LN_MAT_DT", "maturity_date"),
            ("LN_1ST_PMT_DT", "first_payment_date"),
            ("LN_NXT_PMT_DT", "next_payment_date"),
            ("LN_CRET_DT", "created_at"),
            ("LN_UPDT_DT", "updated_at"),
        ],
        amount_cols=[
            ("LN_ORIG_AMT", "original_amount"),
            ("LN_CURR_BAL", "current_balance"),
            ("LN_INT_RT", "interest_rate"),
            ("LN_PMT_AMT", "monthly_payment"),
            ("LN_ESCROW_BAL", "escrow_balance"),
            ("LN_LTV_PCT", "ltv_percent"),
            ("PROP_APRS_VAL", "appraised_value"),
        ],
    )

    # Select only the modern schema columns; drop denormalized borrower fields
    # (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 are redundant with the borrowers table)
    result = transformed.select(
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
        "_parse_errors",
    )

    return result


def write_target(df, table=TARGET_TABLE, mode="overwrite"):
    """
    Write the transformed loan account data to the Delta Lake target table.
    Partitioned by status (configured in the DDL).
    """
    (
        df
        .drop("_parse_errors")
        .write
        .format("delta")
        .mode(mode)
        .option("partitionOverwriteMode", "dynamic")
        .saveAsTable(table)
    )


def run(spark=None):
    """
    Main entry point: read legacy loan account data, transform, validate, and write.
    Returns a summary dict with row counts for reconciliation.
    """
    if spark is None:
        spark = SparkSession.builder.appName("IngestLoanAccounts").getOrCreate()

    print("=" * 60)
    print("Starting loan account ingestion from CDW_LN_ACCT")
    print("=" * 60)

    # Step 1: Read legacy source
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"Source rows read: {source_count}")

    # Step 2: Transform to modern schema
    transformed_df = transform_loan_accounts(source_df)

    # Step 3: Log transformation summary
    total, errors = log_transformation_summary(transformed_df, "loan_accounts")

    # Step 4: Write to Delta Lake target
    write_target(transformed_df)
    print(f"Successfully wrote {total} rows to {TARGET_TABLE}")

    return {"source_count": source_count, "target_count": total, "error_count": errors}


if __name__ == "__main__":
    run()
