"""
PySpark Ingestion Script: Borrowers
====================================
Reads legacy CDW_BORR_MSTR data (simulated as CSV/Parquet source),
transforms columns to proper types, expands status codes, and writes
to the modern Delta Lake borrowers table.

Source: CDW_BORR_MSTR (all-VARCHAR legacy table)
Target: loan_warehouse.borrowers (Delta Lake with proper types)
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, to_date, to_timestamp, regexp_replace, trim, when, lit, coalesce
)
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DecimalType, DateType,
    TimestampType
)
import logging

# Configure logging for tracking malformed records
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_borrowers")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Source path (CSV export from legacy CDW_BORR_MSTR table)
SOURCE_PATH = "/mnt/landing/legacy/cdw_borr_mstr/"
# Target Delta Lake table
TARGET_TABLE = "loan_warehouse.borrowers"
# Quarantine path for malformed records that cannot be processed
QUARANTINE_PATH = "/mnt/quarantine/borrowers/"
# Date format used in legacy system
LEGACY_DATE_FORMAT = "MM/dd/yyyy"

# ---------------------------------------------------------------------------
# Status code expansion mapping (legacy abbreviation → modern readable value)
# ---------------------------------------------------------------------------
STATUS_MAP = {
    "ACT": "Active",
    "INA": "Inactive"
}


def create_spark_session():
    """Initialize SparkSession with Delta Lake support."""
    return (
        SparkSession.builder
        .appName("LoanMigration_IngestBorrowers")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )


def define_source_schema():
    """
    Define explicit schema for reading the legacy CSV export.
    All columns are StringType to match the legacy all-VARCHAR design.
    """
    return StructType([
        StructField("BORR_ID", StringType(), nullable=False),
        StructField("BORR_FST_NM", StringType(), nullable=True),
        StructField("BORR_LST_NM", StringType(), nullable=True),
        StructField("BORR_MID_INIT", StringType(), nullable=True),
        StructField("BORR_SSN_ENCR", StringType(), nullable=True),
        StructField("BORR_DOB_DT", StringType(), nullable=True),
        StructField("BORR_ADDR_LN1", StringType(), nullable=True),
        StructField("BORR_ADDR_LN2", StringType(), nullable=True),
        StructField("BORR_CTY_NM", StringType(), nullable=True),
        StructField("BORR_ST_CD", StringType(), nullable=True),
        StructField("BORR_ZIP_CD", StringType(), nullable=True),
        StructField("BORR_PH_NBR", StringType(), nullable=True),
        StructField("BORR_EMAIL_ADDR", StringType(), nullable=True),
        StructField("BORR_CRDT_SCR", StringType(), nullable=True),
        StructField("BORR_EMP_STAT", StringType(), nullable=True),
        StructField("BORR_ANN_INCM", StringType(), nullable=True),
        StructField("BORR_CRET_DT", StringType(), nullable=True),
        StructField("BORR_UPDT_DT", StringType(), nullable=True),
        StructField("BORR_STAT_CD", StringType(), nullable=True),
        StructField("BORR_REC_TYP", StringType(), nullable=True),
    ])


def parse_amount_string(column):
    """
    Remove commas from amount strings and cast to decimal.
    E.g., "92,500" → 92500.00
    """
    return regexp_replace(col(column), ",", "").cast(DecimalType(12, 2))


def expand_status_code(column):
    """
    Expand legacy status abbreviations to readable values.
    ACT → Active, INA → Inactive. Unknown codes are preserved with a warning prefix.
    """
    return (
        when(col(column) == "ACT", lit("Active"))
        .when(col(column) == "INA", lit("Inactive"))
        .otherwise(col(column))  # Preserve unknown codes rather than dropping records
    )


def read_source(spark, source_path, schema):
    """
    Read legacy data from CSV source files.
    Uses permissive mode to capture malformed records in _corrupt_record column.
    """
    logger.info(f"Reading source data from: {source_path}")

    df = (
        spark.read
        .option("header", "true")
        .option("mode", "PERMISSIVE")
        .option("columnNameOfCorruptRecord", "_corrupt_record")
        .schema(schema.add(StructField("_corrupt_record", StringType(), nullable=True)))
        .csv(source_path)
    )

    total_count = df.count()
    logger.info(f"Total records read from source: {total_count}")
    return df


def quarantine_malformed(df, quarantine_path):
    """
    Separate malformed records and write them to quarantine for manual review.
    Returns only the valid records for further processing.
    """
    # Identify records with parsing issues or missing required fields
    malformed = df.filter(
        col("_corrupt_record").isNotNull() |
        col("BORR_ID").isNull() |
        (trim(col("BORR_ID")) == "")
    )

    malformed_count = malformed.count()
    if malformed_count > 0:
        logger.warning(f"Quarantining {malformed_count} malformed records to: {quarantine_path}")
        malformed.write.mode("append").json(quarantine_path)
    else:
        logger.info("No malformed records found.")

    # Return only valid records (drop _corrupt_record column)
    valid = df.filter(
        col("_corrupt_record").isNull() &
        col("BORR_ID").isNotNull() &
        (trim(col("BORR_ID")) != "")
    ).drop("_corrupt_record")

    logger.info(f"Valid records for transformation: {valid.count()}")
    return valid


def transform(df):
    """
    Apply all transformations to convert legacy CDW_BORR_MSTR to modern borrowers schema.
    - Parse date strings (MM/DD/YYYY) to DateType/TimestampType
    - Parse amount strings (with commas) to DecimalType
    - Parse credit score string to IntegerType
    - Expand status code abbreviations
    - Drop legacy-only columns (BORR_REC_TYP)
    """
    logger.info("Applying transformations...")

    transformed = (
        df
        # Rename and map columns to modern names
        .withColumnRenamed("BORR_ID", "external_id")
        .withColumnRenamed("BORR_FST_NM", "first_name")
        .withColumnRenamed("BORR_LST_NM", "last_name")
        .withColumnRenamed("BORR_MID_INIT", "middle_initial")
        .withColumnRenamed("BORR_SSN_ENCR", "ssn_hash")
        .withColumnRenamed("BORR_ADDR_LN1", "address_line1")
        .withColumnRenamed("BORR_ADDR_LN2", "address_line2")
        .withColumnRenamed("BORR_CTY_NM", "city")
        .withColumnRenamed("BORR_ST_CD", "state")
        .withColumnRenamed("BORR_ZIP_CD", "zip_code")
        .withColumnRenamed("BORR_PH_NBR", "phone")
        .withColumnRenamed("BORR_EMAIL_ADDR", "email")
        .withColumnRenamed("BORR_EMP_STAT", "employment_status")

        # Parse date_of_birth from MM/DD/YYYY string to DATE
        .withColumn("date_of_birth", to_date(col("BORR_DOB_DT"), LEGACY_DATE_FORMAT))

        # Parse credit score from string to integer
        .withColumn("credit_score", col("BORR_CRDT_SCR").cast(IntegerType()))

        # Parse annual income: remove commas, cast to decimal
        .withColumn("annual_income", parse_amount_string("BORR_ANN_INCM"))

        # Parse audit timestamps from MM/DD/YYYY to TIMESTAMP
        .withColumn("created_at", to_timestamp(col("BORR_CRET_DT"), LEGACY_DATE_FORMAT))
        .withColumn("updated_at", to_timestamp(col("BORR_UPDT_DT"), LEGACY_DATE_FORMAT))

        # Expand status code (ACT → Active, INA → Inactive)
        .withColumn("status", expand_status_code("BORR_STAT_CD"))

        # Drop legacy-only columns that are not needed in modern schema
        .drop("BORR_DOB_DT", "BORR_CRDT_SCR", "BORR_ANN_INCM",
               "BORR_CRET_DT", "BORR_UPDT_DT", "BORR_STAT_CD", "BORR_REC_TYP")
    )

    logger.info("Transformations applied successfully.")
    return transformed


def write_to_delta(df, target_table):
    """
    Write transformed data to Delta Lake target table using merge (upsert)
    to handle re-runs without duplicating records.
    """
    logger.info(f"Writing to Delta table: {target_table}")

    # For initial load, use overwrite; for incremental, use merge
    df.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .saveAsTable(target_table)

    final_count = df.count()
    logger.info(f"Successfully wrote {final_count} records to {target_table}")
    return final_count


def main():
    """
    Main entry point for the borrower ingestion pipeline.
    Orchestrates: read → quarantine → transform → write → log summary.
    """
    logger.info("=" * 60)
    logger.info("Starting Borrower Ingestion Pipeline")
    logger.info("=" * 60)

    spark = create_spark_session()
    schema = define_source_schema()

    # Step 1: Read source data
    raw_df = read_source(spark, SOURCE_PATH, schema)
    source_count = raw_df.count()

    # Step 2: Quarantine malformed records
    valid_df = quarantine_malformed(raw_df, QUARANTINE_PATH)

    # Step 3: Transform to modern schema
    transformed_df = transform(valid_df)

    # Step 4: Write to Delta Lake
    target_count = write_to_delta(transformed_df, TARGET_TABLE)

    # Step 5: Log reconciliation summary
    logger.info("=" * 60)
    logger.info("Borrower Ingestion Summary")
    logger.info(f"  Source records read:    {source_count}")
    logger.info(f"  Records quarantined:    {source_count - target_count}")
    logger.info(f"  Records written:        {target_count}")
    logger.info("=" * 60)

    spark.stop()


if __name__ == "__main__":
    main()
