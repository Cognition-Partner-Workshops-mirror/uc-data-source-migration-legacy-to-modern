"""
Ingest legacy CDW_LN_ACCT data into modern Delta Lake loan_accounts table.

Key transformations:
  - Drops denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  - Resolves borrower_id FK via BORR_ID -> borrowers.external_id lookup
  - Resolves product_id FK via PROD_CD -> loan_products.code lookup
  - Expands status codes (ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE)
  - Expands property type codes (SFR->Single Family, CND->Condominium, etc.)
  - Derives origination_year partition column from LN_ORIG_DT

Source: CSV/Parquet export of CDW_LN_ACCT
Target: loan_warehouse.loan_accounts (Delta Lake)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transformations import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    parse_int_col,
    expand_status_col,
    flag_parse_failures,
    quarantine_bad_records,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy-exports/CDW_LN_ACCT/"
LEGACY_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_migration.loan_warehouse.loan_accounts"
BORROWER_TABLE = "loan_migration.loan_warehouse.borrowers"
PRODUCT_TABLE = "loan_migration.loan_warehouse.loan_products"
QUARANTINE_PATH = "dbfs:/mnt/migration-quarantine/loan_accounts/"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "nullValue": "",
    "emptyValue": "",
}


def read_legacy_accounts(spark: SparkSession) -> DataFrame:
    """Read legacy loan account data."""
    reader = spark.read.format(LEGACY_SOURCE_FORMAT)
    if LEGACY_SOURCE_FORMAT == "csv":
        reader = reader.options(**CSV_OPTIONS)
    return reader.load(LEGACY_SOURCE_PATH)


def resolve_borrower_fk(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join with borrowers table to resolve BORR_ID -> borrower_id FK."""
    borrowers = (
        spark.table(BORROWER_TABLE)
        .select(
            F.col("borrower_id").alias("_resolved_borrower_id"),
            F.col("external_id").alias("_borr_ext_id"),
        )
    )
    df = df.join(
        borrowers,
        df["BORR_ID"] == borrowers["_borr_ext_id"],
        "left"
    )
    df = df.withColumn("borrower_id", F.col("_resolved_borrower_id"))
    df = df.withColumn(
        "_bad_borrower_fk",
        F.when(
            F.col("BORR_ID").isNotNull() & F.col("borrower_id").isNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    return df.drop("_resolved_borrower_id", "_borr_ext_id")


def resolve_product_fk(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join with loan_products table to resolve PROD_CD -> product_id FK."""
    products = (
        spark.table(PRODUCT_TABLE)
        .select(
            F.col("product_id").alias("_resolved_product_id"),
            F.col("code").alias("_prod_code"),
        )
    )
    df = df.join(
        products,
        df["PROD_CD"] == products["_prod_code"],
        "left"
    )
    df = df.withColumn("product_id", F.col("_resolved_product_id"))
    df = df.withColumn(
        "_bad_product_fk",
        F.when(
            F.col("PROD_CD").isNotNull() & F.col("product_id").isNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    return df.drop("_resolved_product_id", "_prod_code")


def transform_accounts(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Apply all transformations from legacy CDW_LN_ACCT to modern loan_accounts."""

    # --- Date columns ---
    df = parse_date_col(df, "LN_ORIG_DT", "origination_date")
    df = parse_date_col(df, "LN_MAT_DT", "maturity_date")
    df = parse_date_col(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date_col(df, "LN_NXT_PMT_DT", "next_payment_date")
    df = parse_timestamp_col(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "LN_UPDT_DT", "updated_at")

    # --- Amount columns ---
    df = parse_amount_col(df, "LN_ORIG_AMT", "original_amount")
    df = parse_amount_col(df, "LN_CURR_BAL", "current_balance")
    df = parse_amount_col(df, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    df = parse_amount_col(df, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
    df = parse_amount_col(df, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
    df = parse_amount_col(df, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)
    df = parse_amount_col(df, "PROP_APRS_VAL", "appraised_value")

    # --- Integer columns ---
    df = parse_int_col(df, "LN_TERM_MOS", "term_months")
    df = parse_int_col(df, "LN_DLQ_DAYS", "delinquency_days")

    # --- Status expansion ---
    df = expand_status_col(df, "LN_STAT_CD", "status", LOAN_STATUS_MAP)
    df = expand_status_col(df, "PROP_TYP_CD", "property_type", PROPERTY_TYPE_MAP)

    # --- Derived partition column ---
    df = df.withColumn("origination_year", F.year(F.col("origination_date")))

    # --- FK resolution ---
    df = resolve_borrower_fk(spark, df)
    df = resolve_product_fk(spark, df)

    # --- Direct-copy renames ---
    df = (
        df
        .withColumn("account_number", F.col("LN_ACCT_NBR"))
        .withColumn("property_address", F.col("PROP_ADDR_LN1"))
        .withColumn("property_city", F.col("PROP_CTY_NM"))
        .withColumn("property_state", F.col("PROP_ST_CD"))
        .withColumn("property_zip", F.col("PROP_ZIP_CD"))
    )

    # --- Parse failure flags ---
    df = flag_parse_failures(df, "LN_ORIG_DT", "origination_date", "_bad_orig_dt")
    df = flag_parse_failures(df, "LN_ORIG_AMT", "original_amount", "_bad_orig_amt")
    df = flag_parse_failures(df, "LN_CURR_BAL", "current_balance", "_bad_curr_bal")

    # --- Lineage ---
    df = (
        df
        .withColumn("_migration_source", F.lit("CDW_LN_ACCT"))
        .withColumn("_migrated_at", F.current_timestamp())
    )

    return df


def run_account_ingestion(spark: SparkSession) -> dict:
    """Execute loan account ingestion pipeline."""
    print("=" * 60)
    print("LOAN ACCOUNT INGESTION: CDW_LN_ACCT -> loan_accounts")
    print("=" * 60)

    raw_df = read_legacy_accounts(spark)
    source_count = raw_df.count()
    print(f"Source records read: {source_count}")

    transformed_df = transform_accounts(spark, raw_df)

    quarantine_flags = [
        "_bad_orig_dt", "_bad_orig_amt", "_bad_curr_bal",
        "_bad_borrower_fk", "_bad_product_fk",
    ]
    good_df, bad_df = quarantine_bad_records(transformed_df, quarantine_flags)
    bad_count = bad_df.count()
    if bad_count > 0:
        print(f"WARNING: {bad_count} records quarantined (parse failures or FK mismatches)")
        bad_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)
    else:
        print("No records quarantined")

    final_columns = [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date",
        "first_payment_date", "next_payment_date", "status",
        "delinquency_days", "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state",
        "property_zip", "property_type", "appraised_value",
        "origination_year",
        "created_at", "updated_at", "_migration_source", "_migrated_at",
    ]
    output_df = good_df.select(*final_columns)

    (
        output_df
        .write
        .format("delta")
        .mode("overwrite")
        .partitionBy("status", "origination_year")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    target_count = spark.table(TARGET_TABLE).count()
    print(f"Target records written: {target_count}")
    print("Loan account ingestion complete.")

    return {
        "source_count": source_count,
        "target_count": target_count,
        "quarantined_count": bad_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_Accounts").getOrCreate()
    stats = run_account_ingestion(spark)
    print(f"\nFinal stats: {stats}")
