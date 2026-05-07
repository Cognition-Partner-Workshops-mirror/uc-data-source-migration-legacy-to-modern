"""
PySpark ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy loan account table and transforms all-VARCHAR columns into
properly typed Delta Lake columns per column_mappings.md.

Key transformations:
- Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  in favor of a borrower_id FK resolved via external_id lookup
- Resolve product_id FK via PROD_CD -> loan_products.code lookup
- Parse all amount/rate/percentage strings to DecimalType
- Parse all date strings (MM/DD/YYYY) to DateType/TimestampType
- Expand loan status codes (ACT -> ACTIVE, CLO -> CLOSED, DFT -> DEFAULT, FRB -> FORBEARANCE)
- Expand property type codes (SFR -> Single Family, CND -> Condominium, etc.)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    read_legacy_csv,
    read_legacy_parquet,
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_integer,
    expand_status_code,
    add_pipeline_metadata,
    log_parse_errors,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/cdw/CDW_LN_ACCT/"
TARGET_TABLE = "loan_warehouse.loan_accounts"
SOURCE_FORMAT = "csv"


def read_source(spark: SparkSession) -> DataFrame:
    """Read the legacy loan account data from the landing zone."""
    if SOURCE_FORMAT == "parquet":
        return read_legacy_parquet(spark, SOURCE_PATH)
    return read_legacy_csv(spark, SOURCE_PATH)


def resolve_borrower_ids(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Resolve legacy BORR_ID strings to modern borrower surrogate keys.

    Joins against the already-loaded borrowers table using external_id.
    Rows with unresolved borrower IDs are flagged (not dropped) so that
    the quality framework can report orphaned loan accounts.
    """
    borrowers = spark.table("loan_warehouse.borrowers").select(
        F.col("id").alias("borrower_id"),
        F.col("external_id"),
    )
    joined = df.join(
        borrowers,
        df["BORR_ID"] == borrowers["external_id"],
        "left"
    )
    # Flag rows where the borrower lookup failed (orphaned loan accounts)
    joined = joined.withColumn(
        "borrower_id_unresolved",
        F.col("borrower_id").isNull() & F.col("BORR_ID").isNotNull()
    )
    return joined.drop("external_id")


def resolve_product_ids(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Resolve legacy PROD_CD strings to modern loan_product surrogate keys.

    Joins against the already-loaded loan_products table using code.
    Unresolved product codes are flagged for quality reporting.
    """
    products = spark.table("loan_warehouse.loan_products").select(
        F.col("id").alias("product_id"),
        F.col("code").alias("product_code"),
    )
    joined = df.join(
        products,
        df["PROD_CD"] == products["product_code"],
        "left"
    )
    # Flag rows where product lookup failed
    joined = joined.withColumn(
        "product_id_unresolved",
        F.col("product_id").isNull() & F.col("PROD_CD").isNotNull()
    )
    return joined.drop("product_code")


def transform(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Apply all transformations from CDW_LN_ACCT to modern loan_accounts schema.

    Must be called after borrowers and loan_products tables are loaded
    because FK resolution depends on those target tables existing.
    """
    # --- Step 1: Resolve FK references (borrower_id, product_id) ---
    resolved = resolve_borrower_ids(spark, df)
    resolved = resolve_product_ids(spark, resolved)

    # --- Step 2: Rename direct-copy columns ---
    resolved = (
        resolved
        .withColumnRenamed("LN_ACCT_NBR", "account_number")
        .withColumnRenamed("PROP_ADDR_LN1", "property_address")
        .withColumnRenamed("PROP_CTY_NM", "property_city")
        .withColumnRenamed("PROP_ST_CD", "property_state")
        .withColumnRenamed("PROP_ZIP_CD", "property_zip")
    )

    # --- Step 3: Parse financial amount strings to DecimalType ---
    resolved = parse_legacy_amount(resolved, "LN_ORIG_AMT", "original_amount")
    resolved = parse_legacy_amount(resolved, "LN_CURR_BAL", "current_balance")
    resolved = parse_legacy_amount(resolved, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    resolved = parse_legacy_amount(resolved, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
    resolved = parse_legacy_amount(resolved, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
    resolved = parse_legacy_amount(resolved, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)
    resolved = parse_legacy_amount(resolved, "PROP_APRS_VAL", "appraised_value")

    # --- Step 4: Parse integer fields ---
    resolved = parse_legacy_integer(resolved, "LN_TERM_MOS", "term_months")
    resolved = parse_legacy_integer(resolved, "LN_DLQ_DAYS", "delinquency_days")

    # --- Step 5: Parse date strings to DateType ---
    resolved = parse_legacy_date(resolved, "LN_ORIG_DT", "origination_date")
    resolved = parse_legacy_date(resolved, "LN_MAT_DT", "maturity_date")
    resolved = parse_legacy_date(resolved, "LN_1ST_PMT_DT", "first_payment_date")
    resolved = parse_legacy_date(resolved, "LN_NXT_PMT_DT", "next_payment_date")

    # --- Step 6: Parse audit timestamps ---
    resolved = parse_legacy_timestamp(resolved, "LN_CRET_DT", "created_at")
    resolved = parse_legacy_timestamp(resolved, "LN_UPDT_DT", "updated_at")

    # --- Step 7: Expand loan status code ---
    resolved = expand_status_code(resolved, "LN_STAT_CD", "status", LOAN_STATUS_MAP)

    # --- Step 8: Expand property type code ---
    resolved = expand_status_code(resolved, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)

    # --- Step 9: Add pipeline metadata ---
    resolved = add_pipeline_metadata(resolved, "CDW_LN_ACCT")

    # --- Step 10: Select final columns (drops denormalized borrower fields) ---
    result = resolved.select(
        "account_number",
        "borrower_id",
        "product_id",
        "original_amount",
        "current_balance",
        "interest_rate",
        "term_months",
        "monthly_payment",
        "origination_date",
        "maturity_date",
        "first_payment_date",
        "next_payment_date",
        "status",
        "delinquency_days",
        "escrow_balance",
        "ltv_percent",
        "property_address",
        "property_city",
        "property_state",
        "property_zip",
        "property_type",
        "appraised_value",
        "created_at",
        "updated_at",
        "_ingested_at",
        "_source_system",
    )

    return result


def load(df: DataFrame):
    """Write the transformed loan account data to the Delta Lake target table."""
    (
        df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("status")
        .saveAsTable(TARGET_TABLE)
    )


def run(spark: SparkSession):
    """Main entry point: read -> transform (with FK resolution) -> load."""
    raw_df = read_source(spark)
    transformed_df = transform(spark, raw_df)

    # Log parse/resolution issues before loading
    log_parse_errors(transformed_df, "loan_accounts", [
        "borrower_id_unresolved",
        "product_id_unresolved",
        "original_amount_parse_error",
        "current_balance_parse_error",
        "interest_rate_parse_error",
        "monthly_payment_parse_error",
        "escrow_balance_parse_error",
        "ltv_percent_parse_error",
        "appraised_value_parse_error",
        "term_months_parse_error",
        "delinquency_days_parse_error",
        "origination_date_parse_error",
        "maturity_date_parse_error",
        "first_payment_date_parse_error",
        "next_payment_date_parse_error",
        "status_unmapped",
        "property_type_unmapped",
        "created_at_parse_error",
        "updated_at_parse_error",
    ])

    load(transformed_df)
    print(f"[loan_accounts] Ingestion complete. Rows written: {transformed_df.count()}")


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_LN_ACCT_Ingestion").getOrCreate()
    run(spark)
