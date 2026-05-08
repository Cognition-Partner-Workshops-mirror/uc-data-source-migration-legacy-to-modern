"""
PySpark Ingestion Script: CDW_BORR_MSTR -> borrowers
=====================================================
Reads legacy borrower data (simulated as CSV/Parquet), applies type conversions,
validates required fields, expands status codes, and writes to the Delta Lake
borrowers table.

Transformation Summary:
  - MM/DD/YYYY date strings  -> DateType / TimestampType
  - Comma-formatted amounts  -> DecimalType(12,2)
  - Credit score strings     -> IntegerType (validated 300-850)
  - Status codes             -> Expanded (ACT -> ACTIVE, INA -> INACTIVE)
  - BORR_REC_TYP column      -> Dropped (no business value)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DateType, IntegerType,
    DecimalType, TimestampType
)
import logging

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "/mnt/legacy-data/CDW_BORR_MSTR"  # CSV or Parquet path
TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_TABLE = "loan_warehouse._quarantine_borrowers"

# Status code expansion mapping per column_mappings.md
STATUS_MAP = {"ACT": "ACTIVE", "INA": "INACTIVE"}

logger = logging.getLogger("ingest_borrowers")
logging.basicConfig(level=logging.INFO)


def read_legacy_source(spark: SparkSession, path: str) -> DataFrame:
    """Read legacy CDW_BORR_MSTR data from CSV or Parquet source files."""
    # Try Parquet first; fall back to CSV if the path contains .csv files
    try:
        df = spark.read.parquet(path)
        logger.info("Read legacy borrower data from Parquet: %s", path)
    except Exception:
        df = spark.read.option("header", "true").option("inferSchema", "false").csv(path)
        logger.info("Read legacy borrower data from CSV: %s", path)
    logger.info("Source row count: %d", df.count())
    return df


def parse_legacy_date(col_name: str):
    """Convert MM/DD/YYYY VARCHAR string to DateType using to_date()."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_timestamp(col_name: str):
    """Convert MM/DD/YYYY VARCHAR string to TimestampType (midnight on that date)."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_amount(col_name: str):
    """Remove commas and dollar signs from VARCHAR amount, cast to DecimalType."""
    return F.regexp_replace(F.col(col_name), "[,$]", "").cast(DecimalType(12, 2))


def parse_legacy_integer(col_name: str):
    """Cast VARCHAR integer string to IntegerType."""
    return F.col(col_name).cast(IntegerType())


def expand_status(col_name: str, mapping: dict):
    """Expand abbreviated status codes using a mapping dictionary.

    Unknown codes are preserved as-is with a '[UNMAPPED]' suffix so they
    are visible in quality checks rather than silently dropped.
    """
    expr = F.col(col_name)
    for code, expanded in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(expanded)).otherwise(expr)
    return expr


def transform_borrowers(df: DataFrame) -> DataFrame:
    """Apply all column transformations for the borrowers table.

    Transformations follow data/mappings/column_mappings.md exactly:
      - BORR_DOB_DT: MM/DD/YYYY -> DATE
      - BORR_CRDT_SCR: VARCHAR -> INT
      - BORR_ANN_INCM: comma-formatted string -> DECIMAL(12,2)
      - BORR_CRET_DT, BORR_UPDT_DT: MM/DD/YYYY -> TIMESTAMP
      - BORR_STAT_CD: ACT -> ACTIVE, INA -> INACTIVE
      - BORR_REC_TYP: dropped
    """
    return (
        df
        .withColumn("external_id", F.col("BORR_ID"))
        .withColumn("first_name", F.trim(F.col("BORR_FST_NM")))
        .withColumn("last_name", F.trim(F.col("BORR_LST_NM")))
        .withColumn("middle_initial", F.trim(F.col("BORR_MID_INIT")))
        .withColumn("ssn_hash", F.col("BORR_SSN_ENCR"))
        .withColumn("date_of_birth", parse_legacy_date("BORR_DOB_DT"))
        .withColumn("address_line1", F.col("BORR_ADDR_LN1"))
        .withColumn("address_line2", F.col("BORR_ADDR_LN2"))
        .withColumn("city", F.col("BORR_CTY_NM"))
        .withColumn("state", F.col("BORR_ST_CD"))
        .withColumn("zip_code", F.col("BORR_ZIP_CD"))
        .withColumn("phone", F.col("BORR_PH_NBR"))
        .withColumn("email", F.col("BORR_EMAIL_ADDR"))
        # Credit score: parse to integer for range validation downstream
        .withColumn("credit_score", parse_legacy_integer("BORR_CRDT_SCR"))
        .withColumn("employment_status", F.col("BORR_EMP_STAT"))
        # Annual income: strip commas, parse to decimal
        .withColumn("annual_income", parse_legacy_amount("BORR_ANN_INCM"))
        # Audit dates: parse to full timestamps (time component defaults to midnight)
        .withColumn("created_at", parse_legacy_timestamp("BORR_CRET_DT"))
        .withColumn("updated_at", parse_legacy_timestamp("BORR_UPDT_DT"))
        # Status code expansion
        .withColumn("status", expand_status("BORR_STAT_CD", STATUS_MAP))
        # Lineage metadata
        .withColumn("_legacy_source", F.lit("CDW_BORR_MSTR"))
        .withColumn("_ingested_at", F.current_timestamp())
        # Select only modern columns; drops BORR_REC_TYP and all legacy-named columns
        .select(
            "external_id", "first_name", "last_name", "middle_initial",
            "ssn_hash", "date_of_birth", "address_line1", "address_line2",
            "city", "state", "zip_code", "phone", "email",
            "credit_score", "employment_status", "annual_income",
            "created_at", "updated_at", "status",
            "_legacy_source", "_ingested_at"
        )
    )


def quarantine_bad_records(df: DataFrame) -> tuple:
    """Separate records with null required fields or out-of-range credit scores.

    Returns (good_df, bad_df) so bad records are quarantined rather than
    silently dropped. The quarantine table can be reviewed by data stewards.
    """
    required_not_null = (
        F.col("first_name").isNotNull()
        & F.col("last_name").isNotNull()
        & F.col("ssn_hash").isNotNull()
        & F.col("date_of_birth").isNotNull()
        & F.col("credit_score").isNotNull()
        & F.col("annual_income").isNotNull()
        & F.col("created_at").isNotNull()
        & F.col("updated_at").isNotNull()
        & F.col("status").isNotNull()
    )
    # Credit score business rule: FICO range 300-850
    credit_in_range = (
        (F.col("credit_score") >= 300) & (F.col("credit_score") <= 850)
    )

    good_df = df.filter(required_not_null & credit_in_range)
    bad_df = df.filter(~(required_not_null & credit_in_range))

    bad_count = bad_df.count()
    if bad_count > 0:
        logger.warning("Quarantined %d borrower records with null required fields or invalid credit scores", bad_count)

    return good_df, bad_df


def write_to_delta(df: DataFrame, table: str, mode: str = "overwrite"):
    """Write DataFrame to a Delta Lake table."""
    df.write.format("delta").mode(mode).saveAsTable(table)
    logger.info("Wrote %d rows to %s", df.count(), table)


def run(spark: SparkSession):
    """Main entry point: read -> transform -> quarantine -> write."""
    logger.info("=== Starting borrower ingestion ===")

    # Step 1: Read legacy source
    raw_df = read_legacy_source(spark, LEGACY_SOURCE_PATH)

    # Step 2: Transform to modern schema
    transformed_df = transform_borrowers(raw_df)

    # Step 3: Quarantine bad records instead of silently dropping them
    good_df, bad_df = quarantine_bad_records(transformed_df)

    # Step 4: Write good records to target table
    write_to_delta(good_df, TARGET_TABLE, mode="overwrite")

    # Step 5: Write quarantined records for review
    if bad_df.count() > 0:
        write_to_delta(bad_df, QUARANTINE_TABLE, mode="overwrite")

    logger.info("=== Borrower ingestion complete ===")


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestBorrowers").getOrCreate()
    run(spark)
