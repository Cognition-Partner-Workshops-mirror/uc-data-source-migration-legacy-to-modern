"""
Ingestion notebook: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the denormalized legacy loan-account data, drops redundant borrower
columns, resolves foreign keys to borrowers and loan_products dimension
tables, and writes the normalized result to Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    expand_loan_status,
    expand_property_type,
    parse_amount,
    parse_date_mmddyyyy,
    parse_int,
    parse_rate,
    parse_timestamp_mmddyyyy,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/legacy-export/CDW_LN_ACCT"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
BORROWERS_TABLE = "loan_warehouse.borrowers"
PRODUCTS_TABLE = "loan_warehouse.loan_products"
WRITE_MODE = "overwrite"

# ---------------------------------------------------------------------------
# Spark
# ---------------------------------------------------------------------------
spark = SparkSession.builder.appName("ingest_loan_accounts").getOrCreate()
spark.conf.set("spark.sql.legacy.timeParserPolicy", "CORRECTED")

_LOG_TAG = "[ingest_loan_accounts]"


def _log(msg: str) -> None:
    print(f"{_LOG_TAG} {msg}")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(path: str, fmt: str) -> DataFrame:
    _log(f"Reading source from {path} (format={fmt})")
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(path)
    _log(f"Source row count: {df.count()}")
    return df


# ---------------------------------------------------------------------------
# FK resolution helpers
# ---------------------------------------------------------------------------

def _resolve_borrower_ids(df: DataFrame) -> DataFrame:
    """Join legacy BORR_ID to modern borrowers.id via external_id."""
    borrowers = spark.table(BORROWERS_TABLE).select(
        F.col("id").alias("_borr_pk"),
        F.col("external_id"),
    )
    joined = df.join(
        borrowers,
        df["BORR_ID"] == borrowers["external_id"],
        "left",
    )
    unresolved = joined.filter(F.col("_borr_pk").isNull()).count()
    if unresolved > 0:
        _log(f"WARNING: {unresolved} loan rows have no matching borrower (BORR_ID not found)")
    return joined


def _resolve_product_ids(df: DataFrame) -> DataFrame:
    """Join legacy PROD_CD to modern loan_products.id via code."""
    products = spark.table(PRODUCTS_TABLE).select(
        F.col("id").alias("_prod_pk"),
        F.col("code").alias("_prod_code"),
    )
    joined = df.join(
        products,
        df["PROD_CD"] == products["_prod_code"],
        "left",
    )
    unresolved = joined.filter(F.col("_prod_pk").isNull()).count()
    if unresolved > 0:
        _log(f"WARNING: {unresolved} loan rows have no matching product (PROD_CD not found)")
    return joined


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame) -> DataFrame:
    # Resolve FKs first
    df = _resolve_borrower_ids(df)
    df = _resolve_product_ids(df)

    origination_date_col = parse_date_mmddyyyy(F.col("LN_ORIG_DT"))

    transformed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("_borr_pk").alias("borrower_id"),
        F.col("_prod_pk").alias("product_id"),
        parse_amount(F.col("LN_ORIG_AMT")).alias("original_amount"),
        parse_amount(F.col("LN_CURR_BAL")).alias("current_balance"),
        parse_rate(F.col("LN_INT_RT")).alias("interest_rate"),
        parse_int(F.col("LN_TERM_MOS")).alias("term_months"),
        parse_amount(F.col("LN_PMT_AMT"), precision=10).alias("monthly_payment"),
        origination_date_col.alias("origination_date"),
        parse_date_mmddyyyy(F.col("LN_MAT_DT")).alias("maturity_date"),
        parse_date_mmddyyyy(F.col("LN_1ST_PMT_DT")).alias("first_payment_date"),
        parse_date_mmddyyyy(F.col("LN_NXT_PMT_DT")).alias("next_payment_date"),
        expand_loan_status(F.col("LN_STAT_CD")).alias("status"),
        parse_int(F.col("LN_DLQ_DAYS")).alias("delinquency_days"),
        parse_amount(F.col("LN_ESCROW_BAL"), precision=10).alias("escrow_balance"),
        parse_rate(F.col("LN_LTV_PCT"), precision=5, scale=2).alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_property_type(F.col("PROP_TYP_CD")).alias("property_type"),
        parse_amount(F.col("PROP_APRS_VAL")).alias("appraised_value"),
        parse_timestamp_mmddyyyy(F.col("LN_CRET_DT")).alias("created_at"),
        parse_timestamp_mmddyyyy(F.col("LN_UPDT_DT")).alias("updated_at"),
        F.year(origination_date_col).alias("origination_year"),
    )

    # Validation logging
    null_accts = transformed.filter(F.col("account_number").isNull()).count()
    if null_accts > 0:
        _log(f"WARNING: {null_accts} rows have NULL account_number")

    null_borrowers = transformed.filter(F.col("borrower_id").isNull()).count()
    if null_borrowers > 0:
        _log(f"WARNING: {null_borrowers} rows have NULL borrower_id after FK resolution")

    bad_amounts = transformed.filter(
        F.col("original_amount").isNull() & df["LN_ORIG_AMT"].isNotNull()
    ).count()
    if bad_amounts > 0:
        _log(f"WARNING: {bad_amounts} rows had unparseable original_amount values")

    _log(f"Transformed row count: {transformed.count()}")
    return transformed


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(df: DataFrame, table: str, mode: str) -> None:
    _log(f"Writing {df.count()} rows to {table} (mode={mode})")
    df.write.format("delta").mode(mode).option(
        "mergeSchema", "true"
    ).partitionBy("origination_year").saveAsTable(table)
    _log("Write complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    source_df = read_source(SOURCE_PATH, SOURCE_FORMAT)
    transformed_df = transform(source_df)
    write_target(transformed_df, TARGET_TABLE, WRITE_MODE)
    _log("Loan account ingestion finished successfully.")


if __name__ == "__main__":
    main()
