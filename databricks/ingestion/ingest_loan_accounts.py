"""
Ingest legacy CDW_LN_ACCT → modern loan_accounts Delta Lake table.

Source : CSV/Parquet export of CDW_LN_ACCT
Target : loan_warehouse.loan_accounts (Delta Lake)

Transformations:
  - Parse date strings (MM/DD/YYYY) → DateType / TimestampType
  - Parse amount strings (with commas) → DecimalType
  - Parse numeric strings → IntegerType / DecimalType
  - Expand loan status codes (ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance)
  - Expand property type codes (SFR→Single Family, CND→Condominium, etc.)
  - Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  - Resolve borrower_key FK via lookup on borrowers.external_id
  - Resolve product_key FK via lookup on loan_products.code
  - Derive origination_year partition column from origination_date
"""

import logging
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType,
)

from transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_int,
    expand_status_code,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_loan_accounts")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

LEGACY_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), False),
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_SSN_LST4", StringType(), True),
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

SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_ln_acct/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_PATH = "dbfs:/mnt/quarantine/loan_accounts/"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH, fmt: str = SOURCE_FORMAT) -> DataFrame:
    reader = spark.read.schema(LEGACY_SCHEMA)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.format(fmt).load(path)


# ---------------------------------------------------------------------------
# FK lookup helpers
# ---------------------------------------------------------------------------

def load_borrower_lookup(spark: SparkSession) -> DataFrame:
    """Load borrower key lookup: external_id → borrower_key."""
    return (
        spark.read.table("loan_warehouse.borrowers")
        .select(
            F.col("borrower_key"),
            F.col("external_id").alias("_borr_ext_id"),
        )
    )


def load_product_lookup(spark: SparkSession) -> DataFrame:
    """Load product key lookup: code → product_key."""
    return (
        spark.read.table("loan_warehouse.loan_products")
        .select(
            F.col("product_key"),
            F.col("code").alias("_prod_code"),
        )
    )


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame, borrower_lkp: DataFrame, product_lkp: DataFrame) -> tuple[DataFrame, DataFrame]:
    # Apply column-level transformations (drop denormalized borrower columns)
    mapped = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("_borr_id"),
        F.col("PROD_CD").alias("_prod_cd"),
        parse_legacy_amount("LN_ORIG_AMT", 12, 2).alias("original_amount"),
        parse_legacy_amount("LN_CURR_BAL", 12, 2).alias("current_balance"),
        F.col("LN_INT_RT").cast("decimal(5,3)").alias("interest_rate"),
        parse_legacy_int("LN_TERM_MOS").alias("term_months"),
        parse_legacy_amount("LN_PMT_AMT", 10, 2).alias("monthly_payment"),
        parse_legacy_date("LN_ORIG_DT").alias("origination_date"),
        parse_legacy_date("LN_MAT_DT").alias("maturity_date"),
        parse_legacy_date("LN_1ST_PMT_DT").alias("first_payment_date"),
        parse_legacy_date("LN_NXT_PMT_DT").alias("next_payment_date"),
        expand_status_code("LN_STAT_CD", LOAN_STATUS_MAP, "Unknown").alias("status"),
        parse_legacy_int("LN_DLQ_DAYS").alias("delinquency_days"),
        parse_legacy_amount("LN_ESCROW_BAL", 10, 2).alias("escrow_balance"),
        F.col("LN_LTV_PCT").cast("decimal(5,2)").alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_status_code("PROP_TYP_CD", PROPERTY_TYPE_MAP, "Other").alias("property_type"),
        parse_legacy_amount("PROP_APRS_VAL", 12, 2).alias("appraised_value"),
        parse_legacy_timestamp("LN_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("LN_UPDT_DT").alias("updated_at"),
        F.current_timestamp().alias("_migration_ts"),
        F.lit("CDW_LN_ACCT").alias("_source_system"),
    )

    # Resolve borrower FK
    with_borrower = mapped.join(
        borrower_lkp,
        mapped["_borr_id"] == borrower_lkp["_borr_ext_id"],
        "left",
    ).drop("_borr_ext_id", "_borr_id")

    # Resolve product FK
    with_product = with_borrower.join(
        product_lkp,
        with_borrower["_prod_cd"] == product_lkp["_prod_code"],
        "left",
    ).drop("_prod_code", "_prod_cd")

    # Derive partition column
    with_partition = with_product.withColumn(
        "origination_year",
        F.year(F.col("origination_date")),
    )

    # Validation: required fields and FK resolution
    valid_condition = (
        F.col("account_number").isNotNull()
        & F.col("borrower_key").isNotNull()
        & F.col("product_key").isNotNull()
        & F.col("original_amount").isNotNull()
        & F.col("current_balance").isNotNull()
        & F.col("interest_rate").isNotNull()
        & F.col("origination_date").isNotNull()
        & F.col("maturity_date").isNotNull()
        & F.col("origination_year").isNotNull()
    )

    good_df = with_partition.filter(valid_condition)
    quarantine_df = with_partition.filter(~valid_condition)

    return good_df, quarantine_df


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    good_count = good_df.count()
    quarantine_count = quarantine_df.count()

    logger.info("Loan accounts — good: %d, quarantined: %d", good_count, quarantine_count)

    if quarantine_count > 0:
        logger.warning("Writing %d quarantined loan account records to %s", quarantine_count, QUARANTINE_PATH)
        quarantine_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)

    good_df.write.mode("overwrite").format("delta").saveAsTable(TARGET_TABLE)

    logger.info("Loan account ingestion complete → %s", TARGET_TABLE)
    return {"good": good_count, "quarantined": quarantine_count}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession) -> dict:
    logger.info("Starting loan account ingestion from %s", SOURCE_PATH)

    raw_df = read_source(spark)
    source_count = raw_df.count()
    logger.info("Source record count: %d", source_count)

    borrower_lkp = load_borrower_lookup(spark)
    product_lkp = load_product_lookup(spark)

    good_df, quarantine_df = transform(raw_df, borrower_lkp, product_lkp)
    result = write_target(good_df, quarantine_df)
    result["source_count"] = source_count
    return result


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest_CDW_LN_ACCT").getOrCreate()
    run(spark)
