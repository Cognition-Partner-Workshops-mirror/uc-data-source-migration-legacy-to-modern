"""
Loan account ingestion script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads the legacy denormalized loan account table and transforms it into
the modern loan_accounts Delta Lake table, stripping embedded borrower
fields and resolving foreign keys.

Transformations applied:
  - BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 dropped (denormalized; use FK)
  - BORR_ID → borrower_id via borrowers.external_id lookup
  - PROD_CD → product_id via loan_products.code lookup
  - LN_ORIG_AMT, LN_CURR_BAL, etc. (VARCHAR with commas) → DECIMAL
  - LN_STAT_CD (ACT/CLO/DFT/FRB) → status (Active/Closed/Default/Forbearance)
  - PROP_TYP_CD (SFR/CND/MFR/TWN) → property_type (expanded)
  - All dates (MM/DD/YYYY) → DATE or TIMESTAMP
  - origination_year derived from origination_date for partitioning

Malformed rows are flagged and routed to quarantine, never silently dropped.
"""

import logging

from pyspark.sql import SparkSession, functions as F

from config import (
    SOURCE_PATHS,
    TARGET_TABLES,
    QUARANTINE_TABLE,
    LOAN_ACCOUNT_LEGACY_SCHEMA,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)
from transformations import (
    parse_date,
    parse_timestamp,
    parse_amount,
    parse_amount_10_2,
    parse_integer,
    parse_rate,
    parse_percent,
    expand_status_code,
    add_etl_metadata,
    tag_malformed_rows,
    log_malformed_summary,
    read_legacy_source,
)

logger = logging.getLogger("cdw_migration.ingest_loan_accounts")


