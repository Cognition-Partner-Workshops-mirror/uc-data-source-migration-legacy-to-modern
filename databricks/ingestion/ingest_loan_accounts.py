"""Ingest legacy CDW_LN_ACCT into Delta Lake ``loan_warehouse.loan_accounts``.

Reads from a CSV/Parquet source file that mirrors the legacy CDW_LN_ACCT
table structure. Drops denormalized borrower columns, resolves foreign keys
to borrower and product dimension tables, applies type conversions and
status-code expansion, and writes to the target Delta table.

Usage:
    from databricks.ingestion.ingest_loan_accounts import run
    run(spark, source_path="...", target_table="loan_warehouse.loan_accounts")
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from databricks.ingestion.utils import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    add_ingestion_metadata,
    expand_status,
    log_null_counts,
    parse_amount,
    parse_date,
    parse_int,
    parse_timestamp,
)

EXPECTED_COLUMNS = [
    "LN_ACCT_NBR", "BORR_ID", "BORR_FST_NM", "BORR_LST_NM", "BORR_SSN_LST4",
    "PROD_CD", "LN_ORIG_AMT", "LN_CURR_BAL", "LN_INT_RT", "LN_TERM_MOS",
    "LN_PMT_AMT", "LN_ORIG_DT", "LN_MAT_DT", "LN_1ST_PMT_DT", "LN_NXT_PMT_DT",
    "LN_STAT_CD", "LN_DLQ_DAYS", "LN_ESCROW_BAL", "LN_LTV_PCT",
    "PROP_ADDR_LN1", "PROP_CTY_NM", "PROP_ST_CD", "PROP_ZIP_CD",
    "PROP_TYP_CD", "PROP_APRS_VAL", "LN_CRET_DT", "LN_UPDT_DT",
]

REQUIRED_FIELDS = ["LN_ACCT_NBR", "BORR_ID", "PROD_CD", "LN_ORIG_AMT", "LN_CURR_BAL"]


def read_source(spark: SparkSession, source_path: str, file_format: str = "csv") -> DataFrame:
    if file_format == "parquet":
        return spark.read.parquet(source_path)
    return spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)


def validate_schema(df: DataFrame) -> DataFrame:
    missing = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Source is missing expected columns: {sorted(missing)}")
    return df


def quarantine_bad_rows(df: DataFrame) -> tuple:
    condition = F.lit(True)
    for col_name in REQUIRED_FIELDS:
        condition = condition & F.col(col_name).isNotNull() & (F.trim(F.col(col_name)) != "")
    good_df = df.filter(condition)
    quarantine_df = df.filter(~condition)

    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        print(f"[WARN] Quarantined {quarantine_count} loan account rows with missing required fields.")

    return good_df, quarantine_df


def resolve_borrower_keys(df: DataFrame, spark: SparkSession, borrower_table: str) -> DataFrame:
    """Join with borrowers dimension to resolve BORR_ID -> borrower_key."""
    borrowers = spark.table(borrower_table).select(
        F.col("borrower_key"),
        F.col("external_id").alias("_borr_ext_id"),
    )
    df = df.join(borrowers, df["BORR_ID"] == borrowers["_borr_ext_id"], "left")

    unmatched = df.filter(F.col("borrower_key").isNull()).count()
    if unmatched > 0:
        print(f"[WARN] {unmatched} loan accounts have no matching borrower (BORR_ID not found).")

    return df.drop("_borr_ext_id")


def resolve_product_keys(df: DataFrame, spark: SparkSession, product_table: str) -> DataFrame:
    """Join with loan_products dimension to resolve PROD_CD -> product_key."""
    products = spark.table(product_table).select(
        F.col("product_key"),
        F.col("code").alias("_prod_code"),
    )
    df = df.join(products, df["PROD_CD"] == products["_prod_code"], "left")

    unmatched = df.filter(F.col("product_key").isNull()).count()
    if unmatched > 0:
        print(f"[WARN] {unmatched} loan accounts have no matching product (PROD_CD not found).")

    return df.drop("_prod_code")


def transform(df: DataFrame) -> DataFrame:
    """Apply all column transformations for the loan_accounts table."""
    # Date conversions
    df = parse_date(df, "LN_ORIG_DT", "origination_date")
    df = parse_date(df, "LN_MAT_DT", "maturity_date")
    df = parse_date(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date(df, "LN_NXT_PMT_DT", "next_payment_date")
    df = parse_timestamp(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp(df, "LN_UPDT_DT", "updated_at")

    # Amount conversions
    df = parse_amount(df, "LN_ORIG_AMT", "original_amount", precision=12, scale=2)
    df = parse_amount(df, "LN_CURR_BAL", "current_balance", precision=12, scale=2)
    df = parse_amount(df, "LN_PMT_AMT", "monthly_payment", precision=10, scale=2)
    df = parse_amount(df, "LN_ESCROW_BAL", "escrow_balance", precision=10, scale=2)
    df = parse_amount(df, "PROP_APRS_VAL", "appraised_value", precision=12, scale=2)
    df = parse_amount(df, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    df = parse_amount(df, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)

    # Integer conversions
    df = parse_int(df, "LN_TERM_MOS", "term_months")
    df = parse_int(df, "LN_DLQ_DAYS", "delinquency_days")

    # Status and property type expansion
    df = expand_status(df, "LN_STAT_CD", LOAN_STATUS_MAP, "status")
    df = expand_status(df, "PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type")

    # Derived column: origination year for partitioning convenience
    df = df.withColumn("origination_year", F.year(F.col("origination_date")))

    # Rename direct-copy columns
    df = (
        df.withColumnRenamed("LN_ACCT_NBR", "account_number")
        .withColumnRenamed("PROP_ADDR_LN1", "property_address")
        .withColumnRenamed("PROP_CTY_NM", "property_city")
        .withColumnRenamed("PROP_ST_CD", "property_state")
        .withColumnRenamed("PROP_ZIP_CD", "property_zip")
    )

    df = add_ingestion_metadata(df, "CDW_LN_ACCT")

    final_columns = [
        "account_number", "borrower_key", "product_key",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment",
        "origination_date", "maturity_date",
        "first_payment_date", "next_payment_date",
        "status", "delinquency_days", "escrow_balance", "ltv_percent",
        "property_address", "property_city", "property_state", "property_zip",
        "property_type", "appraised_value", "origination_year",
        "created_at", "updated_at",
        "_ingestion_ts", "_source_system",
    ]
    return df.select(*final_columns)


def write_target(df: DataFrame, target_table: str, mode: str = "overwrite") -> None:
    df.write.format("delta").mode(mode).partitionBy("status").saveAsTable(target_table)
    row_count = df.count()
    print(f"[INFO] Wrote {row_count} rows to {target_table}.")


def run(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.loan_accounts",
    borrower_table: str = "loan_warehouse.borrowers",
    product_table: str = "loan_warehouse.loan_products",
    file_format: str = "csv",
    quarantine_path: str | None = None,
) -> dict:
    print(f"[INFO] Starting loan account ingestion from {source_path}")

    raw_df = read_source(spark, source_path, file_format)
    raw_df = validate_schema(raw_df)
    raw_count = raw_df.count()
    print(f"[INFO] Source row count: {raw_count}")

    good_df, quarantine_df = quarantine_bad_rows(raw_df)
    log_null_counts(good_df, "CDW_LN_ACCT (pre-transform)", EXPECTED_COLUMNS)

    # Resolve foreign keys before transformation
    good_df = resolve_borrower_keys(good_df, spark, borrower_table)
    good_df = resolve_product_keys(good_df, spark, product_table)

    transformed_df = transform(good_df)
    write_target(transformed_df, target_table)

    quarantine_count = quarantine_df.count()
    if quarantine_count > 0 and quarantine_path:
        quarantine_df.write.format("delta").mode("overwrite").save(quarantine_path)
        print(f"[WARN] {quarantine_count} quarantined rows written to {quarantine_path}")

    return {
        "source_count": raw_count,
        "loaded_count": raw_count - quarantine_count,
        "quarantined_count": quarantine_count,
        "target_table": target_table,
    }
