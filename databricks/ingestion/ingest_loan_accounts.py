"""
PySpark ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Key transformations:
- Drop denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
- Resolve BORR_ID -> borrower_id via borrowers table lookup
- Resolve PROD_CD -> product_id via loan_products table lookup
- Parse all VARCHAR amounts, dates, and integers
- Expand status codes and property type codes
- Partition output by status
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

try:
    from transforms import (
        parse_legacy_date,
        parse_legacy_timestamp,
        parse_legacy_amount,
        parse_legacy_integer,
        expand_status_code,
        flag_nulls,
        flag_parse_failures,
        LOAN_STATUS_MAP,
        PROPERTY_TYPE_MAP,
    )
except ImportError:
    pass


LEGACY_SOURCE_PATH = "/mnt/legacy-cdw/CDW_LN_ACCT"
TARGET_TABLE = "loan_warehouse.loan_accounts"
SOURCE_FORMAT = "csv"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "quote": '"',
    "escape": '"',
}


def read_legacy_accounts(spark: SparkSession) -> DataFrame:
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for k, v in CSV_OPTIONS.items():
            reader = reader.option(k, v)
    return reader.load(LEGACY_SOURCE_PATH)


def transform_accounts(raw: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Apply column mappings from CDW_LN_ACCT -> loan_accounts.
    Resolves borrower_id and product_id via lookup joins.
    """
    # -- FK lookups --------------------------------------------------------
    borrowers = spark.table("loan_warehouse.borrowers").select(
        F.col("borrower_id"), F.col("external_id").alias("_borr_ext_id")
    )
    products = spark.table("loan_warehouse.loan_products").select(
        F.col("product_id"), F.col("code").alias("_prod_code")
    )

    # -- Column transforms -------------------------------------------------
    transformed = (
        raw
        .withColumn("account_number", F.trim(F.col("LN_ACCT_NBR")))
        .withColumn("_borr_ext_id", F.trim(F.col("BORR_ID")))
        .withColumn("_prod_code", F.trim(F.col("PROD_CD")))
        .withColumn("original_amount", parse_legacy_amount("LN_ORIG_AMT"))
        .withColumn("current_balance", parse_legacy_amount("LN_CURR_BAL"))
        .withColumn("interest_rate", parse_legacy_amount("LN_INT_RT", precision=5, scale=3))
        .withColumn("term_months", parse_legacy_integer("LN_TERM_MOS"))
        .withColumn("monthly_payment", parse_legacy_amount("LN_PMT_AMT", precision=10, scale=2))
        .withColumn("origination_date", parse_legacy_date("LN_ORIG_DT"))
        .withColumn("maturity_date", parse_legacy_date("LN_MAT_DT"))
        .withColumn("first_payment_date", parse_legacy_date("LN_1ST_PMT_DT"))
        .withColumn("next_payment_date", parse_legacy_date("LN_NXT_PMT_DT"))
        .withColumn("status", expand_status_code("LN_STAT_CD", LOAN_STATUS_MAP))
        .withColumn("delinquency_days", parse_legacy_integer("LN_DLQ_DAYS"))
        .withColumn("escrow_balance", parse_legacy_amount("LN_ESCROW_BAL", precision=10, scale=2))
        .withColumn("ltv_percent", parse_legacy_amount("LN_LTV_PCT", precision=5, scale=2))
        .withColumn("property_address", F.col("PROP_ADDR_LN1"))
        .withColumn("property_city", F.col("PROP_CTY_NM"))
        .withColumn("property_state", F.col("PROP_ST_CD"))
        .withColumn("property_zip", F.col("PROP_ZIP_CD"))
        .withColumn("property_type", expand_status_code("PROP_TYP_CD", PROPERTY_TYPE_MAP))
        .withColumn("appraised_value", parse_legacy_amount("PROP_APRS_VAL"))
        .withColumn("created_at", parse_legacy_timestamp("LN_CRET_DT"))
        .withColumn("updated_at", parse_legacy_timestamp("LN_UPDT_DT"))
        .withColumn("_legacy_acct_nbr", F.col("LN_ACCT_NBR"))
    )

    # -- Join to resolve FKs -----------------------------------------------
    transformed = (
        transformed
        .join(borrowers, on="_borr_ext_id", how="left")
        .join(products, on="_prod_code", how="left")
    )

    # -- Flag orphaned records (FK lookup failed) ---------------------------
    transformed = transformed.withColumn(
        "_fk_warning",
        F.when(
            F.col("borrower_id").isNull(),
            F.concat(F.col("account_number"), F.lit(": orphan — borrower '"),
                     F.col("_borr_ext_id"), F.lit("' not found"))
        ).when(
            F.col("product_id").isNull(),
            F.concat(F.col("account_number"), F.lit(": orphan — product '"),
                     F.col("_prod_code"), F.lit("' not found"))
        )
    )

    # Log FK warnings
    fk_warnings = (
        transformed.filter(F.col("_fk_warning").isNotNull())
        .select("_fk_warning").collect()
    )
    for row in fk_warnings:
        print(f"WARNING [FK]: {row[0]}")

    return transformed.select(
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment",
        "origination_date", "maturity_date",
        "first_payment_date", "next_payment_date",
        "status", "delinquency_days", "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state",
        "property_zip", "property_type", "appraised_value",
        "created_at", "updated_at", "_legacy_acct_nbr",
    )


def write_accounts(df: DataFrame, mode: str = "overwrite") -> None:
    (
        df.write
        .format("delta")
        .mode(mode)
        .partitionBy("status")
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )


def run(spark: SparkSession = None) -> int:
    if spark is None:
        spark = SparkSession.builder.getOrCreate()

    print("=" * 70)
    print("INGESTION: CDW_LN_ACCT -> loan_warehouse.loan_accounts")
    print("=" * 70)

    raw = read_legacy_accounts(spark)
    source_count = raw.count()
    print(f"Source rows read: {source_count}")

    transformed = transform_accounts(raw, spark)
    target_count = transformed.count()
    print(f"Target rows to write: {target_count}")

    write_accounts(transformed)
    print(f"SUCCESS: {target_count} rows written to {TARGET_TABLE}")

    return target_count


if __name__ == "__main__":
    run()