def ingest_loan_accounts(spark: SparkSession, file_format: str = "csv") -> dict:
    """
    Main ingestion function for loan accounts.

    Requires borrowers and loan_products tables to already be loaded (for FK lookup).

    Returns a dict with row counts for reconciliation:
      {"source_count": int, "target_count": int, "quarantine_count": int,
       "orphan_borrower_count": int, "orphan_product_count": int}
    """
    logger.info("Starting loan account ingestion from CDW_LN_ACCT")

    # -------------------------------------------------------------------------
    # Step 1: Read legacy source data
    # -------------------------------------------------------------------------
    raw_df = read_legacy_source(
        spark, SOURCE_PATHS["loan_accounts"], LOAN_ACCOUNT_LEGACY_SCHEMA, file_format
    )
    source_count = raw_df.count()
    logger.info(f"Read {source_count} rows from CDW_LN_ACCT")

    # -------------------------------------------------------------------------
    # Step 2: Load dimension tables for FK resolution
    # -------------------------------------------------------------------------
    borrowers_df = spark.table(TARGET_TABLES["borrowers"]).select(
        F.col("borrower_id"), F.col("external_id")
    )
    products_df = spark.table(TARGET_TABLES["loan_products"]).select(
        F.col("product_id"), F.col("code").alias("product_code")
    )

    # -------------------------------------------------------------------------
    # Step 3: Apply column-level transformations per column_mappings.md
    # -------------------------------------------------------------------------
    transformed_df = raw_df.select(
        # Natural key — direct copy
        F.col("LN_ACCT_NBR").alias("account_number"),

        # Legacy borrower ID — will be resolved to FK below
        F.col("BORR_ID").alias("_legacy_borrower_id"),

        # Legacy product code — will be resolved to FK below
        F.col("PROD_CD").alias("_legacy_product_code"),

        # Denormalized borrower fields DROPPED per column_mappings.md:
        #   BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 — use borrower FK instead

        # Financial amounts — remove commas, parse to DECIMAL
        parse_amount("LN_ORIG_AMT", "original_amount"),
        parse_amount("LN_CURR_BAL", "current_balance"),
        parse_rate("LN_INT_RT", "interest_rate"),
        parse_integer("LN_TERM_MOS", "term_months"),
        parse_amount_10_2("LN_PMT_AMT", "monthly_payment"),

        # Loan lifecycle dates — parse MM/DD/YYYY to DATE
        parse_date("LN_ORIG_DT", "origination_date"),
        parse_date("LN_MAT_DT", "maturity_date"),
        parse_date("LN_1ST_PMT_DT", "first_payment_date"),
        parse_date("LN_NXT_PMT_DT", "next_payment_date"),

        # Status — expand abbreviation (ACT→Active, CLO→Closed, etc.)
        expand_status_code("LN_STAT_CD", LOAN_STATUS_MAP, "status"),

        # Delinquency days — parse VARCHAR to INT
        parse_integer("LN_DLQ_DAYS", "delinquency_days"),

        # Escrow balance — parse comma-formatted VARCHAR
        parse_amount_10_2("LN_ESCROW_BAL", "escrow_balance"),

        # LTV percentage — parse VARCHAR to DECIMAL(5,2)
        parse_percent("LN_LTV_PCT", "ltv_percent"),

        # Property details — direct copy (except property_type, expanded below)
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),

        # Property type — expand abbreviation (SFR→Single Family, etc.)
        expand_status_code("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),

        # Appraised value — remove commas, parse to DECIMAL(12,2)
        parse_amount("PROP_APRS_VAL", "appraised_value"),

        # Audit timestamps — parse MM/DD/YYYY to TIMESTAMP
        parse_timestamp("LN_CRET_DT", "created_at"),
        parse_timestamp("LN_UPDT_DT", "updated_at"),
    )

    # -------------------------------------------------------------------------
    # Step 4: Resolve borrower FK (BORR_ID → borrower_id)
    # -------------------------------------------------------------------------
    with_borrower_fk = transformed_df.join(
        borrowers_df,
        transformed_df["_legacy_borrower_id"] == borrowers_df["external_id"],
        "left",
    ).drop("external_id", "_legacy_borrower_id")

    # Log orphan borrower references (loan references a borrower not in dimension)
    orphan_borrower_count = with_borrower_fk.filter(F.col("borrower_id").isNull()).count()
    if orphan_borrower_count > 0:
        logger.warning(
            f"{orphan_borrower_count} loan accounts reference borrowers "
            "not found in the borrowers dimension table"
        )

    # -------------------------------------------------------------------------
    # Step 5: Resolve product FK (PROD_CD → product_id)
    # -------------------------------------------------------------------------
    with_product_fk = with_borrower_fk.join(
        products_df,
        with_borrower_fk["_legacy_product_code"] == products_df["product_code"],
        "left",
    ).drop("product_code", "_legacy_product_code")

    orphan_product_count = with_product_fk.filter(F.col("product_id").isNull()).count()
    if orphan_product_count > 0:
        logger.warning(
            f"{orphan_product_count} loan accounts reference products "
            "not found in the loan_products dimension table"
        )

    # -------------------------------------------------------------------------
    # Step 6: Derive partition column (origination_year from origination_date)
    # -------------------------------------------------------------------------
    with_partition = with_product_fk.withColumn(
        "origination_year", F.year(F.col("origination_date"))
    )

    # -------------------------------------------------------------------------
    # Step 7: Flag malformed rows
    # -------------------------------------------------------------------------
    required_cols = [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date",
    ]
    with_flags = tag_malformed_rows(with_partition, required_cols)
    log_malformed_summary(with_flags, "loan_accounts")

    # -------------------------------------------------------------------------
    # Step 8: Separate clean vs. quarantine
    # -------------------------------------------------------------------------
    clean_df = with_flags.filter(~F.col("_is_malformed")).drop("_is_malformed")
    quarantine_df = with_flags.filter(F.col("_is_malformed")).drop("_is_malformed")

    clean_df = add_etl_metadata(clean_df, "CDW_LN_ACCT")

    # -------------------------------------------------------------------------
    # Step 9: Write clean records to Delta Lake
    # -------------------------------------------------------------------------
    clean_count = clean_df.count()
    logger.info(
        f"Writing {clean_count} clean loan account records to "
        f"{TARGET_TABLES['loan_accounts']}"
    )

    clean_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).partitionBy("origination_year").saveAsTable(TARGET_TABLES["loan_accounts"])

    # -------------------------------------------------------------------------
    # Step 10: Write quarantine records (if any)
    # -------------------------------------------------------------------------
    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        logger.warning(f"Writing {quarantine_count} quarantined loan account records")
        quarantine_with_meta = add_etl_metadata(quarantine_df, "CDW_LN_ACCT")
        quarantine_with_meta.withColumn(
            "_quarantine_reason", F.lit("Required field NULL after transformation")
        ).write.format("delta").mode("append").option(
            "mergeSchema", "true"
        ).saveAsTable(QUARANTINE_TABLE)

    result = {
        "source_count": source_count,
        "target_count": clean_count,
        "quarantine_count": quarantine_count,
        "orphan_borrower_count": orphan_borrower_count,
        "orphan_product_count": orphan_product_count,
    }
    logger.info(f"Loan account ingestion complete: {result}")
    return result


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Migration_LoanAccounts").getOrCreate()
    ingest_loan_accounts(spark)
    spark.stop()
