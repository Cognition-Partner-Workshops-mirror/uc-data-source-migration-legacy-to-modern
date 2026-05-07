"""
PySpark Ingestion Script: Loan Products
=========================================
Reads legacy CDW_LN_PROD data (simulated as CSV/Parquet source),
transforms columns to proper types, converts status codes to boolean,
and writes to the modern Delta Lake loan_products table.

Source: CDW_LN_PROD (all-VARCHAR legacy table)
Target: loan_warehouse.loan_products (Delta Lake with proper types)
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, to_date, regexp_replace, trim, when, lit
)
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DecimalType,
    BooleanType, DateType
)
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_loan_products")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/legacy/cdw_ln_prod/"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_PATH = "/mnt/quarantine/loan_products/"
LEGACY_DATE_FORMAT = "MM/dd/yyyy"


def create_spark_session():
    """Initialize SparkSession with Delta Lake support."""
    return (
        SparkSession.builder
        .appName("LoanMigration_IngestLoanProducts")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )


def define_source_schema():
    """
    Define explicit schema for legacy CSV export.
    All columns are StringType matching the legacy all-VARCHAR design.
    """
    return StructType([
        StructField("PROD_CD", StringType(), nullable=False),
        StructField("PROD_DESC_TXT", StringType(), nullable=True),
        StructField("PROD_TYP_CD", StringType(), nullable=True),
        StructField("PROD_TERM_MOS", StringType(), nullable=True),
        StructField("PROD_RT_TYP", StringType(), nullable=True),
        StructField("PROD_MIN_AMT", StringType(), nullable=True),
        StructField("PROD_MAX_AMT", StringType(), nullable=True),
        StructField("PROD_STAT_CD", StringType(), nullable=True),
        StructField("PROD_EFF_DT", StringType(), nullable=True),
        StructField("PROD_EXP_DT", StringType(), nullable=True),
    ])


def parse_amount_string(column):
    """
    Remove commas from amount strings and cast to decimal.
    E.g., "1,500,000" → 1500000.00
    """
    return regexp_replace(col(column), ",", "").cast(DecimalType(12, 2))


def read_source(spark, source_path, schema):
    """
    Read legacy loan product data from CSV source.
    Uses permissive mode to capture malformed records.
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
    Separate malformed records and write them to quarantine.
    Returns only valid records for processing.
    """
    malformed = df.filter(
        col("_corrupt_record").isNotNull() |
        col("PROD_CD").isNull() |
        (trim(col("PROD_CD")) == "")
    )

    malformed_count = malformed.count()
    if malformed_count > 0:
        logger.warning(f"Quarantining {malformed_count} malformed records to: {quarantine_path}")
        malformed.write.mode("append").json(quarantine_path)
    else:
        logger.info("No malformed records found.")

    valid = df.filter(
        col("_corrupt_record").isNull() &
        col("PROD_CD").isNotNull() &
        (trim(col("PROD_CD")) != "")
    ).drop("_corrupt_record")

    logger.info(f"Valid records for transformation: {valid.count()}")
    return valid


def transform(df):
    """
    Apply transformations for CDW_LN_PROD → loan_products:
    - Rename columns to meaningful names
    - Parse term_months from string to integer
    - Parse min/max amounts (remove commas, cast to decimal)
    - Convert status code to boolean (ACT → true, INA → false)
    - Parse date strings to DateType
    """
    logger.info("Applying transformations...")

    transformed = (
        df
        # Rename columns to modern schema names
        .withColumnRenamed("PROD_CD", "code")
        .withColumnRenamed("PROD_DESC_TXT", "name")
        .withColumnRenamed("PROD_TYP_CD", "type")
        .withColumnRenamed("PROD_RT_TYP", "rate_type")

        # Parse term months from string to integer
        .withColumn("term_months", col("PROD_TERM_MOS").cast(IntegerType()))

        # Parse amount range (remove commas, cast to decimal)
        .withColumn("min_amount", parse_amount_string("PROD_MIN_AMT"))
        .withColumn("max_amount", parse_amount_string("PROD_MAX_AMT"))

        # Convert status code to boolean: ACT → true, anything else → false
        .withColumn("is_active",
                    when(col("PROD_STAT_CD") == "ACT", lit(True))
                    .otherwise(lit(False))
                    .cast(BooleanType()))

        # Parse date strings to DateType
        .withColumn("effective_date", to_date(col("PROD_EFF_DT"), LEGACY_DATE_FORMAT))
        .withColumn("expiration_date", to_date(col("PROD_EXP_DT"), LEGACY_DATE_FORMAT))

        # Drop original columns that were transformed
        .drop("PROD_TERM_MOS", "PROD_MIN_AMT", "PROD_MAX_AMT",
               "PROD_STAT_CD", "PROD_EFF_DT", "PROD_EXP_DT")
    )

    logger.info("Transformations applied successfully.")
    return transformed


def write_to_delta(df, target_table):
    """Write transformed data to Delta Lake target table."""
    logger.info(f"Writing to Delta table: {target_table}")

    df.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .saveAsTable(target_table)

    final_count = df.count()
    logger.info(f"Successfully wrote {final_count} records to {target_table}")
    return final_count


def main():
    """Main entry point for the loan products ingestion pipeline."""
    logger.info("=" * 60)
    logger.info("Starting Loan Products Ingestion Pipeline")
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
    logger.info("Loan Products Ingestion Summary")
    logger.info(f"  Source records read:    {source_count}")
    logger.info(f"  Records quarantined:    {source_count - target_count}")
    logger.info(f"  Records written:        {target_count}")
    logger.info("=" * 60)

    spark.stop()


if __name__ == "__main__":
    main()
