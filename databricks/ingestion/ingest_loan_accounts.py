"""
Ingestion script for CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads legacy loan account data and applies transformations:
- Drops denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
- Resolves borrower_id FK by joining on BORR_ID -> borrowers.external_id
- Resolves product_id FK by joining on PROD_CD -> loan_products.code
- Parses all date, amount, and rate string fields
- Expands loan status codes (ACT, CLO, DFT, FRB)
- Expands property type codes (SFR, CND, MFR, TWN)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructField,
    StructType,
    StringType,
)

from transformations import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    add_ingestion_metadata,
    expand_status_column,
    flag_parse_errors,
    log_rejected_records,
    parse_amount_column,
    parse_date_column,
    parse_integer_column,
    parse_rate_column,
    parse_timestamp_column,
)


LEGACY_LOAN_ACCOUNT_SCHEMA = StructType([
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


def read_legacy_loan_accounts(spark: SparkSession, source_path: str) -> DataFrame:
    """Read legacy loan account data from CSV or Parquet source."""
    if source_path.endswith(".parquet") or source_path.endswith("/parquet"):
        return spark.read.schema(LEGACY_LOAN_ACCOUNT_SCHEMA).parquet(source_path)

    return (
        spark.read
        .schema(LEGACY_LOAN_ACCOUNT_SCHEMA)
        .option("header", "true")
        .option("quote", '"')
        .option("escape", '"')
        .csv(source_path)
    )


def resolve_foreign_keys(
    df: DataFrame,
    borrowers_df: DataFrame,
    products_df: DataFrame,
) -> DataFrame:
    """
    Resolve string-based legacy IDs to modern integer foreign keys.

    Joins:
    - BORR_ID -> borrowers.external_id to get borrowers.id
    - PROD_CD -> loan_products.code to get loan_products.id

    Records that cannot be resolved are flagged but NOT dropped.
    """
    # Resolve borrower FK
    borrower_lookup = borrowers_df.select(
        F.col("id").alias("borrower_id"),
        F.col("external_id"),
    )
    df = df.join(
        borrower_lookup,
        df["BORR_ID"] == borrower_lookup["external_id"],
        "left",
    ).drop("external_id")

    # Resolve product FK
    product_lookup = products_df.select(
        F.col("id").alias("product_id"),
        F.col("code"),
    )
    df = df.join(
        product_lookup,
        df["PROD_CD"] == product_lookup["code"],
        "left",
    ).drop("code")

    # Flag unresolved FKs
    df = df.withColumn(
        "_borrower_fk_error",
        F.when(F.col("borrower_id").isNull() & F.col("BORR_ID").isNotNull(), F.lit(True))
        .otherwise(F.lit(False)),
    ).withColumn(
        "_product_fk_error",
        F.when(F.col("product_id").isNull() & F.col("PROD_CD").isNotNull(), F.lit(True))
        .otherwise(F.lit(False)),
    )

    return df


def transform_loan_accounts(df: DataFrame) -> DataFrame:
    """
    Apply column transformations to loan account data.

    This assumes FK resolution has already been performed.
    Drops denormalized borrower columns and applies type conversions.
    """
    transformed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("borrower_id"),
        F.col("product_id"),
        # Amount fields
        parse_amount_column("LN_ORIG_AMT", 12, 2, "original_amount"),
        parse_amount_column("LN_CURR_BAL", 12, 2, "current_balance"),
        parse_rate_column("LN_INT_RT", 5, 3, "interest_rate"),
        parse_integer_column("LN_TERM_MOS", "term_months"),
        parse_amount_column("LN_PMT_AMT", 10, 2, "monthly_payment"),
        # Date fields
        parse_date_column("LN_ORIG_DT", "origination_date"),
        parse_date_column("LN_MAT_DT", "maturity_date"),
        parse_date_column("LN_1ST_PMT_DT", "first_payment_date"),
        parse_date_column("LN_NXT_PMT_DT", "next_payment_date"),
        # Status expansion
        expand_status_column("LN_STAT_CD", LOAN_STATUS_MAP, "status"),
        # Numeric fields
        parse_integer_column("LN_DLQ_DAYS", "delinquency_days"),
        parse_amount_column("LN_ESCROW_BAL", 10, 2, "escrow_balance"),
        parse_rate_column("LN_LTV_PCT", 5, 2, "ltv_percent"),
        # Property fields
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_status_column("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
        parse_amount_column("PROP_APRS_VAL", 12, 2, "appraised_value"),
        # Timestamps
        parse_timestamp_column("LN_CRET_DT", "created_at"),
        parse_timestamp_column("LN_UPDT_DT", "updated_at"),
        # FK error flags (carried from resolve step)
        F.col("_borrower_fk_error"),
        F.col("_product_fk_error"),
        # Raw values for error detection
        F.col("LN_ORIG_AMT").alias("_raw_orig_amt"),
        F.col("LN_CURR_BAL").alias("_raw_curr_bal"),
        F.col("LN_ORIG_DT").alias("_raw_orig_dt"),
    )

    transformed = flag_parse_errors(transformed, "_raw_orig_amt", "original_amount", "_orig_amt_error")
    transformed = flag_parse_errors(transformed, "_raw_curr_bal", "current_balance", "_curr_bal_error")
    transformed = flag_parse_errors(transformed, "_raw_orig_dt", "origination_date", "_orig_dt_error")

    return transformed


def write_loan_accounts(
    df: DataFrame,
    target_table: str,
    rejection_path: str,
    mode: str = "overwrite",
) -> dict:
    """Write transformed loan account data to Delta Lake."""
    error_columns = [
        "_borrower_fk_error", "_product_fk_error",
        "_orig_amt_error", "_curr_bal_error", "_orig_dt_error",
    ]
    total_count = df.count()
    rejected_count = log_rejected_records(df, error_columns, "loan_accounts", rejection_path)

    clean_df = df.drop(
        "_borrower_fk_error", "_product_fk_error",
        "_raw_orig_amt", "_raw_curr_bal", "_raw_orig_dt",
        "_orig_amt_error", "_curr_bal_error", "_orig_dt_error",
    )
    clean_df = add_ingestion_metadata(clean_df, "CDW_LN_ACCT")

    clean_df.write.mode(mode).format("delta").saveAsTable(target_table)

    stats = {
        "table": target_table,
        "source_count": total_count,
        "loaded_count": total_count,
        "rejected_count": rejected_count,
        "rejection_rate": f"{(rejected_count / max(total_count, 1)) * 100:.2f}%",
    }
    print(f"[INFO] Loan accounts ingestion complete: {stats}")
    return stats


def run(spark: SparkSession, config: dict) -> dict:
    """
    Main entry point for loan account ingestion.

    Requires borrowers and loan_products tables to already be loaded
    (for FK resolution).
    """
    source_path = config["source_path"]
    target_table = config.get("target_table", "loan_warehouse.loan_accounts")
    rejection_path = config.get("rejection_path", "/mnt/data/rejections")
    mode = config.get("mode", "overwrite")
    borrower_table = config.get("borrower_table", "loan_warehouse.borrowers")
    product_table = config.get("product_table", "loan_warehouse.loan_products")

    print(f"[INFO] Starting loan accounts ingestion from: {source_path}")
    raw_df = read_legacy_loan_accounts(spark, source_path)
    print(f"[INFO] Read {raw_df.count()} records from source")

    # Load dimension tables for FK resolution
    borrowers_df = spark.read.table(borrower_table)
    products_df = spark.read.table(product_table)

    # Resolve FKs then transform
    fk_resolved_df = resolve_foreign_keys(raw_df, borrowers_df, products_df)
    transformed_df = transform_loan_accounts(fk_resolved_df)

    return write_loan_accounts(transformed_df, target_table, rejection_path, mode)
