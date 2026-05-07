"""
Ingestion script for CDW_BORR_MSTR -> loan_warehouse.borrowers
Transforms legacy borrower records with:
- Date string parsing (MM/DD/YYYY -> DateType/TimestampType)
- Amount string parsing (comma-separated -> DecimalType)
- Status code expansion (ACT -> ACTIVE, INA -> INACTIVE)
- Credit score string -> IntegerType with range validation
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
    parse_integer_string,
    expand_status_code,
    log_malformed_records,
    write_to_delta,
    logger,
    BORROWER_STATUS_MAP,
)


def transform_borrowers(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Transform legacy CDW_BORR_MSTR data to modern borrowers schema.

    Returns:
        Tuple of (valid_records_df, malformed_records_df)
    """
    logger.info("Starting borrower transformation")

    # Rename columns to modern names (direct copy fields)
    transformed = df.select(
        trim(col("BORR_ID")).alias("external_id"),
        trim(col("BORR_FST_NM")).alias("first_name"),
        trim(col("BORR_LST_NM")).alias("last_name"),
        trim(col("BORR_MID_INIT")).alias("middle_initial"),
        trim(col("BORR_SSN_ENCR")).alias("ssn_hash"),
        col("BORR_DOB_DT"),
        trim(col("BORR_ADDR_LN1")).alias("address_line1"),
        trim(col("BORR_ADDR_LN2")).alias("address_line2"),
        trim(col("BORR_CTY_NM")).alias("city"),
        trim(col("BORR_ST_CD")).alias("state"),
        trim(col("BORR_ZIP_CD")).alias("zip_code"),
        trim(col("BORR_PH_NBR")).alias("phone"),
        trim(col("BORR_EMAIL_ADDR")).alias("email"),
        col("BORR_CRDT_SCR"),
        trim(col("BORR_EMP_STAT")).alias("employment_status"),
        col("BORR_ANN_INCM"),
        col("BORR_CRET_DT"),
        col("BORR_UPDT_DT"),
        col("BORR_STAT_CD"),
    )

    # Parse date of birth
    transformed = parse_date_string(transformed, "BORR_DOB_DT", "date_of_birth")

    # Parse timestamps
    transformed = parse_timestamp_string(transformed, "BORR_CRET_DT", "created_at")
    transformed = parse_timestamp_string(transformed, "BORR_UPDT_DT", "updated_at")

    # Parse credit score to integer
    transformed = parse_integer_string(transformed, "BORR_CRDT_SCR", "credit_score")

    # Parse annual income (remove commas, cast to decimal)
    transformed = parse_amount_string(transformed, "BORR_ANN_INCM", "annual_income")

    # Expand status codes
    transformed = expand_status_code(transformed, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)

    # Add metadata columns
    transformed = (
        transformed
        .withColumn("_ingestion_ts", current_timestamp())
        .withColumn("_source_system", lit("CDW_LEGACY"))
    )

    # Select final columns
    final = transformed.select(
        "external_id", "first_name", "last_name", "middle_initial",
        "ssn_hash", "date_of_birth", "address_line1", "address_line2",
        "city", "state", "zip_code", "phone", "email", "credit_score",
        "employment_status", "annual_income", "status", "created_at",
        "updated_at", "_ingestion_ts", "_source_system"
    )

    # Identify malformed records (missing required fields)
    malformed = final.filter(
        col("external_id").isNull()
        | col("first_name").isNull()
        | col("last_name").isNull()
        | col("status").isNull()
    )

    valid = final.filter(
        col("external_id").isNotNull()
        & col("first_name").isNotNull()
        & col("last_name").isNotNull()
        & col("status").isNotNull()
    )

    # Log credit score out-of-range warnings (don't reject, just warn)
    out_of_range = valid.filter(
        (col("credit_score").isNotNull())
        & ((col("credit_score") < 300) | (col("credit_score") > 850))
    )
    if out_of_range.count() > 0:
        logger.warning(
            f"Found {out_of_range.count()} borrowers with credit scores outside "
            f"expected range (300-850). Records retained but flagged."
        )

    logger.info(
        f"Borrower transformation complete: {valid.count()} valid, "
        f"{malformed.count()} malformed"
    )
    return valid, malformed


def run(config: MigrationConfig = None):
    """Execute the borrower ingestion pipeline."""
    if config is None:
        config = MigrationConfig()

    spark = get_spark()
    logger.info("=" * 60)
    logger.info("STARTING: Borrower Ingestion (CDW_BORR_MSTR -> borrowers)")
    logger.info("=" * 60)

    # Read source data
    source_df = read_source_data(spark, config, "CDW_BORR_MSTR")

    # Transform
    valid_df, malformed_df = transform_borrowers(source_df)

    # Log malformed records
    log_malformed_records(source_df, malformed_df, "CDW_BORR_MSTR", spark, config)

    # Write to Delta Lake
    write_to_delta(valid_df, "borrowers")

    logger.info("COMPLETED: Borrower Ingestion")
    return valid_df


if __name__ == "__main__":
    run()
