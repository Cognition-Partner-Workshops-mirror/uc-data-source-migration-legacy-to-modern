"""
PySpark ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads legacy loan account data (denormalized), strips embedded borrower fields,
resolves foreign keys, and writes to Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DecimalType, IntegerType, TimestampType
)

LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_LN_ACCT/"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_accounts"
DATE_FORMAT = "MM/dd/yyyy"

# Legacy 3-letter status codes mapped to full descriptive names
STATUS_MAP = {
    "ACT": "ACTIVE",
    "CLO": "CLOSED",
    "DFT": "DEFAULT",
    "FRB": "FORBEARANCE",
}

# Legacy property type abbreviations mapped to readable descriptions
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family",
    "CND": "Condominium",
    "MFR": "Multi-Family",
    "TWN": "Townhouse",
}

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


def parse_legacy_amount(col_name: str):
    """Strip non-numeric chars and cast to DecimalType for amount fields."""
    cleaned = F.regexp_replace(F.col(col_name), r"[^0-9.\-]", "")
    return F.when(
        (F.col(col_name).isNull()) | (F.trim(F.col(col_name)) == ""),
        F.lit(None).cast(DecimalType(12, 2))
    ).otherwise(cleaned.cast(DecimalType(12, 2)))


def expand_status(col_name: str):
    """Expand 3-letter loan status codes to full names; unknown codes prefixed with UNKNOWN:."""
    expr = F.lit(None).cast(StringType())
    for code, expanded in STATUS_MAP.items():
        expr = F.when(F.col(col_name) == code, expanded).otherwise(expr)
    return F.when(
        F.col(col_name).isNull(), F.lit(None)
    ).otherwise(
        F.coalesce(expr, F.concat(F.lit("UNKNOWN:"), F.col(col_name)))
    )


def expand_property_type(col_name: str):
    """Expand property type abbreviations; unknown codes pass through unchanged."""
    expr = F.lit(None).cast(StringType())
    for code, expanded in PROPERTY_TYPE_MAP.items():
        expr = F.when(F.col(col_name) == code, expanded).otherwise(expr)
    return F.coalesce(expr, F.col(col_name))


def read_legacy_accounts(spark: SparkSession) -> DataFrame:
    return (
        spark.read
        .option("header", "true")
        .schema(LEGACY_SCHEMA)
        .csv(LEGACY_SOURCE_PATH)
    )


def transform_accounts(df: DataFrame) -> DataFrame:
    """
    Transform legacy loan accounts.
    Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
    are dropped — the modern schema uses a FK to the borrowers table.
    """
    return df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        # Temporary columns for FK resolution (dropped after join)
        F.col("BORR_ID").alias("_legacy_borrower_id"),
        F.col("PROD_CD").alias("_legacy_product_code"),
        parse_legacy_amount("LN_ORIG_AMT").alias("original_amount"),
        parse_legacy_amount("LN_CURR_BAL").alias("current_balance"),
        F.col("LN_INT_RT").cast(DecimalType(5, 3)).alias("interest_rate"),
        F.col("LN_TERM_MOS").cast(IntegerType()).alias("term_months"),
        parse_legacy_amount("LN_PMT_AMT").alias("monthly_payment"),
        F.to_date(F.col("LN_ORIG_DT"), DATE_FORMAT).alias("origination_date"),
        F.to_date(F.col("LN_MAT_DT"), DATE_FORMAT).alias("maturity_date"),
        F.to_date(F.col("LN_1ST_PMT_DT"), DATE_FORMAT).alias("first_payment_date"),
        F.to_date(F.col("LN_NXT_PMT_DT"), DATE_FORMAT).alias("next_payment_date"),
        expand_status("LN_STAT_CD").alias("status"),
        F.coalesce(F.col("LN_DLQ_DAYS").cast(IntegerType()), F.lit(0)).alias("delinquency_days"),
        parse_legacy_amount("LN_ESCROW_BAL").alias("escrow_balance"),
        F.col("LN_LTV_PCT").cast(DecimalType(5, 2)).alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_property_type("PROP_TYP_CD").alias("property_type"),
        parse_legacy_amount("PROP_APRS_VAL").alias("appraised_value"),
        F.to_date(F.col("LN_CRET_DT"), DATE_FORMAT).cast(TimestampType()).alias("created_at"),
        F.to_date(F.col("LN_UPDT_DT"), DATE_FORMAT).cast(TimestampType()).alias("updated_at"),
    )


def resolve_foreign_keys(df: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Resolve legacy string IDs to modern auto-increment BIGINT IDs.
    - BORR_ID -> borrower_id (via borrowers.external_id)
    - PROD_CD -> product_id (via loan_products.code)
    """
    borrowers = spark.table("loan_warehouse.borrowers").select(
        F.col("id").alias("borrower_id"),
        F.col("external_id")
    )
    products = spark.table("loan_warehouse.loan_products").select(
        F.col("id").alias("product_id"),
        F.col("code")
    )

    resolved = (
        df
        .join(borrowers, df["_legacy_borrower_id"] == borrowers["external_id"], "left")
        .join(products, df["_legacy_product_code"] == products["code"], "left")
        .drop("_legacy_borrower_id", "_legacy_product_code", "external_id", "code")
    )
    return resolved


def quarantine_bad_records(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    critical_filter = (
        F.col("account_number").isNotNull()
        & F.col("borrower_id").isNotNull()
        & F.col("product_id").isNotNull()
        & F.col("original_amount").isNotNull()
    )
    good = df.filter(critical_filter)
    bad = df.filter(~critical_filter).withColumn(
        "_quarantine_reason",
        F.concat_ws(", ",
            F.when(F.col("account_number").isNull(), F.lit("missing account_number")),
            F.when(F.col("borrower_id").isNull(), F.lit("orphaned borrower (FK not found)")),
            F.when(F.col("product_id").isNull(), F.lit("orphaned product (FK not found)")),
            F.when(F.col("original_amount").isNull(), F.lit("missing original_amount")),
        )
    ).withColumn("_quarantine_ts", F.current_timestamp())

    return good, bad


def run(spark: SparkSession):
    print("=== Loan Account Ingestion: START ===")

    raw_df = read_legacy_accounts(spark)
    source_count = raw_df.count()
    print(f"Source record count: {source_count}")

    transformed_df = transform_accounts(raw_df)
    resolved_df = resolve_foreign_keys(transformed_df, spark)
    good_df, bad_df = quarantine_bad_records(resolved_df)

    good_count = good_df.count()
    bad_count = bad_df.count()
    print(f"Clean records: {good_count}, Quarantined: {bad_count}")

    (
        good_df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("status")
        .saveAsTable(TARGET_TABLE)
    )
    print(f"Wrote {good_count} records to {TARGET_TABLE}")

    if bad_count > 0:
        (
            bad_df.write
            .format("delta")
            .mode("append")
            .option("mergeSchema", "true")
            .saveAsTable(QUARANTINE_TABLE)
        )
        print(f"Quarantined {bad_count} records to {QUARANTINE_TABLE}")

    print("=== Loan Account Ingestion: COMPLETE ===")
    return source_count, good_count, bad_count


if __name__ == "__main__":
    spark = SparkSession.builder.getOrCreate()
    run(spark)
