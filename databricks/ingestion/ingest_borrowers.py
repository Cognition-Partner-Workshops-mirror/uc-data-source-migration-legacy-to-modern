"""
PySpark ingestion script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads from a legacy CSV/Parquet extract of the CDW_BORR_MSTR table and transforms
all VARCHAR columns into proper Spark SQL types per column_mappings.md. The
BORR_REC_TYP column is intentionally dropped (no business value in modern schema).

Usage (Databricks notebook cell):
    %run ./transform_utils
    %run ./ingest_borrowers

Or as a standalone script:
    spark-submit --master local[*] ingest_borrowers.py \
        --source-path /mnt/landing/cdw_borr_mstr/ \
        --source-format csv \
        --target-table loan_warehouse.borrowers
"""

import argparse
import logging
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

# Local imports — available when running as a Databricks notebook or via PYTHONPATH
from transform_utils import (
    parse_date_mmddyyyy,
    parse_timestamp_mmddyyyy,
    parse_decimal_amount,
    parse_integer,
    expand_status_code,
    tag_malformed_rows,
    log_unmapped_codes,
    BORROWER_STATUS_MAP,
)

logger = logging.getLogger("cdw_migration.borrowers")
logger.setLevel(logging.INFO)


def read_legacy_borrowers(spark: SparkSession, source_path: str,
                          source_format: str = "csv") -> DataFrame:
    """
    Read the legacy CDW_BORR_MSTR extract from the landing zone.
    Supports CSV (with header) and Parquet formats.
    """
    if source_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")    # Keep everything as STRING initially
            .option("nullValue", "")
            .csv(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from legacy CDW_BORR_MSTR at %s", df.count(), source_path)
    return df


def transform_borrowers(df: DataFrame) -> DataFrame:
    """
    Transform legacy CDW_BORR_MSTR columns to the modern borrowers schema.

    Transformations applied:
      - BORR_DOB_DT:    MM/DD/YYYY string → DateType
      - BORR_ANN_INCM:  comma-formatted string → DECIMAL(12,2)
      - BORR_CRDT_SCR:  VARCHAR → IntegerType
      - BORR_STAT_CD:   abbreviation → expanded status (ACT→ACTIVE, INA→INACTIVE)
      - BORR_CRET_DT:   MM/DD/YYYY string → TimestampType
      - BORR_UPDT_DT:   MM/DD/YYYY string → TimestampType
      - BORR_REC_TYP:   dropped (not needed in modern schema)
    """
    transformed = (
        df
        # Direct-copy string fields
        .withColumn("external_id", F.col("BORR_ID"))
        .withColumn("first_name", F.trim(F.col("BORR_FST_NM")))
        .withColumn("last_name", F.trim(F.col("BORR_LST_NM")))
        .withColumn("middle_initial", F.col("BORR_MID_INIT"))
        .withColumn("ssn_hash", F.col("BORR_SSN_ENCR"))
        .withColumn("address_line1", F.col("BORR_ADDR_LN1"))
        .withColumn("address_line2", F.col("BORR_ADDR_LN2"))
        .withColumn("city", F.col("BORR_CTY_NM"))
        .withColumn("state", F.col("BORR_ST_CD"))
        .withColumn("zip_code", F.col("BORR_ZIP_CD"))
        .withColumn("phone", F.col("BORR_PH_NBR"))
        .withColumn("email", F.col("BORR_EMAIL_ADDR"))
        .withColumn("employment_status", F.col("BORR_EMP_STAT"))

        # Type conversions
        .withColumn("date_of_birth", parse_date_mmddyyyy("BORR_DOB_DT"))
        .withColumn("annual_income", parse_decimal_amount("BORR_ANN_INCM"))
        .withColumn("credit_score", parse_integer("BORR_CRDT_SCR"))

        # Status code expansion
        .withColumn("status", expand_status_code("BORR_STAT_CD", BORROWER_STATUS_MAP))

        # Timestamp conversions
        .withColumn("created_at", parse_timestamp_mmddyyyy("BORR_CRET_DT"))
        .withColumn("updated_at", parse_timestamp_mmddyyyy("BORR_UPDT_DT"))
    )

    # Tag rows with malformed date/amount values for downstream quality checks
    transformed = tag_malformed_rows(transformed, "BORR_DOB_DT", "date_of_birth")
    transformed = tag_malformed_rows(transformed, "BORR_ANN_INCM", "annual_income")

    # Log any unmapped status codes
    log_unmapped_codes(transformed, "BORR_STAT_CD", "status", "CDW_BORR_MSTR")

    # Select only the modern columns (drop legacy columns and BORR_REC_TYP)
    modern_columns = [
        "external_id", "first_name", "last_name", "middle_initial",
        "ssn_hash", "date_of_birth", "address_line1", "address_line2",
        "city", "state", "zip_code", "phone", "email",
        "credit_score", "employment_status", "annual_income",
        "status", "created_at", "updated_at",
    ]
    return transformed.select(modern_columns)


def write_borrowers(df: DataFrame, target_table: str = "loan_warehouse.borrowers") -> None:
    """
    Write the transformed borrower data to the Delta Lake target table.
    Uses merge (upsert) on external_id to support idempotent reruns.
    """
    row_count = df.count()
    logger.info("Writing %d borrower records to %s", row_count, target_table)

    # Register source as a temp view for the MERGE statement
    df.createOrReplaceTempView("borrowers_staging")

    spark = df.sparkSession
    spark.sql(f"""
        MERGE INTO {target_table} AS target
        USING borrowers_staging AS source
        ON target.external_id = source.external_id
        WHEN MATCHED THEN UPDATE SET
            first_name        = source.first_name,
            last_name         = source.last_name,
            middle_initial    = source.middle_initial,
            ssn_hash          = source.ssn_hash,
            date_of_birth     = source.date_of_birth,
            address_line1     = source.address_line1,
            address_line2     = source.address_line2,
            city              = source.city,
            state             = source.state,
            zip_code          = source.zip_code,
            phone             = source.phone,
            email             = source.email,
            credit_score      = source.credit_score,
            employment_status = source.employment_status,
            annual_income     = source.annual_income,
            status            = source.status,
            created_at        = source.created_at,
            updated_at        = source.updated_at,
            _migration_ts     = current_timestamp()
        WHEN NOT MATCHED THEN INSERT (
            external_id, first_name, last_name, middle_initial,
            ssn_hash, date_of_birth, address_line1, address_line2,
            city, state, zip_code, phone, email,
            credit_score, employment_status, annual_income,
            status, created_at, updated_at
        ) VALUES (
            source.external_id, source.first_name, source.last_name, source.middle_initial,
            source.ssn_hash, source.date_of_birth, source.address_line1, source.address_line2,
            source.city, source.state, source.zip_code, source.phone, source.email,
            source.credit_score, source.employment_status, source.annual_income,
            source.status, source.created_at, source.updated_at
        )
    """)
    logger.info("Borrower ingestion complete: %d records processed", row_count)


# ---------------------------------------------------------------------------
# CLI entry point for spark-submit execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_BORR_MSTR to loan_warehouse.borrowers")
    parser.add_argument("--source-path", required=True, help="Path to legacy CSV/Parquet extract")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--target-table", default="loan_warehouse.borrowers")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Borrower_Ingestion").getOrCreate()

    raw_df = read_legacy_borrowers(spark, args.source_path, args.source_format)
    transformed_df = transform_borrowers(raw_df)
    write_borrowers(transformed_df, args.target_table)

    spark.stop()
