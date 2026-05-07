"""
Ingestion script for CDW_LN_ACCT -> loan_warehouse.loan_accounts
Transforms legacy loan account records with:
- Denormalized borrower fields dropped (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
- Amount string parsing (comma-separated -> DecimalType)
- Date string parsing (MM/DD/YYYY -> DateType/TimestampType)
- Status code expansion (ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE)
- Property type expansion (SFR->Single Family, CND->Condominium, etc.)
- Interest rate and LTV parsing to decimal
"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, trim, current_timestamp, lit, regexp_replace
from pyspark.sql.types import DecimalType

from common import (
    get_spark,
    MigrationConfig,
    read_source_data,
    parse_date_string,
    parse_timestamp_string,
    parse_amount_string,
    parse_integer_string,
    expand_status_code,
    log_malformed_records,
    write_to_delta,
    logger,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)


def transform_loan_accounts(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Transform legacy CDW_LN_ACCT data to modern loan_accounts schema.
    Drops denormalized borrower fields and normalizes via FK reference.

    Returns:
        Tuple of (valid_records_df, malformed_records_df)
    """
    logger.info("Starting loan account transformation")
    logger.info("Dropping denormalized borrower fields: BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4")

    # Select relevant columns, dropping denormalized borrower fields
    transformed = df.select(
        trim(col("LN_ACCT_NBR")).alias("account_number"),
        trim(col("BORR_ID")).alias("borrower_id"),
        trim(col("PROD_CD")).alias("product_code"),
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
        trim(col("PROP_ADDR_LN1")).alias("property_address"),
        trim(col("PROP_CTY_NM")).alias("property_city"),
        trim(col("PROP_ST_CD")).alias("property_state"),
        trim(col("PROP_ZIP_CD")).alias("property_zip"),
        col("PROP_TYP_CD"),
        col("PROP_APRS_VAL"),
        col("LN_CRET_DT"),
        col("LN_UPDT_DT"),
    )

    # Parse amount fields
    transformed = parse_amount_string(transformed, "LN_ORIG_AMT", "original_amount")
    transformed = parse_amount_string(transformed, "LN_CURR_BAL", "current_balance")
    transformed = parse_amount_string(transformed, "LN_PMT_AMT", "monthly_payment", 10, 2)
    transformed = parse_amount_string(transformed, "LN_ESCROW_BAL", "escrow_balance", 10, 2)
    transformed = parse_amount_string(transformed, "PROP_APRS_VAL", "appraised_value")

    # Parse interest rate (no commas, just cast)
    transformed = transformed.withColumn(
        "interest_rate",
        regexp_replace(col("LN_INT_RT"), ",", "").cast(DecimalType(5, 3))
    )

    # Parse LTV percent
    transformed = transformed.withColumn(
        "ltv_percent",
        regexp_replace(col("LN_LTV_PCT"), ",", "").cast(DecimalType(5, 2))
    )

    # Parse integer fields
    transformed = parse_integer_string(transformed, "LN_TERM_MOS", "term_months")
    transformed = parse_integer_string(transformed, "LN_DLQ_DAYS", "delinquency_days")

    # Parse date fields
    transformed = parse_date_string(transformed, "LN_ORIG_DT", "origination_date")
    transformed = parse_date_string(transformed, "LN_MAT_DT", "maturity_date")
    transformed = parse_date_string(transformed, "LN_1ST_PMT_DT", "first_payment_date")
    transformed = parse_date_string(transformed, "LN_NXT_PMT_DT", "next_payment_date")

    # Parse timestamp fields
    transformed = parse_timestamp_string(transformed, "LN_CRET_DT", "created_at")
    transformed = parse_timestamp_string(transformed, "LN_UPDT_DT", "updated_at")

    # Expand status codes
    transformed = expand_status_code(transformed, "LN_STAT_CD", "status", LOAN_STATUS_MAP)

    # Expand property type codes
    transformed = expand_status_code(transformed, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)

    # Add metadata
    transformed = (
        transformed
        .withColumn("_ingestion_ts", current_timestamp())
        .withColumn("_source_system", lit("CDW_LEGACY"))
    )

    # Select final columns
    final = transformed.select(
        "account_number", "borrower_id", "product_code",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date",
        "maturity_date", "first_payment_date", "next_payment_date",
        "status", "delinquency_days", "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state",
        "property_zip", "property_type", "appraised_value",
        "created_at", "updated_at", "_ingestion_ts", "_source_system"
    )

    # Identify malformed records (missing required fields)
    malformed = final.filter(
        col("account_number").isNull()
        | col("borrower_id").isNull()
        | col("product_code").isNull()
        | col("status").isNull()
    )

    valid = final.filter(
        col("account_number").isNotNull()
        & col("borrower_id").isNotNull()
        & col("product_code").isNotNull()
        & col("status").isNotNull()
    )

    logger.info(
        f"Loan account transformation complete: {valid.count()} valid, "
        f"{malformed.count()} malformed"
    )
    return valid, malformed


def run(config: MigrationConfig = None):
    """Execute the loan account ingestion pipeline."""
    if config is None:
        config = MigrationConfig()

    spark = get_spark()
    logger.info("=" * 60)
    logger.info("STARTING: Loan Account Ingestion (CDW_LN_ACCT -> loan_accounts)")
    logger.info("=" * 60)

    # Read source data
    source_df = read_source_data(spark, config, "CDW_LN_ACCT")

    # Transform
    valid_df, malformed_df = transform_loan_accounts(source_df)

    # Log malformed records
    log_malformed_records(source_df, malformed_df, "CDW_LN_ACCT", spark, config)

    # Write to Delta Lake
    write_to_delta(valid_df, "loan_accounts")

    logger.info("COMPLETED: Loan Account Ingestion")
    return valid_df


if __name__ == "__main__":
    run()
