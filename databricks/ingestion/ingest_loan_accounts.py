"""
Ingest loan accounts from legacy CDW_LN_ACCT into the modern ``loan_accounts`` Delta table.

This script:
- Drops the denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
- Resolves BORR_ID → borrower_id via lookup against the already-loaded borrowers table
- Resolves PROD_CD → product_id via lookup against the already-loaded loan_products table
- Expands loan status codes and property type codes

Expected source: CSV or Parquet export of the CDW_LN_ACCT table.

Usage:
    from ingestion.ingest_loan_accounts import run
    run(spark, source_path="dbfs:/mnt/legacy/cdw_ln_acct/", source_format="csv")
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

# Import shared transformation helpers for legacy VARCHAR → typed column conversions
from .transforms import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_int,
    parse_percent,
    parse_rate,
    parse_timestamp,
)

logger = logging.getLogger("ingestion.loan_accounts")

# Target Delta Lake table, partitioned by loan status for portfolio segmentation queries
TARGET_TABLE = "loan_warehouse.loan_accounts"

# Explicit schema for all 27 columns in CDW_LN_ACCT — includes the 3 denormalized
# borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) that will be dropped
# during transformation in favor of a borrower_id foreign key
LEGACY_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),     # denormalized — will be dropped
    StructField("BORR_LST_NM", StringType(), True),     # denormalized — will be dropped
    StructField("BORR_SSN_LST4", StringType(), True),   # denormalized — will be dropped
    StructField("PROD_CD", StringType(), True),
    StructField("LN_ORIG_AMT", StringType(), True),
    StructField("LN_CURR_BAL", StringType(), True),
    StructField("LN_INT_RT", StringType(), True),
    StructField("LN_TERM_MOS", StringType(), True),
    StructField("LN_PMT_AMT", StringType(), True),
    StructField("LN_ORIG_DT", StringType(), True),
    StructField("LN_MAT_DT", StringType(), True),
    StructField("LN_1ST_PMT_DT", StringType(), True),
    StructField("LN_NXT_PMT_DT", StringType(), True),
    StructField("LN_STAT_CD", StringType(), True),
    StructField("LN_DLQ_DAYS", StringType(), True),
    StructField("LN_ESCROW_BAL", StringType(), True),
    StructField("LN_LTV_PCT", StringType(), True),
    StructField("PROP_ADDR_LN1", StringType(), True),
    StructField("PROP_CTY_NM", StringType(), True),
    StructField("PROP_ST_CD", StringType(), True),
    StructField("PROP_ZIP_CD", StringType(), True),
    StructField("PROP_TYP_CD", StringType(), True),
    StructField("PROP_APRS_VAL", StringType(), True),
    StructField("LN_CRET_DT", StringType(), True),
    StructField("LN_UPDT_DT", StringType(), True),
])


def read_source(spark: SparkSession, path: str, fmt: str = "csv") -> DataFrame:
    reader = spark.read.schema(LEGACY_SCHEMA)
    if fmt == "csv":
        return reader.option("header", "true").csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def _load_borrower_lookup(spark: SparkSession) -> DataFrame:
    """Load borrower external_id → borrower_id mapping from already-ingested data."""
    return spark.table("loan_warehouse.borrowers").select(
        F.col("borrower_id"),
        F.col("external_id"),
    )


def _load_product_lookup(spark: SparkSession) -> DataFrame:
    """Load product code → product_id mapping from already-ingested data."""
    return spark.table("loan_warehouse.loan_products").select(
        F.col("product_id"),
        F.col("code").alias("product_code"),
    )


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    # Load FK lookup tables from already-ingested dimension tables
    borrower_lkp = _load_borrower_lookup(spark)
    product_lkp = _load_product_lookup(spark)

    # Apply type transformations and column renames; denormalized borrower columns
    # (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) are intentionally NOT selected here
    base = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("_borr_ext_id"),       # temporary column for FK join
        F.col("PROD_CD").alias("_prod_cd"),               # temporary column for FK join
        parse_amount("LN_ORIG_AMT").alias("original_amount"),
        parse_amount("LN_CURR_BAL").alias("current_balance"),
        parse_rate("LN_INT_RT").alias("interest_rate"),
        parse_int("LN_TERM_MOS").alias("term_months"),
        parse_amount("LN_PMT_AMT", 10, 2).alias("monthly_payment"),
        parse_date("LN_ORIG_DT").alias("origination_date"),
        parse_date("LN_MAT_DT").alias("maturity_date"),
        parse_date("LN_1ST_PMT_DT").alias("first_payment_date"),
        parse_date("LN_NXT_PMT_DT").alias("next_payment_date"),
        # Expand loan status: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
        expand_status("LN_STAT_CD", LOAN_STATUS_MAP, alias="status"),
        parse_int("LN_DLQ_DAYS").alias("delinquency_days"),
        parse_amount("LN_ESCROW_BAL", 10, 2).alias("escrow_balance"),
        parse_percent("LN_LTV_PCT").alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        # Expand property type: SFR→Single Family, CND→Condominium, etc.
        expand_status("PROP_TYP_CD", PROPERTY_TYPE_MAP, alias="property_type"),
        parse_amount("PROP_APRS_VAL").alias("appraised_value"),
        parse_timestamp("LN_CRET_DT").alias("created_at"),
        parse_timestamp("LN_UPDT_DT").alias("updated_at"),
    )

    # Resolve borrower FK: join BORR_ID against borrowers.external_id → get borrower_id
    with_borrower = base.join(
        borrower_lkp,
        base["_borr_ext_id"] == borrower_lkp["external_id"],
        "left",
    ).drop("external_id")

    # Resolve product FK: join PROD_CD against loan_products.code → get product_id
    with_product = with_borrower.join(
        product_lkp,
        with_borrower["_prod_cd"] == product_lkp["product_code"],
        "left",
    ).drop("product_code")

    # Log unresolved FKs
    unresolved_borrowers = with_product.filter(F.col("borrower_id").isNull()).count()
    unresolved_products = with_product.filter(F.col("product_id").isNull()).count()
    if unresolved_borrowers > 0:
        logger.warning(
            "Loan account ingestion: %d rows have unresolved borrower_id",
            unresolved_borrowers,
        )
    if unresolved_products > 0:
        logger.warning(
            "Loan account ingestion: %d rows have unresolved product_id",
            unresolved_products,
        )

    # Flag rows with missing PKs or unresolved FKs; invalid rows are kept, not dropped
    result = with_product.withColumn(
        "_is_valid",
        F.col("account_number").isNotNull()
        & F.col("borrower_id").isNotNull()
        & F.col("product_id").isNotNull(),
    ).drop("_borr_ext_id", "_prod_cd")  # drop temporary join columns

    return result


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    output = df.drop("_is_valid")
    (
        output.write
        .format("delta")
        .mode(mode)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info("Wrote %d rows to %s (mode=%s)", output.count(), TARGET_TABLE, mode)


def run(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
    write_mode: str = "overwrite",
) -> DataFrame:
    logger.info("Starting loan account ingestion from %s (%s)", source_path, source_format)
    raw = read_source(spark, source_path, source_format)
    logger.info("Read %d raw loan account records", raw.count())

    result = transform(raw, spark)
    write_target(result, mode=write_mode)
    return result
