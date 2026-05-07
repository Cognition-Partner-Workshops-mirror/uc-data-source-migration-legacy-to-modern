"""
Ingestion script for CDW_LN_PROD -> loan_warehouse.loan_products
Transforms legacy loan product records with:
- Amount string parsing (comma-separated -> DecimalType)
- Term months string -> IntegerType
- Status code to boolean (ACT -> true, INA -> false)
- Date string parsing (MM/DD/YYYY -> DateType)
"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, trim, when, lit, current_timestamp

from common import (
    get_spark,
    MigrationConfig,
    read_source_data,
    parse_date_string,
    parse_amount_string,
    parse_integer_string,
    log_malformed_records,
    write_to_delta,
    logger,
)


def transform_loan_products(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Transform legacy CDW_LN_PROD data to modern loan_products schema.

    Returns:
        Tuple of (valid_records_df, malformed_records_df)
    """
    logger.info("Starting loan product transformation")

    # Rename and select columns
    transformed = df.select(
        trim(col("PROD_CD")).alias("code"),
        trim(col("PROD_DESC_TXT")).alias("name"),
        trim(col("PROD_TYP_CD")).alias("type"),
        col("PROD_TERM_MOS"),
        trim(col("PROD_RT_TYP")).alias("rate_type"),
        col("PROD_MIN_AMT"),
        col("PROD_MAX_AMT"),
        col("PROD_STAT_CD"),
        col("PROD_EFF_DT"),
        col("PROD_EXP_DT"),
    )

    # Parse term months
    transformed = parse_integer_string(transformed, "PROD_TERM_MOS", "term_months")

    # Parse amounts
    transformed = parse_amount_string(transformed, "PROD_MIN_AMT", "min_amount")
    transformed = parse_amount_string(transformed, "PROD_MAX_AMT", "max_amount")

    # Convert status to boolean
    transformed = transformed.withColumn(
        "is_active",
        when(trim(col("PROD_STAT_CD")) == "ACT", lit(True))
        .when(trim(col("PROD_STAT_CD")) == "INA", lit(False))
        .otherwise(lit(None))
    )

    # Parse dates
    transformed = parse_date_string(transformed, "PROD_EFF_DT", "effective_date")
    transformed = parse_date_string(transformed, "PROD_EXP_DT", "expiration_date")

    # Add metadata
    transformed = (
        transformed
        .withColumn("_ingestion_ts", current_timestamp())
        .withColumn("_source_system", lit("CDW_LEGACY"))
    )

    # Select final columns
    final = transformed.select(
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "is_active", "effective_date",
        "expiration_date", "_ingestion_ts", "_source_system"
    )

    # Identify malformed records
    malformed = final.filter(
        col("code").isNull()
        | col("name").isNull()
        | col("is_active").isNull()
    )

    valid = final.filter(
        col("code").isNotNull()
        & col("name").isNotNull()
        & col("is_active").isNotNull()
    )

    logger.info(
        f"Loan product transformation complete: {valid.count()} valid, "
        f"{malformed.count()} malformed"
    )
    return valid, malformed


def run(config: MigrationConfig = None):
    """Execute the loan product ingestion pipeline."""
    if config is None:
        config = MigrationConfig()

    spark = get_spark()
    logger.info("=" * 60)
    logger.info("STARTING: Loan Product Ingestion (CDW_LN_PROD -> loan_products)")
    logger.info("=" * 60)

    # Read source data
    source_df = read_source_data(spark, config, "CDW_LN_PROD")

    # Transform
    valid_df, malformed_df = transform_loan_products(source_df)

    # Log malformed records
    log_malformed_records(source_df, malformed_df, "CDW_LN_PROD", spark, config)

    # Write to Delta Lake
    write_to_delta(valid_df, "loan_products")

    logger.info("COMPLETED: Loan Product Ingestion")
    return valid_df


if __name__ == "__main__":
    run()
