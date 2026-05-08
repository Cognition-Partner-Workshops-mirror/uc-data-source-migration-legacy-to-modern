"""
PySpark Ingestion Script: CDW_LN_ACCT -> loan_accounts
=======================================================
Reads legacy denormalized loan account data, drops the redundant borrower
columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4), resolves foreign keys
to borrowers and loan_products dimension tables, converts all-VARCHAR columns
to proper types, expands status and property type codes, and writes to the
Delta Lake loan_accounts table.

Key Transformations:
  - Denormalized borrower fields dropped; BORR_ID resolved to borrowers.id FK
  - PROD_CD resolved to loan_products.id FK
  - Amount strings (commas) -> DECIMAL
  - Date strings (MM/DD/YYYY) -> DATE / TIMESTAMP
  - LN_STAT_CD: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE
  - PROP_TYP_CD: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, DecimalType
import logging

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "/mnt/legacy-data/CDW_LN_ACCT"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_accounts"

# Status code expansion per column_mappings.md
LOAN_STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Property type code expansion per column_mappings.md
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

logger = logging.getLogger("ingest_loan_accounts")
logging.basicConfig(level=logging.INFO)


def read_legacy_source(spark: SparkSession, path: str) -> DataFrame:
    """Read legacy CDW_LN_ACCT data from CSV or Parquet source files."""
    try:
        df = spark.read.parquet(path)
        logger.info("Read legacy loan account data from Parquet: %s", path)
    except Exception:
        df = spark.read.option("header", "true").option("inferSchema", "false").csv(path)
        logger.info("Read legacy loan account data from CSV: %s", path)
    logger.info("Source row count: %d", df.count())
    return df


def parse_legacy_date(col_name: str):
    """Convert MM/DD/YYYY VARCHAR string to DateType."""
    return F.to_date(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_timestamp(col_name: str):
    """Convert MM/DD/YYYY VARCHAR string to TimestampType."""
    return F.to_timestamp(F.col(col_name), "MM/dd/yyyy")


def parse_legacy_amount(col_name: str, precision: int = 12, scale: int = 2):
    """Remove commas and dollar signs from VARCHAR amount, cast to DecimalType."""
    return F.regexp_replace(F.col(col_name), "[,$]", "").cast(DecimalType(precision, scale))


def expand_code(col_name: str, mapping: dict):
    """Expand abbreviated codes using a mapping dictionary.

    Unknown codes are preserved as-is so they surface in quality checks.
    """
    expr = F.col(col_name)
    for code, expanded in mapping.items():
        expr = F.when(F.col(col_name) == code, F.lit(expanded)).otherwise(expr)
    return expr


def resolve_borrower_fk(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Resolve legacy BORR_ID to borrowers.id via lookup join.

    Records whose BORR_ID has no match in borrowers are flagged with
    borrower_id = -1 so they surface in referential integrity checks.
    """
    borrower_lookup = (
        spark.table("loan_warehouse.borrowers")
        .select(
            F.col("id").alias("_borrower_pk"),
            F.col("external_id").alias("_borr_ext_id")
        )
    )
    joined = df.join(
        borrower_lookup,
        df["BORR_ID"] == borrower_lookup["_borr_ext_id"],
        "left"
    )
    # Flag orphaned references with -1 instead of dropping them
    resolved = joined.withColumn(
        "borrower_id",
        F.coalesce(F.col("_borrower_pk"), F.lit(-1))
    ).drop("_borrower_pk", "_borr_ext_id")

    orphan_count = resolved.filter(F.col("borrower_id") == -1).count()
    if orphan_count > 0:
        logger.warning("Found %d loan accounts with orphaned BORR_ID references", orphan_count)

    return resolved


