"""
PySpark Ingestion Script: Loan Accounts
=========================================
Reads legacy CDW_LN_ACCT data (simulated as CSV/Parquet source),
transforms columns to proper types, resolves foreign keys to borrowers
and loan_products, expands status/property type codes, drops denormalized
borrower fields, and writes to the modern Delta Lake loan_accounts table.

Source: CDW_LN_ACCT (all-VARCHAR legacy table, denormalized)
Target: loan_warehouse.loan_accounts (Delta Lake, normalized with FKs)
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, to_date, to_timestamp, regexp_replace, trim, when, lit, coalesce
)
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DecimalType, DateType
)
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_loan_accounts")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/legacy/cdw_ln_acct/"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_PATH = "/mnt/quarantine/loan_accounts/"
LEGACY_DATE_FORMAT = "MM/dd/yyyy"

# ---------------------------------------------------------------------------
# Status code expansion mappings
# ---------------------------------------------------------------------------
# Loan status codes (CDW_LN_ACCT.LN_STAT_CD)
LOAN_STATUS_MAP = {
    "ACT": "Active",
    "CLO": "Closed",
    "DFT": "Default",
    "FRB": "Forbearance"
}

# Property type codes (CDW_LN_ACCT.PROP_TYP_CD)
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse"
}


def create_spark_session():
    """Initialize SparkSession with Delta Lake support."""
    return (
        SparkSession.builder
        .appName("LoanMigration_IngestLoanAccounts")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )


def define_source_schema():
    """
    Define explicit schema for legacy CSV export.
    All columns are StringType matching the legacy all-VARCHAR design.
    Includes denormalized borrower fields that will be dropped.
    """
    return StructType([
        StructField("LN_ACCT_NBR", StringType(), nullable=False),
        StructField("BORR_ID", StringType(), nullable=True),
        # Denormalized borrower fields (will be dropped during transformation)
        StructField("BORR_FST_NM", StringType(), nullable=True),
        StructField("BORR_LST_NM", StringType(), nullable=True),
        StructField("BORR_SSN_LST4", StringType(), nullable=True),
        # Loan-specific fields
        StructField("PROD_CD", StringType(), nullable=True),
        StructField("LN_ORIG_AMT", StringType(), nullable=True),
        StructField("LN_CURR_BAL", StringType(), nullable=True),
        StructField("LN_INT_RT", StringType(), nullable=True),
        StructField("LN_TERM_MOS", StringType(), nullable=True),
        StructField("LN_PMT_AMT", StringType(), nullable=True),
        StructField("LN_ORIG_DT", StringType(), nullable=True),
        StructField("LN_MAT_DT", StringType(), nullable=True),
        StructField("LN_1ST_PMT_DT", StringType(), nullable=True),
        StructField("LN_NXT_PMT_DT", StringType(), nullable=True),
        StructField("LN_STAT_CD", StringType(), nullable=True),
        StructField("LN_DLQ_DAYS", StringType(), nullable=True),
        StructField("LN_ESCROW_BAL", StringType(), nullable=True),
        StructField("LN_LTV_PCT", StringType(), nullable=True),
        StructField("PROP_ADDR_LN1", StringType(), nullable=True),
        StructField("PROP_CTY_NM", StringType(), nullable=True),
        StructField("PROP_ST_CD", StringType(), nullable=True),
        StructField("PROP_ZIP_CD", StringType(), nullable=True),
        StructField("PROP_TYP_CD", StringType(), nullable=True),
        StructField("PROP_APRS_VAL", StringType(), nullable=True),
        StructField("LN_CRET_DT", StringType(), nullable=True),
        StructField("LN_UPDT_DT", StringType(), nullable=True),
    ])


def parse_amount_string(column):
    """Remove commas from amount strings and cast to decimal."""
    return regexp_replace(col(column), ",", "").cast(DecimalType(12, 2))


def expand_loan_status(column):
    """
    Expand loan status abbreviations to full readable values.
    ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance.
    """
    return (
        when(col(column) == "ACT", lit("Active"))
        .when(col(column) == "CLO", lit("Closed"))
        .when(col(column) == "DFT", lit("Default"))
        .when(col(column) == "FRB", lit("Forbearance"))
        .otherwise(col(column))  # Preserve unknown codes
    )


def expand_property_type(column):
    """
    Expand property type abbreviations to full readable values.
    SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse.
    """
    return (
        when(col(column) == "SFR", lit("Single Family"))
        .when(col(column) == "CND", lit("Condominium"))
        .when(col(column) == "MFR", lit("Multi-Family"))
        .when(col(column) == "TWN", lit("Townhouse"))
        .otherwise(col(column))  # Preserve unknown codes
    )


def read_source(spark, source_path, schema):
    """Read legacy loan account data from CSV source with error handling."""
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
    """Separate malformed records for manual review."""
    malformed = df.filter(
        col("_corrupt_record").isNotNull() |
        col("LN_ACCT_NBR").isNull() |
        (trim(col("LN_ACCT_NBR")) == "") |
        col("BORR_ID").isNull()
    )

    malformed_count = malformed.count()
    if malformed_count > 0:
        logger.warning(f"Quarantining {malformed_count} malformed records to: {quarantine_path}")
        malformed.write.mode("append").json(quarantine_path)
    else:
        logger.info("No malformed records found.")

    valid = df.filter(
        col("_corrupt_record").isNull() &
        col("LN_ACCT_NBR").isNotNull() &
        (trim(col("LN_ACCT_NBR")) != "") &
        col("BORR_ID").isNotNull()
    ).drop("_corrupt_record")

    logger.info(f"Valid records for transformation: {valid.count()}")
    return valid


def resolve_foreign_keys(spark, df):
    """
    Resolve legacy string IDs to modern surrogate keys via lookup joins.
    - BORR_ID → borrowers.id (via borrowers.external_id)
    - PROD_CD → loan_products.id (via loan_products.code)
    """
    logger.info("Resolving foreign keys...")

    # Load lookup tables from already-ingested Delta tables
    borrowers_lookup = (
        spark.table("loan_warehouse.borrowers")
        .select(col("id").alias("borrower_id"), col("external_id"))
    )

    products_lookup = (
        spark.table("loan_warehouse.loan_products")
        .select(col("id").alias("product_id"), col("code"))
    )

    # Join to resolve borrower FK
    df = df.join(borrowers_lookup, df["BORR_ID"] == borrowers_lookup["external_id"], "left")

    # Log any unresolved borrower references
    unresolved_borrowers = df.filter(col("borrower_id").isNull()).count()
    if unresolved_borrowers > 0:
        logger.warning(f"WARNING: {unresolved_borrowers} loan accounts have unresolved borrower_id")

    # Join to resolve product FK
    df = df.join(products_lookup, df["PROD_CD"] == products_lookup["code"], "left")

    # Log any unresolved product references
    unresolved_products = df.filter(col("product_id").isNull()).count()
    if unresolved_products > 0:
        logger.warning(f"WARNING: {unresolved_products} loan accounts have unresolved product_id")

    # Drop the join key columns
    df = df.drop("external_id", "code")

    return df


def transform(df):
    """
    Apply all transformations for CDW_LN_ACCT → loan_accounts:
    - Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
    - Parse amounts from comma-formatted strings to DecimalType
    - Parse dates from MM/DD/YYYY to DateType/TimestampType
    - Parse integer fields (term_months, delinquency_days)
    - Expand status and property type codes
    """
    logger.info("Applying transformations...")

    transformed = (
        df
        # Rename account number
        .withColumnRenamed("LN_ACCT_NBR", "account_number")

        # Parse financial amounts (remove commas, cast to decimal)
        .withColumn("original_amount", parse_amount_string("LN_ORIG_AMT"))
        .withColumn("current_balance",
                    regexp_replace(col("LN_CURR_BAL"), ",", "").cast(DecimalType(12, 2)))
        .withColumn("interest_rate", col("LN_INT_RT").cast(DecimalType(5, 3)))
        .withColumn("term_months", col("LN_TERM_MOS").cast(IntegerType()))
        .withColumn("monthly_payment",
                    regexp_replace(col("LN_PMT_AMT"), ",", "").cast(DecimalType(10, 2)))

        # Parse date strings to DateType
        .withColumn("origination_date", to_date(col("LN_ORIG_DT"), LEGACY_DATE_FORMAT))
        .withColumn("maturity_date", to_date(col("LN_MAT_DT"), LEGACY_DATE_FORMAT))
        .withColumn("first_payment_date", to_date(col("LN_1ST_PMT_DT"), LEGACY_DATE_FORMAT))
        .withColumn("next_payment_date", to_date(col("LN_NXT_PMT_DT"), LEGACY_DATE_FORMAT))

        # Expand loan status code
        .withColumn("status", expand_loan_status("LN_STAT_CD"))

        # Parse delinquency days to integer
        .withColumn("delinquency_days", col("LN_DLQ_DAYS").cast(IntegerType()))

        # Parse escrow balance and LTV
        .withColumn("escrow_balance",
                    regexp_replace(col("LN_ESCROW_BAL"), ",", "").cast(DecimalType(10, 2)))
        .withColumn("ltv_percent", col("LN_LTV_PCT").cast(DecimalType(5, 2)))

        # Property details - rename and expand property type
        .withColumnRenamed("PROP_ADDR_LN1", "property_address")
        .withColumnRenamed("PROP_CTY_NM", "property_city")
        .withColumnRenamed("PROP_ST_CD", "property_state")
        .withColumnRenamed("PROP_ZIP_CD", "property_zip")
        .withColumn("property_type", expand_property_type("PROP_TYP_CD"))

        # Parse appraised value
        .withColumn("appraised_value",
                    regexp_replace(col("PROP_APRS_VAL"), ",", "").cast(DecimalType(12, 2)))

        # Parse audit timestamps
        .withColumn("created_at", to_timestamp(col("LN_CRET_DT"), LEGACY_DATE_FORMAT))
        .withColumn("updated_at", to_timestamp(col("LN_UPDT_DT"), LEGACY_DATE_FORMAT))

        # Drop all original/intermediate columns no longer needed
        .drop("BORR_ID", "BORR_FST_NM", "BORR_LST_NM", "BORR_SSN_LST4", "PROD_CD",
               "LN_ORIG_AMT", "LN_CURR_BAL", "LN_INT_RT", "LN_TERM_MOS", "LN_PMT_AMT",
               "LN_ORIG_DT", "LN_MAT_DT", "LN_1ST_PMT_DT", "LN_NXT_PMT_DT",
               "LN_STAT_CD", "LN_DLQ_DAYS", "LN_ESCROW_BAL", "LN_LTV_PCT",
               "PROP_TYP_CD", "PROP_APRS_VAL", "LN_CRET_DT", "LN_UPDT_DT")
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
    """
    Main entry point for the loan accounts ingestion pipeline.
    Must be run AFTER borrowers and loan_products ingestion to resolve FKs.
    """
    logger.info("=" * 60)
    logger.info("Starting Loan Accounts Ingestion Pipeline")
    logger.info("=" * 60)
    logger.info("NOTE: This script depends on borrowers and loan_products tables")
    logger.info("      being already populated for FK resolution.")

    spark = create_spark_session()
    schema = define_source_schema()

    # Step 1: Read source data
    raw_df = read_source(spark, SOURCE_PATH, schema)
    source_count = raw_df.count()

    # Step 2: Quarantine malformed records
    valid_df = quarantine_malformed(raw_df, QUARANTINE_PATH)

    # Step 3: Resolve foreign keys (borrower_id, product_id)
    resolved_df = resolve_foreign_keys(spark, valid_df)

    # Step 4: Transform to modern schema
    transformed_df = transform(resolved_df)

    # Step 5: Write to Delta Lake
    target_count = write_to_delta(transformed_df, TARGET_TABLE)

    # Step 6: Log reconciliation summary
    logger.info("=" * 60)
    logger.info("Loan Accounts Ingestion Summary")
    logger.info(f"  Source records read:    {source_count}")
    logger.info(f"  Records quarantined:    {source_count - target_count}")
    logger.info(f"  Records written:        {target_count}")
    logger.info("=" * 60)

    spark.stop()


if __name__ == "__main__":
    main()
