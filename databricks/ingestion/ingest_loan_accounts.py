"""
PySpark ingestion script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads from a legacy CSV/Parquet extract of the CDW_LN_ACCT table and transforms
all VARCHAR columns into proper Spark SQL types. Key operations:
  - Drops denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  - Resolves BORR_ID → borrowers.id via lookup on borrowers.external_id
  - Resolves PROD_CD → loan_products.id via lookup on loan_products.code
  - Expands loan status codes: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
  - Expands property type codes: SFR→Single Family, CND→Condominium, etc.
  - Parses all date strings and comma-formatted amounts

Usage (Databricks notebook cell):
    %run ./transform_utils
    %run ./ingest_loan_accounts

Or as a standalone script:
    spark-submit --master local[*] ingest_loan_accounts.py \
        --source-path /mnt/landing/cdw_ln_acct/ \
        --source-format csv \
        --target-table loan_warehouse.loan_accounts
"""

import argparse
import logging
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transform_utils import (
    parse_date_mmddyyyy,
    parse_timestamp_mmddyyyy,
    parse_decimal_amount,
    parse_integer,
    expand_status_code,
    tag_malformed_rows,
    log_unmapped_codes,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

logger = logging.getLogger("cdw_migration.loan_accounts")
logger.setLevel(logging.INFO)


def read_legacy_loan_accounts(spark: SparkSession, source_path: str,
                              source_format: str = "csv") -> DataFrame:
    """
    Read the legacy CDW_LN_ACCT extract from the landing zone.
    """
    if source_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "")
            .csv(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from legacy CDW_LN_ACCT at %s", df.count(), source_path)
    return df


def resolve_foreign_keys(df: DataFrame, spark: SparkSession,
                         borrowers_table: str = "loan_warehouse.borrowers",
                         products_table: str = "loan_warehouse.loan_products") -> DataFrame:
    """
    Resolve legacy string IDs to modern surrogate keys:
      - CDW_LN_ACCT.BORR_ID → borrowers.id  (via borrowers.external_id)
      - CDW_LN_ACCT.PROD_CD → loan_products.id (via loan_products.code)

    Rows with unresolvable FKs are flagged (not dropped) so the quality framework
    can report them.
    """
    # Load lookup tables
    borrowers_lookup = spark.table(borrowers_table).select(
        F.col("id").alias("_resolved_borrower_id"),
        F.col("external_id").alias("_borr_lookup_key"),
    )
    products_lookup = spark.table(products_table).select(
        F.col("id").alias("_resolved_product_id"),
        F.col("code").alias("_prod_lookup_key"),
    )

    # Left join to resolve borrower FK
    df = df.join(
        borrowers_lookup,
        df["BORR_ID"] == borrowers_lookup["_borr_lookup_key"],
        "left"
    )

    # Left join to resolve product FK
    df = df.join(
        products_lookup,
        df["PROD_CD"] == products_lookup["_prod_lookup_key"],
        "left"
    )

    # Flag unresolved FKs for quality reporting
    df = df.withColumn(
        "_unresolved_borrower",
        F.when(F.col("_resolved_borrower_id").isNull(), F.lit(True)).otherwise(F.lit(False))
    )
    df = df.withColumn(
        "_unresolved_product",
        F.when(F.col("_resolved_product_id").isNull(), F.lit(True)).otherwise(F.lit(False))
    )

    # Log unresolved FKs
    unresolved_borr = df.filter(F.col("_unresolved_borrower")).count()
    unresolved_prod = df.filter(F.col("_unresolved_product")).count()
    if unresolved_borr > 0:
        logger.warning("Found %d loan accounts with unresolvable BORR_ID", unresolved_borr)
    if unresolved_prod > 0:
        logger.warning("Found %d loan accounts with unresolvable PROD_CD", unresolved_prod)

    return df


def transform_loan_accounts(df: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Transform legacy CDW_LN_ACCT columns to the modern loan_accounts schema.

    Transformations applied:
      - Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4): dropped
      - BORR_ID, PROD_CD: resolved to surrogate FK ids via lookup
      - LN_ORIG_AMT, LN_CURR_BAL, LN_PMT_AMT, LN_ESCROW_BAL, PROP_APRS_VAL:
        comma-formatted string → DECIMAL
      - LN_INT_RT, LN_LTV_PCT: string → DECIMAL
      - LN_TERM_MOS, LN_DLQ_DAYS: string → INT
      - Date fields (LN_ORIG_DT, LN_MAT_DT, etc.): MM/DD/YYYY → DateType
      - LN_STAT_CD: expanded to full status name
      - PROP_TYP_CD: expanded to full property type name
    """
    # Resolve foreign keys first
    df = resolve_foreign_keys(df, spark)

    transformed = (
        df
        # Natural key
        .withColumn("account_number", F.col("LN_ACCT_NBR"))

        # Resolved FKs
        .withColumn("borrower_id", F.col("_resolved_borrower_id"))
        .withColumn("product_id", F.col("_resolved_product_id"))

        # Financial fields — parse from comma-formatted strings
        .withColumn("original_amount", parse_decimal_amount("LN_ORIG_AMT"))
        .withColumn("current_balance", parse_decimal_amount("LN_CURR_BAL"))
        .withColumn("interest_rate", parse_decimal_amount("LN_INT_RT", 5, 3))
        .withColumn("monthly_payment", parse_decimal_amount("LN_PMT_AMT", 10, 2))
        .withColumn("escrow_balance", parse_decimal_amount("LN_ESCROW_BAL", 10, 2))
        .withColumn("appraised_value", parse_decimal_amount("PROP_APRS_VAL"))
        .withColumn("ltv_percent", parse_decimal_amount("LN_LTV_PCT", 5, 2))

        # Integer fields
        .withColumn("term_months", parse_integer("LN_TERM_MOS"))
        .withColumn("delinquency_days", parse_integer("LN_DLQ_DAYS"))

        # Date fields
        .withColumn("origination_date", parse_date_mmddyyyy("LN_ORIG_DT"))
        .withColumn("maturity_date", parse_date_mmddyyyy("LN_MAT_DT"))
        .withColumn("first_payment_date", parse_date_mmddyyyy("LN_1ST_PMT_DT"))
        .withColumn("next_payment_date", parse_date_mmddyyyy("LN_NXT_PMT_DT"))

        # Status code expansion
        .withColumn("status", expand_status_code("LN_STAT_CD", LOAN_STATUS_MAP))

        # Property type expansion
        .withColumn("property_type", expand_status_code("PROP_TYP_CD", PROPERTY_TYPE_MAP))

        # Direct-copy property address fields
        .withColumn("property_address", F.col("PROP_ADDR_LN1"))
        .withColumn("property_city", F.col("PROP_CTY_NM"))
        .withColumn("property_state", F.col("PROP_ST_CD"))
        .withColumn("property_zip", F.col("PROP_ZIP_CD"))

        # Timestamps
        .withColumn("created_at", parse_timestamp_mmddyyyy("LN_CRET_DT"))
        .withColumn("updated_at", parse_timestamp_mmddyyyy("LN_UPDT_DT"))
    )

    # Log unmapped status and property type codes
    log_unmapped_codes(transformed, "LN_STAT_CD", "status", "CDW_LN_ACCT")
    log_unmapped_codes(transformed, "PROP_TYP_CD", "property_type", "CDW_LN_ACCT")

    modern_columns = [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment",
        "origination_date", "maturity_date", "first_payment_date", "next_payment_date",
        "status", "delinquency_days", "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state", "property_zip",
        "property_type", "appraised_value",
        "created_at", "updated_at",
    ]
    return transformed.select(modern_columns)


def write_loan_accounts(df: DataFrame,
                        target_table: str = "loan_warehouse.loan_accounts") -> None:
    """
    Write transformed loan account data to the Delta Lake target table.
    Uses merge (upsert) on account_number for idempotent reruns.
    The table is partitioned by status, so Delta handles partition placement automatically.
    """
    row_count = df.count()
    logger.info("Writing %d loan account records to %s", row_count, target_table)

    df.createOrReplaceTempView("loan_accounts_staging")

    spark = df.sparkSession
    spark.sql(f"""
        MERGE INTO {target_table} AS target
        USING loan_accounts_staging AS source
        ON target.account_number = source.account_number
        WHEN MATCHED THEN UPDATE SET
            borrower_id        = source.borrower_id,
            product_id         = source.product_id,
            original_amount    = source.original_amount,
            current_balance    = source.current_balance,
            interest_rate      = source.interest_rate,
            term_months        = source.term_months,
            monthly_payment    = source.monthly_payment,
            origination_date   = source.origination_date,
            maturity_date      = source.maturity_date,
            first_payment_date = source.first_payment_date,
            next_payment_date  = source.next_payment_date,
            status             = source.status,
            delinquency_days   = source.delinquency_days,
            escrow_balance     = source.escrow_balance,
            ltv_percent        = source.ltv_percent,
            property_address   = source.property_address,
            property_city      = source.property_city,
            property_state     = source.property_state,
            property_zip       = source.property_zip,
            property_type      = source.property_type,
            appraised_value    = source.appraised_value,
            created_at         = source.created_at,
            updated_at         = source.updated_at,
            _migration_ts      = current_timestamp()
        WHEN NOT MATCHED THEN INSERT (
            account_number, borrower_id, product_id,
            original_amount, current_balance, interest_rate,
            term_months, monthly_payment,
            origination_date, maturity_date, first_payment_date, next_payment_date,
            status, delinquency_days, escrow_balance, ltv_percent,
            property_address, property_city, property_state, property_zip,
            property_type, appraised_value,
            created_at, updated_at
        ) VALUES (
            source.account_number, source.borrower_id, source.product_id,
            source.original_amount, source.current_balance, source.interest_rate,
            source.term_months, source.monthly_payment,
            source.origination_date, source.maturity_date,
            source.first_payment_date, source.next_payment_date,
            source.status, source.delinquency_days, source.escrow_balance, source.ltv_percent,
            source.property_address, source.property_city, source.property_state,
            source.property_zip, source.property_type, source.appraised_value,
            source.created_at, source.updated_at
        )
    """)
    logger.info("Loan account ingestion complete: %d records processed", row_count)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest CDW_LN_ACCT to loan_warehouse.loan_accounts"
    )
    parser.add_argument("--source-path", required=True, help="Path to legacy CSV/Parquet extract")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--target-table", default="loan_warehouse.loan_accounts")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_LoanAccount_Ingestion").getOrCreate()

    raw_df = read_legacy_loan_accounts(spark, args.source_path, args.source_format)
    transformed_df = transform_loan_accounts(raw_df, spark)
    write_loan_accounts(transformed_df, args.target_table)

    spark.stop()
