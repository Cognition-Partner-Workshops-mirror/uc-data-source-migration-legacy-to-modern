"""
Ingestion script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads the legacy loan accounts table (simulated as CSV/Parquet),
applies all transformations from column_mappings.md, resolves
FK references to borrowers and loan_products, and writes to the
modern Delta Lake loan_accounts table.

Execution order: Run THIRD — depends on borrowers and loan_products
being loaded first for FK resolution.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_integer,
    parse_legacy_amount,
    parse_legacy_decimal,
    expand_loan_status,
    expand_property_type,
)

# =============================================================================
# Configuration
# =============================================================================
LEGACY_SOURCE_PATH = "/mnt/legacy-data/CDW_LN_ACCT"
LEGACY_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_PATH = "/mnt/migration/quarantine/loan_accounts"


def read_legacy_loan_accounts(spark: SparkSession) -> DataFrame:
    """Read legacy loan account data. All columns as STRING."""
    return (
        spark.read
        .format(LEGACY_SOURCE_FORMAT)
        .option("header", "true")
        .option("inferSchema", "false")
        .load(LEGACY_SOURCE_PATH)
    )


def transform_loan_accounts(df: DataFrame, borrowers_df: DataFrame,
                             products_df: DataFrame) -> DataFrame:
    """
    Apply all transformations from column_mappings.md § CDW_LN_ACCT → loan_accounts.

    Key operations:
    - Drops denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
    - Resolves BORR_ID → borrower_id via borrowers.external_id lookup
    - Resolves PROD_CD → product_id via loan_products.code lookup
    - Parses all VARCHAR amounts/dates to proper types
    - Expands status and property type codes
    """
    # Build lookup DataFrames for FK resolution
    borrower_lookup = borrowers_df.select(
        F.col("borrower_id"),
        F.col("external_id").alias("_borr_ext_id")
    )
    product_lookup = products_df.select(
        F.col("product_id"),
        F.col("code").alias("_prod_code")
    )

    # Join legacy data with lookups to resolve FKs
    resolved = (
        df
        .join(borrower_lookup, df["BORR_ID"] == borrower_lookup["_borr_ext_id"], "left")
        .join(product_lookup, df["PROD_CD"] == product_lookup["_prod_code"], "left")
    )

    transformed = resolved.select(
        F.col("LN_ACCT_NBR").alias("account_number"),

        # FK resolution — borrower_id and product_id from lookup joins
        F.col("borrower_id"),
        F.col("product_id"),

        # Amount parsing: VARCHAR with commas → DECIMAL
        parse_legacy_amount(F.col("LN_ORIG_AMT")).alias("original_amount"),
        parse_legacy_amount(F.col("LN_CURR_BAL")).alias("current_balance"),
        parse_legacy_decimal(F.col("LN_INT_RT"), 5, 3).alias("interest_rate"),
        parse_legacy_integer(F.col("LN_TERM_MOS")).alias("term_months"),
        parse_legacy_amount(F.col("LN_PMT_AMT"), 10, 2).alias("monthly_payment"),

        # Date parsing: MM/DD/YYYY string → DATE
        parse_legacy_date(F.col("LN_ORIG_DT")).alias("origination_date"),
        parse_legacy_date(F.col("LN_MAT_DT")).alias("maturity_date"),
        parse_legacy_date(F.col("LN_1ST_PMT_DT")).alias("first_payment_date"),
        parse_legacy_date(F.col("LN_NXT_PMT_DT")).alias("next_payment_date"),

        # Status expansion
        expand_loan_status(F.col("LN_STAT_CD")).alias("status"),

        # Numeric parsing
        parse_legacy_integer(F.col("LN_DLQ_DAYS")).alias("delinquency_days"),
        parse_legacy_amount(F.col("LN_ESCROW_BAL"), 10, 2).alias("escrow_balance"),
        parse_legacy_decimal(F.col("LN_LTV_PCT"), 5, 2).alias("ltv_percent"),

        # Property fields
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_property_type(F.col("PROP_TYP_CD")).alias("property_type"),
        parse_legacy_amount(F.col("PROP_APRS_VAL")).alias("appraised_value"),

        # Timestamps
        parse_legacy_timestamp(F.col("LN_CRET_DT")).alias("created_at"),
        parse_legacy_timestamp(F.col("LN_UPDT_DT")).alias("updated_at"),
    )

    return transformed


def quarantine_invalid_records(df: DataFrame) -> tuple:
    """
    Separate valid from invalid records.
    Required: account_number, borrower_id (FK resolved), product_id (FK resolved),
    original_amount, current_balance, interest_rate, status.
    Records with unresolved FKs (null borrower_id or product_id) are quarantined.
    """
    required_fields = [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate", "status"
    ]

    null_condition = F.lit(False)
    for field in required_fields:
        null_condition = null_condition | F.col(field).isNull()

    valid_df = df.filter(~null_condition)
    quarantine_df = df.filter(null_condition)
    return valid_df, quarantine_df


def run_ingestion():
    """Main ingestion entry point. Requires borrowers and loan_products to be loaded first."""
    spark = SparkSession.builder.appName("Ingest CDW_LN_ACCT → loan_accounts").getOrCreate()

    print("=" * 60)
    print("INGESTION: CDW_LN_ACCT → loan_warehouse.loan_accounts")
    print("=" * 60)

    # Read lookup tables (must be populated by prior ingestion steps)
    borrowers_df = spark.table("loan_warehouse.borrowers")
    products_df = spark.table("loan_warehouse.loan_products")
    print(f"Borrowers loaded for FK resolution: {borrowers_df.count()}")
    print(f"Products loaded for FK resolution: {products_df.count()}")

    legacy_df = read_legacy_loan_accounts(spark)
    source_count = legacy_df.count()
    print(f"Source records read: {source_count}")

    transformed_df = transform_loan_accounts(legacy_df, borrowers_df, products_df)
    valid_df, quarantine_df = quarantine_invalid_records(transformed_df)
    quarantine_count = quarantine_df.count()
    valid_count = valid_df.count()

    if quarantine_count > 0:
        print(f"WARNING: {quarantine_count} record(s) quarantined (likely unresolved FKs)")
        quarantine_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)
    else:
        print("All records passed validation and FK resolution")

    valid_df.write.mode("overwrite").format("delta").saveAsTable(TARGET_TABLE)
    print(f"Target records written: {valid_count}")
    print(f"Reconciliation: {source_count} → {valid_count} (+{quarantine_count} quarantined)")


if __name__ == "__main__":
    run_ingestion()
