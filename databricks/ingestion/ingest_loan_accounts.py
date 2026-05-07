"""
Ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy loan accounts extract, applies column renaming, type
conversions, status/property-type expansion, drops denormalized borrower
fields, and resolves foreign keys to borrowers and loan_products dimension
tables. Writes to the Delta Lake loan_accounts table.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_codes,
    parse_amount,
    parse_amount_10_2,
    parse_int,
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_percent,
    parse_rate,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "/mnt/landing/cdw_ln_acct/"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_PATH = "/mnt/quarantine/cdw_ln_acct/"


def read_source(spark: SparkSession, path: str) -> DataFrame:
    """Read legacy loan accounts extract."""
    try:
        return spark.read.parquet(path)
    except Exception:
        return spark.read.option("header", "true").option("inferSchema", "false").csv(path)


def resolve_foreign_keys(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join to borrowers and loan_products to resolve surrogate keys.

    If the dimension tables have not yet been loaded, falls back to keeping
    the legacy string IDs in temporary columns so the pipeline does not fail.
    """
    # --- Resolve borrower_key ---
    try:
        borrowers = spark.table("loan_warehouse.borrowers").select(
            F.col("borrower_key"), F.col("external_id")
        )
        df = (
            df.join(
                borrowers,
                df["_legacy_borr_id"] == borrowers["external_id"],
                "left",
            )
            .drop("external_id")
        )
    except Exception as e:
        print(f"WARNING: Could not resolve borrower FK: {e}")
        df = df.withColumn("borrower_key", F.lit(None).cast("bigint"))

    # --- Resolve product_key ---
    try:
        products = spark.table("loan_warehouse.loan_products").select(
            F.col("product_key"), F.col("code")
        )
        df = (
            df.join(
                products,
                df["_legacy_prod_cd"] == products["code"],
                "left",
            )
            .drop("code")
        )
    except Exception as e:
        print(f"WARNING: Could not resolve product FK: {e}")
        df = df.withColumn("product_key", F.lit(None).cast("bigint"))

    # Tag unresolved FK rows
    df = df.withColumn(
        "_fk_unresolved",
        F.col("borrower_key").isNull() | F.col("product_key").isNull(),
    )

    return df


def transform_loan_accounts(
    spark: SparkSession, raw: DataFrame
) -> tuple[DataFrame, DataFrame]:
    """Apply column mappings, type conversions, FK resolution."""
    # Phase 1: rename and convert columns
    transformed = raw.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("_legacy_borr_id"),
        F.col("PROD_CD").alias("_legacy_prod_cd"),
        # Drop denormalized borrower fields: BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4
        parse_amount("LN_ORIG_AMT", "original_amount"),
        parse_amount("LN_CURR_BAL", "current_balance"),
        parse_rate("LN_INT_RT", "interest_rate"),
        parse_int("LN_TERM_MOS", "term_months"),
        parse_amount_10_2("LN_PMT_AMT", "monthly_payment"),
        parse_legacy_date("LN_ORIG_DT", "origination_date"),
        parse_legacy_date("LN_MAT_DT", "maturity_date"),
        parse_legacy_date("LN_1ST_PMT_DT", "first_payment_date"),
        parse_legacy_date("LN_NXT_PMT_DT", "next_payment_date"),
        expand_codes("LN_STAT_CD", LOAN_STATUS_MAP, "status"),
        parse_int("LN_DLQ_DAYS", "delinquency_days"),
        parse_amount_10_2("LN_ESCROW_BAL", "escrow_balance"),
        parse_percent("LN_LTV_PCT", "ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_codes("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
        parse_amount("PROP_APRS_VAL", "appraised_value"),
        parse_legacy_timestamp("LN_CRET_DT", "created_at"),
        parse_legacy_timestamp("LN_UPDT_DT", "updated_at"),
    )

    # Phase 2: resolve FKs
    transformed = resolve_foreign_keys(spark, transformed)

    # Phase 3: critical field validation
    transformed = transformed.withColumn(
        "_has_error",
        (
            F.col("account_number").isNull()
            | F.col("original_amount").isNull()
            | F.col("current_balance").isNull()
            | F.col("interest_rate").isNull()
            | F.col("origination_date").isNull()
            | F.col("maturity_date").isNull()
        ),
    )

    # Separate good and quarantine
    drop_cols = ["_has_error", "_legacy_borr_id", "_legacy_prod_cd", "_fk_unresolved"]
    good_df = transformed.filter(~F.col("_has_error")).drop(*drop_cols)
    quarantine_df = transformed.filter(F.col("_has_error")).drop("_has_error")

    return good_df, quarantine_df


def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    """Write results to Delta Lake and quarantine bad records."""
    source_count = good_df.count() + quarantine_df.count()

    good_df = good_df.withColumn("_ingestion_ts", F.current_timestamp())

    good_df.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    target_count = good_df.count()
    quarantine_count = quarantine_df.count()

    if quarantine_count > 0:
        quarantine_df.write.format("delta").mode("append").save(QUARANTINE_PATH)
        print(
            f"WARNING: {quarantine_count} loan account records quarantined to {QUARANTINE_PATH}"
        )

    return {
        "table": "loan_accounts",
        "source_count": source_count,
        "target_count": target_count,
        "quarantine_count": quarantine_count,
    }


def run(spark: SparkSession | None = None) -> dict:
    """Main entry point."""
    if spark is None:
        spark = SparkSession.builder.appName("IngestLoanAccounts").getOrCreate()

    print("--- Ingesting CDW_LN_ACCT -> loan_accounts ---")
    raw = read_source(spark, SOURCE_PATH)
    print(f"Source record count: {raw.count()}")

    good_df, quarantine_df = transform_loan_accounts(spark, raw)
    stats = write_target(good_df, quarantine_df)

    print(f"Target records written: {stats['target_count']}")
    print(f"Quarantined records:    {stats['quarantine_count']}")
    return stats


if __name__ == "__main__":
    run()
