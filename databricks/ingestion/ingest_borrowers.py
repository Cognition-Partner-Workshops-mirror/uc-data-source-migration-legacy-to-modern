"""
Ingestion script: CDW_BORR_MSTR → borrowers (Delta Lake)

Reads legacy borrower data from CSV/Parquet source, applies transformations
per column_mappings.md, and writes to the modern borrowers Delta table.
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
    BORROWER_STATUS_MAP,
)


def read_legacy_borrowers(spark, source_path: str):
    """
    Read legacy CDW_BORR_MSTR data from CSV or Parquet.
    Auto-detects format based on file extension.
    """
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


def transform_borrowers(df):
    """
    Apply all transformations to convert legacy borrower data to modern schema.
    """
    source_count = log_record_counts(df, "borrowers", "source")

    # Flag records with critical nulls (don't drop, just log)
    log_null_counts(df, "borrowers", ["BORR_ID", "BORR_FST_NM", "BORR_LST_NM"])

    # Rename direct-copy columns
    result = df.select(
        col("BORR_ID").alias("external_id"),
        col("BORR_FST_NM").alias("first_name"),
        col("BORR_LST_NM").alias("last_name"),
        col("BORR_MID_INIT").alias("middle_initial"),
        col("BORR_SSN_ENCR").alias("ssn_hash"),
        col("BORR_DOB_DT"),
        col("BORR_ADDR_LN1").alias("address_line1"),
        col("BORR_ADDR_LN2").alias("address_line2"),
        col("BORR_CTY_NM").alias("city"),
        col("BORR_ST_CD").alias("state"),
        col("BORR_ZIP_CD").alias("zip_code"),
        col("BORR_PH_NBR").alias("phone"),
        col("BORR_EMAIL_ADDR").alias("email"),
        col("BORR_CRDT_SCR"),
        col("BORR_EMP_STAT").alias("employment_status"),
        col("BORR_ANN_INCM"),
        col("BORR_CRET_DT"),
        col("BORR_UPDT_DT"),
        col("BORR_STAT_CD"),
    )

    # Parse date of birth
    result = parse_date_column(result, "BORR_DOB_DT", "date_of_birth")
    result = result.drop("BORR_DOB_DT")

    # Parse credit score to integer
    result = parse_integer_column(result, "BORR_CRDT_SCR", "credit_score")
    result = result.drop("BORR_CRDT_SCR")

    # Parse annual income (remove commas, cast to decimal)
    result = parse_amount_column(result, "BORR_ANN_INCM", "annual_income")
    result = result.drop("BORR_ANN_INCM")

    # Parse created/updated timestamps
    result = parse_timestamp_column(result, "BORR_CRET_DT", "created_at")
    result = result.drop("BORR_CRET_DT")
    result = parse_timestamp_column(result, "BORR_UPDT_DT", "updated_at")
    result = result.drop("BORR_UPDT_DT")

    # Expand status codes
    result = expand_status_code(result, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP)
    result = result.drop("BORR_STAT_CD")

    # Add surrogate key
    result = result.withColumn("id", monotonically_increasing_id())

    target_count = log_record_counts(result, "borrowers", "transformed")

    if source_count != target_count:
        logger.error(
            f"[borrowers] Record count mismatch! Source={source_count}, Target={target_count}"
        )

    return result


def run(source_path: str):
    """Main entry point for borrower ingestion."""
    spark = get_spark()
    logger.info("=== Starting Borrower Ingestion ===")

    raw_df = read_legacy_borrowers(spark, source_path)
    transformed_df = transform_borrowers(raw_df)
    write_delta(transformed_df, "borrowers", partition_cols=["state"])

    logger.info("=== Borrower Ingestion Complete ===")
    return transformed_df


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: spark-submit ingest_borrowers.py <source_path>")
        sys.exit(1)
    run(sys.argv[1])