def resolve_product_fk(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Resolve legacy PROD_CD to loan_products.id via lookup join.

    Records whose PROD_CD has no match are flagged with product_id = -1.
    """
    product_lookup = (
        spark.table("loan_warehouse.loan_products")
        .select(
            F.col("id").alias("_product_pk"),
            F.col("code").alias("_prod_code")
        )
    )
    joined = df.join(
        product_lookup,
        df["PROD_CD"] == product_lookup["_prod_code"],
        "left"
    )
    resolved = joined.withColumn(
        "product_id",
        F.coalesce(F.col("_product_pk"), F.lit(-1))
    ).drop("_product_pk", "_prod_code")

    orphan_count = resolved.filter(F.col("product_id") == -1).count()
    if orphan_count > 0:
        logger.warning("Found %d loan accounts with orphaned PROD_CD references", orphan_count)

    return resolved


def transform_loan_accounts(df: DataFrame) -> DataFrame:
    """Apply all column transformations per data/mappings/column_mappings.md.

    Denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
    are dropped since borrower_id FK now points to the borrowers dimension.
    """
    return (
        df
        .withColumn("account_number", F.col("LN_ACCT_NBR"))
        # borrower_id and product_id already resolved before this step
        # Financial fields: strip commas, parse to decimal
        .withColumn("original_amount", parse_legacy_amount("LN_ORIG_AMT"))
        .withColumn("current_balance", parse_legacy_amount("LN_CURR_BAL"))
        .withColumn("interest_rate", parse_legacy_amount("LN_INT_RT", 5, 3))
        .withColumn("term_months", F.col("LN_TERM_MOS").cast(IntegerType()))
        .withColumn("monthly_payment", parse_legacy_amount("LN_PMT_AMT", 10, 2))
        # Date fields: MM/DD/YYYY -> DATE
        .withColumn("origination_date", parse_legacy_date("LN_ORIG_DT"))
        .withColumn("maturity_date", parse_legacy_date("LN_MAT_DT"))
        .withColumn("first_payment_date", parse_legacy_date("LN_1ST_PMT_DT"))
        .withColumn("next_payment_date", parse_legacy_date("LN_NXT_PMT_DT"))
        # Status code expansion
        .withColumn("status", expand_code("LN_STAT_CD", LOAN_STATUS_MAP))
        .withColumn("delinquency_days", F.coalesce(F.col("LN_DLQ_DAYS").cast(IntegerType()), F.lit(0)))
        # Escrow and LTV
        .withColumn("escrow_balance", parse_legacy_amount("LN_ESCROW_BAL", 10, 2))
        .withColumn("ltv_percent", parse_legacy_amount("LN_LTV_PCT", 5, 2))
        # Property details
        .withColumn("property_address", F.col("PROP_ADDR_LN1"))
        .withColumn("property_city", F.col("PROP_CTY_NM"))
        .withColumn("property_state", F.col("PROP_ST_CD"))
        .withColumn("property_zip", F.col("PROP_ZIP_CD"))
        .withColumn("property_type", expand_code("PROP_TYP_CD", PROPERTY_TYPE_MAP))
        .withColumn("appraised_value", parse_legacy_amount("PROP_APRS_VAL"))
        # Audit timestamps
        .withColumn("created_at", parse_legacy_timestamp("LN_CRET_DT"))
        .withColumn("updated_at", parse_legacy_timestamp("LN_UPDT_DT"))
        # Lineage metadata
        .withColumn("_legacy_source", F.lit("CDW_LN_ACCT"))
        .withColumn("_ingested_at", F.current_timestamp())
        # Select only modern columns; drops denormalized BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4
        .select(
            "account_number", "borrower_id", "product_id",
            "original_amount", "current_balance", "interest_rate",
            "term_months", "monthly_payment",
            "origination_date", "maturity_date", "first_payment_date", "next_payment_date",
            "status", "delinquency_days",
            "escrow_balance", "ltv_percent",
            "property_address", "property_city", "property_state", "property_zip",
            "property_type", "appraised_value",
            "created_at", "updated_at",
            "_legacy_source", "_ingested_at"
        )
    )


def quarantine_bad_records(df: DataFrame) -> tuple:
    """Separate records with null required fields or orphaned FK references.

    Orphaned references are flagged with -1 during FK resolution.
    Returns (good_df, bad_df).
    """
    valid_record = (
        F.col("account_number").isNotNull()
        & F.col("borrower_id").isNotNull()
        & (F.col("borrower_id") != -1)
        & F.col("product_id").isNotNull()
        & (F.col("product_id") != -1)
        & F.col("original_amount").isNotNull()
        & F.col("current_balance").isNotNull()
        & F.col("interest_rate").isNotNull()
        & F.col("origination_date").isNotNull()
        & F.col("status").isNotNull()
    )

    good_df = df.filter(valid_record)
    bad_df = df.filter(~valid_record)

    bad_count = bad_df.count()
    if bad_count > 0:
        logger.warning("Quarantined %d loan account records", bad_count)

    return good_df, bad_df


def write_to_delta(df: DataFrame, table: str, mode: str = "overwrite"):
    """Write DataFrame to a Delta Lake table."""
    df.write.format("delta").mode(mode).saveAsTable(table)
    logger.info("Wrote %d rows to %s", df.count(), table)


def run(spark: SparkSession):
    """Main entry point: read -> resolve FKs -> transform -> quarantine -> write.

    IMPORTANT: This script must run AFTER ingest_borrowers.py and
    ingest_loan_products.py because it resolves foreign keys against those
    dimension tables.
    """
    logger.info("=== Starting loan account ingestion ===")

    # Step 1: Read legacy source
    raw_df = read_legacy_source(spark, LEGACY_SOURCE_PATH)

    # Step 2: Resolve foreign keys against already-loaded dimension tables
    with_borrower = resolve_borrower_fk(raw_df, spark)
    with_fks = resolve_product_fk(with_borrower, spark)

    # Step 3: Transform columns to modern types
    transformed_df = transform_loan_accounts(with_fks)

    # Step 4: Quarantine bad records
    good_df, bad_df = quarantine_bad_records(transformed_df)

    # Step 5: Write to Delta
    write_to_delta(good_df, TARGET_TABLE, mode="overwrite")
    if bad_df.count() > 0:
        write_to_delta(bad_df, QUARANTINE_TABLE, mode="overwrite")

    logger.info("=== Loan account ingestion complete ===")


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestLoanAccounts").getOrCreate()
    run(spark)
