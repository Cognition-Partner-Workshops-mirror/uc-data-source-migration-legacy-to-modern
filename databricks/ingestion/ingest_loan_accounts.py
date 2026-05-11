"""
ingest_loan_accounts.py — PySpark ingestion for CDW_LN_ACCT → loan_accounts.

Reads the legacy loan account data (which includes denormalized borrower
fields), applies all transformations from column_mappings.md, resolves
foreign keys to the borrowers and loan_products dimension tables, and
writes to the Delta Lake `loan_warehouse.loan_accounts` table.

Key transformations:
  - Drop denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  - Resolve BORR_ID → borrowers.id via lookup
  - Resolve PROD_CD → loan_products.id via lookup
  - Parse dates, amounts, rates, and integers from VARCHAR strings
  - Expand status codes: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
  - Expand property type codes: SFR→Single Family, CND→Condominium, etc.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
import logging

from common_transforms import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_code_col,
    log_null_counts,
    add_ingestion_metadata,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

logger = logging.getLogger("cdw_migration.loan_accounts")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/legacy-extract/CDW_LN_ACCT"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"


def read_source(spark: SparkSession) -> "DataFrame":
    """Read the legacy CDW_LN_ACCT extract (CSV or Parquet)."""
    if SOURCE_FORMAT == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "NULL")
            .option("emptyValue", "")
            .csv(SOURCE_PATH)
        )
    else:
        df = spark.read.parquet(SOURCE_PATH)

    logger.info("Read %d rows from %s (%s)", df.count(), SOURCE_PATH, SOURCE_FORMAT)
    return df


def resolve_foreign_keys(df: "DataFrame", spark: SparkSession) -> "DataFrame":
    """Resolve legacy string IDs to modern surrogate BIGINT keys.

    - BORR_ID → borrowers.id  (via borrowers.external_id)
    - PROD_CD → loan_products.id  (via loan_products.code)

    Rows with unresolvable keys are kept (with NULL FK) and flagged
    in the quality checks — we never silently drop records.
    """
    # Load borrower lookup table
    borrower_lookup = (
        spark.table("loan_warehouse.borrowers")
        .select(
            F.col("id").alias("borrower_id"),
            F.col("external_id").alias("_borr_ext_id"),
        )
    )

    # Load product lookup table
    product_lookup = (
        spark.table("loan_warehouse.loan_products")
        .select(
            F.col("id").alias("product_id"),
            F.col("code").alias("_prod_code"),
        )
    )

    # Left join to preserve all loan records even if FK cannot be resolved
    df = df.join(borrower_lookup, df["BORR_ID"] == borrower_lookup["_borr_ext_id"], "left")
    df = df.drop("_borr_ext_id")

    df = df.join(product_lookup, df["PROD_CD"] == product_lookup["_prod_code"], "left")
    df = df.drop("_prod_code")

    # Log any unresolved foreign keys
    unresolved_borr = df.filter(F.col("borrower_id").isNull()).count()
    unresolved_prod = df.filter(F.col("product_id").isNull()).count()
    if unresolved_borr > 0:
        logger.warning("%d loan accounts have unresolved borrower_id (BORR_ID not in borrowers)", unresolved_borr)
    if unresolved_prod > 0:
        logger.warning("%d loan accounts have unresolved product_id (PROD_CD not in loan_products)", unresolved_prod)

    return df


def transform(df: "DataFrame", spark: SparkSession) -> "DataFrame":
    """Apply all column mappings, type conversions, and FK resolution."""

    # --- Resolve foreign keys first (needs original BORR_ID and PROD_CD) ---
    df = resolve_foreign_keys(df, spark)

    # --- Date columns ---
    df = parse_date_col(df, "LN_ORIG_DT", "origination_date")
    df = parse_date_col(df, "LN_MAT_DT", "maturity_date")
    df = parse_date_col(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date_col(df, "LN_NXT_PMT_DT", "next_payment_date")
    df = parse_timestamp_col(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "LN_UPDT_DT", "updated_at")

    # --- Amount / decimal columns ---
    df = parse_amount_col(df, "LN_ORIG_AMT", "original_amount", 12, 2)
    df = parse_amount_col(df, "LN_CURR_BAL", "current_balance", 12, 2)
    df = parse_amount_col(df, "LN_PMT_AMT", "monthly_payment", 10, 2)
    df = parse_amount_col(df, "LN_ESCROW_BAL", "escrow_balance", 10, 2)
    df = parse_amount_col(df, "PROP_APRS_VAL", "appraised_value", 12, 2)

    # --- Rate and percentage columns ---
    df = parse_amount_col(df, "LN_INT_RT", "interest_rate", 5, 3)
    df = parse_amount_col(df, "LN_LTV_PCT", "ltv_percent", 5, 2)

    # --- Integer columns ---
    df = parse_int_col(df, "LN_TERM_MOS", "term_months")
    df = parse_int_col(df, "LN_DLQ_DAYS", "delinquency_days")

    # --- Status / type code expansion ---
    df = expand_code_col(df, "LN_STAT_CD", "status", LOAN_STATUS_MAP)
    df = expand_code_col(df, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP, default="Other")

    # --- Direct-copy renames ---
    df = (
        df
        .withColumnRenamed("LN_ACCT_NBR", "account_number")
        .withColumnRenamed("PROP_ADDR_LN1", "property_address")
        .withColumnRenamed("PROP_CTY_NM", "property_city")
        .withColumnRenamed("PROP_ST_CD", "property_state")
        .withColumnRenamed("PROP_ZIP_CD", "property_zip")
    )

    # --- Drop legacy columns (denormalized borrower fields + originals) ---
    cols_to_drop = [
        "BORR_ID", "BORR_FST_NM", "BORR_LST_NM", "BORR_SSN_LST4", "PROD_CD",
        "LN_ORIG_DT", "LN_MAT_DT", "LN_1ST_PMT_DT", "LN_NXT_PMT_DT",
        "LN_CRET_DT", "LN_UPDT_DT", "LN_ORIG_AMT", "LN_CURR_BAL",
        "LN_PMT_AMT", "LN_ESCROW_BAL", "PROP_APRS_VAL", "LN_INT_RT",
        "LN_LTV_PCT", "LN_TERM_MOS", "LN_DLQ_DAYS", "LN_STAT_CD",
        "PROP_TYP_CD",
    ]
    df = df.drop(*cols_to_drop)

    # --- Add ingestion metadata ---
    df = add_ingestion_metadata(df, "CDW_LN_ACCT")

    # --- Select final column order ---
    df = df.select(
        "account_number",
        "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment",
        "origination_date", "maturity_date", "first_payment_date", "next_payment_date",
        "status", "delinquency_days",
        "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state", "property_zip",
        "property_type", "appraised_value",
        "created_at", "updated_at",
        "_ingestion_ts", "_source_system",
    )

    return df


def validate_pre_write(df: "DataFrame") -> None:
    """Log NULL counts on critical fields before writing."""
    critical_cols = [
        "account_number", "borrower_id", "product_id", "status",
        "original_amount", "current_balance", "origination_date",
    ]
    log_null_counts(df, critical_cols, TARGET_TABLE)


def write_target(df: "DataFrame") -> None:
    """Write loan accounts to Delta Lake with MERGE upsert on account_number."""
    from delta.tables import DeltaTable

    spark = df.sparkSession
    if DeltaTable.isDeltaTable(spark, TARGET_TABLE):
        target = DeltaTable.forName(spark, TARGET_TABLE)
        (
            target.alias("tgt")
            .merge(df.alias("src"), "tgt.account_number = src.account_number")
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )
        logger.info("MERGE completed into %s", TARGET_TABLE)
    else:
        (
            df.write
            .format("delta")
            .mode("overwrite")
            .partitionBy("status")
            .saveAsTable(TARGET_TABLE)
        )
        logger.info("Initial load completed into %s", TARGET_TABLE)


def main():
    """Entry point — orchestrates read → transform → validate → write."""
    spark = SparkSession.builder.appName("CDW Migration — Loan Accounts").getOrCreate()
    logger.info("Starting loan accounts ingestion from %s", SOURCE_PATH)

    raw_df = read_source(spark)
    transformed_df = transform(raw_df, spark)
    validate_pre_write(transformed_df)
    write_target(transformed_df)

    logger.info("Loan accounts ingestion complete. Rows written: %d", transformed_df.count())


if __name__ == "__main__":
    main()
