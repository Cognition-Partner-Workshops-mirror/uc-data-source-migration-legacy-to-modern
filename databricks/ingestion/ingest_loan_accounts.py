"""
Ingest CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads the legacy loan account extract, drops denormalized borrower fields,
applies type conversions and status code expansion, adds an origination_year
partition column, then writes to the loan_accounts Delta table.

Usage (Databricks notebook cell):
    %run ./transforms
    %run ./ingest_loan_accounts
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
)

from transforms import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status,
    parse_amount,
    parse_date_mmddyyyy,
    parse_int,
    parse_timestamp_mmddyyyy,
    tag_load_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/landing/legacy/CDW_LN_ACCT/"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_PATH = "dbfs:/mnt/landing/quarantine/CDW_LN_ACCT/"

LEGACY_SCHEMA = StructType(
    [
        StructField("LN_ACCT_NBR", StringType(), True),
        StructField("BORR_ID", StringType(), True),
        # Denormalized borrower fields (will be dropped)
        StructField("BORR_FST_NM", StringType(), True),
        StructField("BORR_LST_NM", StringType(), True),
        StructField("BORR_SSN_LST4", StringType(), True),
        # Loan fields
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
    ]
)


def read_legacy_accounts(spark: SparkSession):
    """Read from CSV with header, falling back to Parquet."""
    try:
        df = (
            spark.read.format("csv")
            .option("header", "true")
            .option("mode", "PERMISSIVE")
            .schema(LEGACY_SCHEMA)
            .load(SOURCE_PATH)
        )
    except Exception:
        df = spark.read.format("parquet").load(SOURCE_PATH)
    return df


def transform_accounts(df):
    """
    Apply column mappings and type conversions for loan accounts.
    Drops denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4).
    Adds origination_year derived from LN_ORIG_DT for partitioning.
    """
    origination_date_col = parse_date_mmddyyyy(F.col("LN_ORIG_DT"))

    transformed = df.select(
        F.trim(F.col("LN_ACCT_NBR")).alias("account_number"),
        F.trim(F.col("BORR_ID")).alias("borrower_external_id"),
        F.trim(F.col("PROD_CD")).alias("product_code"),
        parse_amount(F.col("LN_ORIG_AMT")).alias("original_amount"),
        parse_amount(F.col("LN_CURR_BAL")).alias("current_balance"),
        parse_amount(F.col("LN_INT_RT"), 5, 3).alias("interest_rate"),
        parse_int(F.col("LN_TERM_MOS")).alias("term_months"),
        parse_amount(F.col("LN_PMT_AMT"), 10, 2).alias("monthly_payment"),
        origination_date_col.alias("origination_date"),
        parse_date_mmddyyyy(F.col("LN_MAT_DT")).alias("maturity_date"),
        parse_date_mmddyyyy(F.col("LN_1ST_PMT_DT")).alias("first_payment_date"),
        parse_date_mmddyyyy(F.col("LN_NXT_PMT_DT")).alias("next_payment_date"),
        expand_status(F.col("LN_STAT_CD"), LOAN_STATUS_MAP, "UNKNOWN").alias("status"),
        parse_int(F.col("LN_DLQ_DAYS")).alias("delinquency_days"),
        parse_amount(F.col("LN_ESCROW_BAL"), 10, 2).alias("escrow_balance"),
        parse_amount(F.col("LN_LTV_PCT"), 5, 2).alias("ltv_percent"),
        F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
        F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
        F.trim(F.col("PROP_ST_CD")).alias("property_state"),
        F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
        expand_status(F.col("PROP_TYP_CD"), PROPERTY_TYPE_MAP, "Other").alias(
            "property_type"
        ),
        parse_amount(F.col("PROP_APRS_VAL")).alias("appraised_value"),
        F.year(origination_date_col).alias("origination_year"),
        parse_timestamp_mmddyyyy(F.col("LN_CRET_DT")).alias("created_at"),
        parse_timestamp_mmddyyyy(F.col("LN_UPDT_DT")).alias("updated_at"),
        *tag_load_metadata("CDW_LN_ACCT"),
    )
    return transformed


def quarantine_bad_records(df):
    """Quarantine accounts missing required fields."""
    bad_mask = (
        F.col("account_number").isNull()
        | (F.trim(F.col("account_number")) == "")
        | F.col("borrower_external_id").isNull()
        | (F.trim(F.col("borrower_external_id")) == "")
        | F.col("original_amount").isNull()
        | F.col("current_balance").isNull()
        | F.col("origination_date").isNull()
        | F.col("maturity_date").isNull()
    )

    bad_records = df.filter(bad_mask)
    clean_records = df.filter(~bad_mask)

    bad_count = bad_records.count()
    if bad_count > 0:
        print(f"[WARN] Quarantining {bad_count} loan account records with missing required fields")
        bad_records.write.format("delta").mode("append").save(QUARANTINE_PATH)
    else:
        print("[INFO] No bad loan account records found")

    return clean_records


def validate_referential_integrity(spark: SparkSession, df):
    """
    Check that borrower_external_id and product_code exist in their
    respective target tables. Log warnings for orphaned references
    but do NOT drop the records (to avoid silent data loss).
    """
    borrower_ids = spark.table("loan_warehouse.borrowers").select("external_id")
    product_codes = spark.table("loan_warehouse.loan_products").select("code")

    orphan_borrowers = df.join(
        borrower_ids,
        df.borrower_external_id == borrower_ids.external_id,
        "left_anti",
    )
    orphan_count = orphan_borrowers.count()
    if orphan_count > 0:
        print(
            f"[WARN] {orphan_count} loan accounts reference borrower IDs not found in borrowers table"
        )
        orphan_borrowers.select("account_number", "borrower_external_id").show(
            truncate=False
        )

    orphan_products = df.join(
        product_codes,
        df.product_code == product_codes.code,
        "left_anti",
    )
    orphan_prod_count = orphan_products.count()
    if orphan_prod_count > 0:
        print(
            f"[WARN] {orphan_prod_count} loan accounts reference product codes not found in loan_products table"
        )
        orphan_products.select("account_number", "product_code").show(truncate=False)

    return df


def write_accounts(df):
    """Merge into the target Delta table using account_number as the business key."""
    df.createOrReplaceTempView("accounts_staged")

    merge_sql = f"""
    MERGE INTO {TARGET_TABLE} AS target
    USING accounts_staged AS source
    ON target.account_number = source.account_number
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """
    spark = df.sparkSession
    spark.sql(merge_sql)
    print(f"[INFO] Loan accounts merged into {TARGET_TABLE}")


def run(spark: SparkSession):
    """Main entry point for loan account ingestion."""
    print("=" * 60)
    print("Starting loan account ingestion: CDW_LN_ACCT -> loan_accounts")
    print("=" * 60)

    raw_df = read_legacy_accounts(spark)
    raw_count = raw_df.count()
    print(f"[INFO] Read {raw_count} raw loan account records from source")

    transformed_df = transform_accounts(raw_df)
    clean_df = quarantine_bad_records(transformed_df)
    clean_count = clean_df.count()
    print(f"[INFO] {clean_count} clean loan account records after validation")

    validate_referential_integrity(spark, clean_df)
    write_accounts(clean_df)

    final_count = spark.table(TARGET_TABLE).count()
    print(f"[INFO] Target table {TARGET_TABLE} now has {final_count} rows")
    print(f"[INFO] Source: {raw_count} | Quarantined: {raw_count - clean_count} | Loaded: {clean_count}")
    print("=" * 60)
    return {"source_count": raw_count, "clean_count": clean_count, "target_count": final_count}


# Allow direct execution in a Databricks notebook
# spark = SparkSession.builder.getOrCreate()
# run(spark)
