"""
Ingestion script for CDW_PMT_HIST -> loan_warehouse.payments
Transforms legacy payment history records with:
- Amount string parsing (comma-separated -> DecimalType)
- Date string parsing (MM/DD/YYYY -> DateType/TimestampType)
- Payment type expansion (REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT)
- Payment status expansion (PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING)
"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, trim, current_timestamp, lit

from common import (
    get_spark,
    MigrationConfig,
    read_source_data,
    parse_date_string,
    parse_timestamp_string,
    parse_amount_string,
    expand_status_code,
    log_malformed_records,
    write_to_delta,
    logger,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)


def transform_payments(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Transform legacy CDW_PMT_HIST data to modern payments schema.

    Returns:
        Tuple of (valid_records_df, malformed_records_df)
    """
    logger.info("Starting payment history transformation")

    # Select and rename columns
    transformed = df.select(
        trim(col("PMT_SEQ_NBR")).alias("legacy_payment_id"),
        trim(col("LN_ACCT_NBR")).alias("loan_account_number"),
        col("PMT_DT"),
        col("PMT_AMT"),
        col("PMT_PRIN_AMT"),
        col("PMT_INT_AMT"),
        col("PMT_ESCROW_AMT"),
        col("PMT_LATE_FEE"),
        col("PMT_TYP_CD"),
        col("PMT_STAT_CD"),
        col("PMT_RECV_DT"),
        col("PMT_PROC_DT"),
        col("PMT_CRET_DT"),
        col("PMT_UPDT_DT"),
    )

    # Parse amount fields
    transformed = parse_amount_string(transformed, "PMT_AMT", "total_amount", 10, 2)
    transformed = parse_amount_string(transformed, "PMT_PRIN_AMT", "principal_amount", 10, 2)
    transformed = parse_amount_string(transformed, "PMT_INT_AMT", "interest_amount", 10, 2)
    transformed = parse_amount_string(transformed, "PMT_ESCROW_AMT", "escrow_amount", 10, 2)
    transformed = parse_amount_string(transformed, "PMT_LATE_FEE", "late_fee", 10, 2)

    # Parse date fields
    transformed = parse_date_string(transformed, "PMT_DT", "payment_date")
    transformed = parse_date_string(transformed, "PMT_RECV_DT", "received_date")
    transformed = parse_date_string(transformed, "PMT_PROC_DT", "processed_date")

    # Parse timestamp fields
    transformed = parse_timestamp_string(transformed, "PMT_CRET_DT", "created_at")
    transformed = parse_timestamp_string(transformed, "PMT_UPDT_DT", "updated_at")

    # Expand type codes
    transformed = expand_status_code(transformed, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)

    # Expand status codes
    transformed = expand_status_code(transformed, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # Add metadata
    transformed = (
        transformed
        .withColumn("_ingestion_ts", current_timestamp())
        .withColumn("_source_system", lit("CDW_LEGACY"))
    )

    # Select final columns
    final = transformed.select(
        "legacy_payment_id", "loan_account_number", "payment_date",
        "total_amount", "principal_amount", "interest_amount",
        "escrow_amount", "late_fee", "type", "status",
        "received_date", "processed_date", "created_at", "updated_at",
        "_ingestion_ts", "_source_system"
    )

    # Identify malformed records
    malformed = final.filter(
        col("legacy_payment_id").isNull()
        | col("loan_account_number").isNull()
        | col("payment_date").isNull()
        | col("total_amount").isNull()
        | col("status").isNull()
    )

    valid = final.filter(
        col("legacy_payment_id").isNotNull()
        & col("loan_account_number").isNotNull()
        & col("payment_date").isNotNull()
        & col("total_amount").isNotNull()
        & col("status").isNotNull()
    )

    logger.info(
        f"Payment transformation complete: {valid.count()} valid, "
        f"{malformed.count()} malformed"
    )
    return valid, malformed


def run(config: MigrationConfig = None):
    """Execute the payment ingestion pipeline."""
    if config is None:
        config = MigrationConfig()

    spark = get_spark()
    logger.info("=" * 60)
    logger.info("STARTING: Payment Ingestion (CDW_PMT_HIST -> payments)")
    logger.info("=" * 60)

    # Read source data
    source_df = read_source_data(spark, config, "CDW_PMT_HIST")

    # Transform
    valid_df, malformed_df = transform_payments(source_df)

    # Log malformed records
    log_malformed_records(source_df, malformed_df, "CDW_PMT_HIST", spark, config)

    # Write to Delta Lake
    write_to_delta(valid_df, "payments")

    logger.info("COMPLETED: Payment Ingestion")
    return valid_df


if __name__ == "__main__":
    run()
