"""
Ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Key transformations:
- Drops denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
- Resolves borrower_id via lookup against loan_warehouse.borrowers.external_id
- Resolves product_id via lookup against loan_warehouse.loan_products.code
- Parses all date, amount, and integer strings
- Expands status codes (ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE)
- Expands property type codes (SFR->Single Family, etc.)

Prerequisites: borrowers and loan_products tables must be ingested first.

Usage:
    spark = SparkSession.builder.getOrCreate()
    ingest_loan_accounts(spark, source_path="dbfs:/mnt/legacy/CDW_LN_ACCT.csv")
"""

import logging

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from common_utils import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    map_status_column,
    quarantine_malformed,
    read_legacy_csv,
    read_legacy_parquet,
    register_udfs,
    write_delta,
)

logger = logging.getLogger("cdw_migration.loan_accounts")

TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_accounts"

REQUIRED_COLUMNS = [
    "account_number", "borrower_id", "product_id",
    "original_amount", "current_balance", "interest_rate",
    "term_months", "monthly_payment", "origination_date", "maturity_date",
]


def ingest_loan_accounts(spark: SparkSession, source_path: str,
                         source_format: str = "csv"):
    """
    End-to-end ingestion of CDW_LN_ACCT into loan_warehouse.loan_accounts.
    """
    udfs = register_udfs(spark)

    # ------------------------------------------------------------------
    # 1. Read source
    # ------------------------------------------------------------------
    if source_format == "parquet":
        raw_df = read_legacy_parquet(spark, source_path)
    else:
        raw_df = read_legacy_csv(spark, source_path)

    source_count = raw_df.count()
    logger.info("Source row count: %d", source_count)

    # ------------------------------------------------------------------
    # 2. Load lookup tables for FK resolution
    # ------------------------------------------------------------------
    borrowers_df = (
        spark.table("loan_warehouse.borrowers")
        .select(
            F.col("borrower_key").alias("_bk_borrower_id"),
            F.col("external_id").alias("_bk_external_id"),
        )
    )

    products_df = (
        spark.table("loan_warehouse.loan_products")
        .select(
            F.col("product_key").alias("_pk_product_id"),
            F.col("code").alias("_pk_code"),
        )
    )

    # ------------------------------------------------------------------
    # 3. Transform columns
    # ------------------------------------------------------------------
    transformed_df = (
        raw_df
        .withColumn("account_number", F.trim(F.col("LN_ACCT_NBR")))
        .withColumn("_borr_id_lookup", F.trim(F.col("BORR_ID")))
        .withColumn("_prod_cd_lookup", F.trim(F.col("PROD_CD")))
        .withColumn("original_amount", udfs["parse_amount_12_2"](F.col("LN_ORIG_AMT")))
        .withColumn("current_balance", udfs["parse_amount_12_2"](F.col("LN_CURR_BAL")))
        .withColumn("interest_rate", udfs["parse_amount_5_3"](F.col("LN_INT_RT")))
        .withColumn("term_months", udfs["parse_int"](F.col("LN_TERM_MOS")))
        .withColumn("monthly_payment", udfs["parse_amount_10_2"](F.col("LN_PMT_AMT")))
        .withColumn("origination_date", udfs["parse_date"](F.col("LN_ORIG_DT")))
        .withColumn("maturity_date", udfs["parse_date"](F.col("LN_MAT_DT")))
        .withColumn("first_payment_date", udfs["parse_date"](F.col("LN_1ST_PMT_DT")))
        .withColumn("next_payment_date", udfs["parse_date"](F.col("LN_NXT_PMT_DT")))
        .withColumn("delinquency_days", udfs["parse_int"](F.col("LN_DLQ_DAYS")))
        .withColumn("escrow_balance", udfs["parse_amount_10_2"](F.col("LN_ESCROW_BAL")))
        .withColumn("ltv_percent", udfs["parse_amount_5_2"](F.col("LN_LTV_PCT")))
        .withColumn("property_address", F.trim(F.col("PROP_ADDR_LN1")))
        .withColumn("property_city", F.trim(F.col("PROP_CTY_NM")))
        .withColumn("property_state", F.trim(F.col("PROP_ST_CD")))
        .withColumn("property_zip", F.trim(F.col("PROP_ZIP_CD")))
        .withColumn("appraised_value", udfs["parse_amount_12_2"](F.col("PROP_APRS_VAL")))
        .withColumn("created_at", udfs["parse_timestamp"](F.col("LN_CRET_DT")))
        .withColumn("updated_at", udfs["parse_timestamp"](F.col("LN_UPDT_DT")))
    )

    # Expand loan status codes
    transformed_df = map_status_column(
        transformed_df, "LN_STAT_CD", "status", LOAN_STATUS_MAP
    )

    # Expand property type codes
    prop_type_expr = F.create_map(
        *[F.lit(x) for kv in PROPERTY_TYPE_MAP.items() for x in kv]
    )
    transformed_df = transformed_df.withColumn(
        "property_type",
        F.coalesce(
            prop_type_expr[F.upper(F.trim(F.col("PROP_TYP_CD")))],
            F.trim(F.col("PROP_TYP_CD")),
        ),
    )

    # ------------------------------------------------------------------
    # 4. Resolve foreign keys via joins
    # ------------------------------------------------------------------
    joined_df = (
        transformed_df
        .join(borrowers_df,
              transformed_df["_borr_id_lookup"] == borrowers_df["_bk_external_id"],
              "left")
        .join(products_df,
              transformed_df["_prod_cd_lookup"] == products_df["_pk_code"],
              "left")
        .withColumn("borrower_id", F.col("_bk_borrower_id"))
        .withColumn("product_id", F.col("_pk_product_id"))
    )

    # Log any unresolved FKs
    unresolved_borr = joined_df.filter(F.col("borrower_id").isNull()).count()
    unresolved_prod = joined_df.filter(F.col("product_id").isNull()).count()
    if unresolved_borr > 0:
        logger.warning("Unresolved borrower_id for %d loan accounts", unresolved_borr)
    if unresolved_prod > 0:
        logger.warning("Unresolved product_id for %d loan accounts", unresolved_prod)

    # ------------------------------------------------------------------
    # 5. Select final columns
    # ------------------------------------------------------------------
    # Drop all legacy and lookup columns
    all_legacy_cols = [c for c in raw_df.columns]
    lookup_cols = [
        "_borr_id_lookup", "_prod_cd_lookup",
        "_bk_borrower_id", "_bk_external_id",
        "_pk_product_id", "_pk_code",
    ]
    modern_df = joined_df.drop(*(all_legacy_cols + lookup_cols))

    # Add audit columns
    modern_df = (
        modern_df
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit("CDW_LN_ACCT"))
    )

    # ------------------------------------------------------------------
    # 6. Quarantine malformed rows
    # ------------------------------------------------------------------
    valid_df, quarantine_df = quarantine_malformed(
        modern_df, TARGET_TABLE, REQUIRED_COLUMNS
    )

    # ------------------------------------------------------------------
    # 7. Write to Delta Lake
    # ------------------------------------------------------------------
    write_delta(valid_df, TARGET_TABLE, mode="overwrite", partition_cols=["status"])

    if quarantine_df.count() > 0:
        write_delta(quarantine_df, QUARANTINE_TABLE, mode="overwrite")

    # ------------------------------------------------------------------
    # 8. Post-write validation
    # ------------------------------------------------------------------
    target_count = spark.table(TARGET_TABLE).count()
    quarantine_count = quarantine_df.count()

    logger.info("Ingestion complete for %s", TARGET_TABLE)
    logger.info("  Source rows:      %d", source_count)
    logger.info("  Target rows:      %d", target_count)
    logger.info("  Quarantined rows: %d", quarantine_count)

    return {
        "source_count": source_count,
        "target_count": target_count,
        "quarantine_count": quarantine_count,
        "unresolved_borrowers": unresolved_borr,
        "unresolved_products": unresolved_prod,
        "reconciled": source_count == target_count + quarantine_count,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    spark = SparkSession.builder.appName("CDW_LoanAccount_Ingestion").getOrCreate()

    path = sys.argv[1] if len(sys.argv) > 1 else "dbfs:/mnt/legacy/CDW_LN_ACCT.csv"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "csv"

    result = ingest_loan_accounts(spark, source_path=path, source_format=fmt)
    print(f"Ingestion result: {result}")
