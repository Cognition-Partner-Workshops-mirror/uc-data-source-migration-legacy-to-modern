"""
Ingest loan accounts from legacy CDW_LN_ACCT into Delta Lake loan_accounts table.

Source : CSV/Parquet export of CDW_LN_ACCT
Target : loan_modernized.loan_accounts

Transformations applied:
  - Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
  - Resolve BORR_ID to borrower_id via borrowers table lookup
  - Amount strings ("285,000") -> DECIMAL
  - Interest rate string ("4.750") -> DECIMAL(5,3)
  - Date strings (MM/DD/YYYY) -> DATE / TIMESTAMP
  - Loan status expansion (ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE)
  - Property type expansion (SFR->Single Family, CND->Condominium, etc.)
  - Derive origination_year for partitioning
"""

import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_code,
    parse_amount,
    parse_date,
    parse_int,
    parse_percent,
    parse_rate,
    parse_timestamp,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_loan_accounts")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/landing/cdw/CDW_LN_ACCT"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_modernized.loan_accounts"
BORROWERS_TABLE = "loan_modernized.borrowers"
QUARANTINE_PATH = "/mnt/landing/cdw/quarantine/loan_accounts"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "nullValue": "",
    "emptyValue": "",
}


def read_source(spark: SparkSession) -> DataFrame:
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for k, v in CSV_OPTIONS.items():
            reader = reader.option(k, v)
    return reader.load(SOURCE_PATH)


def transform(df: DataFrame, spark: SparkSession) -> tuple[DataFrame, DataFrame]:
    """Transform and resolve foreign keys.

    Borrower FK resolution:
      Legacy BORR_ID is looked up against the already-loaded borrowers table
      to obtain the modern borrower_id (BIGINT identity column).
      Records with unresolvable BORR_ID are quarantined.
    """
    # -- Step 1: Column-level transformations --------------------------------
    base = df.select(
        F.trim(F.col("LN_ACCT_NBR")).alias("account_number"),
        F.trim(F.col("BORR_ID")).alias("_legacy_borr_id"),
        F.trim(F.col("PROD_CD")).alias("_legacy_prod_cd"),
        # Denormalized borrower fields intentionally dropped:
        #   BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4
        parse_amount("LN_ORIG_AMT").alias("original_amount"),
        parse_amount("LN_CURR_BAL").alias("current_balance"),
        parse_rate("LN_INT_RT").alias("interest_rate"),
        parse_int("LN_TERM_MOS").alias("term_months"),
        parse_amount("LN_PMT_AMT", 10, 2).alias("monthly_payment"),
        parse_date("LN_ORIG_DT").alias("origination_date"),
        parse_date("LN_MAT_DT").alias("maturity_date"),
        parse_date("LN_1ST_PMT_DT").alias("first_payment_date"),
        parse_date("LN_NXT_PMT_DT").alias("next_payment_date"),
        expand_code("LN_STAT_CD", LOAN_STATUS_MAP).alias("status"),
        parse_int("LN_DLQ_DAYS").alias("delinquency_days"),
        parse_amount("LN_ESCROW_BAL", 10, 2).alias("escrow_balance"),
        parse_percent("LN_LTV_PCT").alias("ltv_percent"),
        F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
        F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
        F.trim(F.col("PROP_ST_CD")).alias("property_state"),
        F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
        expand_code("PROP_TYP_CD", PROPERTY_TYPE_MAP).alias("property_type"),
        parse_amount("PROP_APRS_VAL").alias("appraised_value"),
        parse_timestamp("LN_CRET_DT").alias("created_at"),
        parse_timestamp("LN_UPDT_DT").alias("updated_at"),
        F.current_timestamp().alias("_migration_ts"),
    )

    # Derive origination_year for partitioning
    base = base.withColumn(
        "origination_year", F.year(F.col("origination_date"))
    )

    # -- Step 2: FK resolution — borrower_id --------------------------------
    borrowers = spark.table(BORROWERS_TABLE).select(
        F.col("borrower_id"), F.col("external_id")
    )
    joined = base.join(
        borrowers,
        base["_legacy_borr_id"] == borrowers["external_id"],
        "left",
    ).drop("external_id")

    # product_code is kept as string FK reference
    joined = joined.withColumnRenamed("_legacy_prod_cd", "product_code")

    # -- Step 3: Quarantine unresolvable records -----------------------------
    quarantine_condition = (
        F.col("account_number").isNull()
        | F.col("borrower_id").isNull()
        | F.col("original_amount").isNull()
    )
    quarantine_df = joined.filter(quarantine_condition)
    good_df = joined.filter(~quarantine_condition)

    return good_df, quarantine_df


def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    source_count = good_df.count() + quarantine_df.count()
    quarantine_count = quarantine_df.count()

    if quarantine_count > 0:
        logger.warning(
            "Quarantined %d loan account records (missing FK or required fields)",
            quarantine_count,
        )
        quarantine_df.write.format("delta").mode("overwrite").save(QUARANTINE_PATH)

    good_count = good_df.count()
    logger.info("Writing %d loan account records to %s", good_count, TARGET_TABLE)

    good_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLE)

    return {
        "table": TARGET_TABLE,
        "source_count": source_count,
        "written_count": good_count,
        "quarantined_count": quarantine_count,
    }


def run(spark: SparkSession) -> dict:
    logger.info("Starting loan account ingestion from %s", SOURCE_PATH)
    raw = read_source(spark)
    logger.info("Read %d raw loan account records", raw.count())
    good, quarantine = transform(raw, spark)
    stats = write_target(good, quarantine)
    logger.info("Loan account ingestion complete: %s", stats)
    return stats


if __name__ == "__main__":
    spark = SparkSession.builder.appName("ingest_loan_accounts").getOrCreate()
    result = run(spark)
    print(result)
