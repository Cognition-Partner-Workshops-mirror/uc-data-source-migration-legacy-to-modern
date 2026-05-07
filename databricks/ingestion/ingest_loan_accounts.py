"""
Ingestion script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads legacy loan account data, drops denormalized borrower fields,
applies type conversions, expands status codes, and writes to Delta Lake.
Partitioned by origination_year.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from common_transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_decimal,
    parse_legacy_integer,
    expand_status_code,
    add_ingestion_metadata,
    flag_null_required_fields,
    log_rejected_records,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_LN_ACCT/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_PATH = "dbfs:/mnt/legacy-cdw/quarantine/loan_accounts/"

REQUIRED_FIELDS = [
    "account_number", "borrower_id", "product_code",
    "original_amount", "current_balance", "interest_rate",
    "term_months", "monthly_payment", "origination_date",
    "maturity_date", "status",
]

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "mode": "PERMISSIVE",
    "columnNameOfCorruptRecord": "_corrupt_record",
}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH) -> DataFrame:
    return (
        spark.read
        .format(SOURCE_FORMAT)
        .options(**CSV_OPTIONS)
        .load(path)
    )


def transform(df: DataFrame) -> DataFrame:
    """
    Transform legacy loan accounts.
    - Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) are dropped.
    - Status and property type codes are expanded.
    - origination_year is derived for partitioning.
    """
    transformed = df.select(
        F.trim(F.col("LN_ACCT_NBR")).alias("account_number"),
        F.trim(F.col("BORR_ID")).alias("borrower_id"),
        F.trim(F.col("PROD_CD")).alias("product_code"),
        parse_legacy_amount("LN_ORIG_AMT", "original_amount"),
        parse_legacy_amount("LN_CURR_BAL", "current_balance"),
        parse_legacy_decimal("LN_INT_RT", 5, 3, "interest_rate"),
        parse_legacy_integer("LN_TERM_MOS", "term_months"),
        parse_legacy_amount("LN_PMT_AMT", "monthly_payment"),
        parse_legacy_date("LN_ORIG_DT", "origination_date"),
        parse_legacy_date("LN_MAT_DT", "maturity_date"),
        parse_legacy_date("LN_1ST_PMT_DT", "first_payment_date"),
        parse_legacy_date("LN_NXT_PMT_DT", "next_payment_date"),
        expand_status_code("LN_STAT_CD", LOAN_STATUS_MAP, "status"),
        parse_legacy_integer("LN_DLQ_DAYS", "delinquency_days"),
        parse_legacy_amount("LN_ESCROW_BAL", "escrow_balance"),
        parse_legacy_decimal("LN_LTV_PCT", 5, 2, "ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_status_code("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
        parse_legacy_amount("PROP_APRS_VAL", "appraised_value"),
        parse_legacy_timestamp("LN_CRET_DT", "created_at"),
        parse_legacy_timestamp("LN_UPDT_DT", "updated_at"),
    )

    # Derive partition key
    transformed = transformed.withColumn(
        "origination_year",
        F.year(F.col("origination_date"))
    )

    # Replace null delinquency_days with 0
    transformed = transformed.withColumn(
        "delinquency_days",
        F.coalesce(F.col("delinquency_days"), F.lit(0))
    )

    return transformed


def validate_and_split(df: DataFrame, spark: SparkSession) -> tuple:
    df = flag_null_required_fields(df, REQUIRED_FIELDS)

    # Additional business rule: active loans should have positive balance
    df = df.withColumn(
        "_business_rule_violation",
        (F.col("status") == "ACTIVE") & (F.col("current_balance") <= 0)
    )
    df = df.withColumn(
        "_has_nulls",
        F.col("_has_nulls") | F.col("_business_rule_violation")
    )
    df = df.drop("_business_rule_violation")

    valid_df, rejected_df = log_rejected_records(df, "_has_nulls", "loan_accounts", spark)
    valid_df = valid_df.drop("_has_nulls")
    return valid_df, rejected_df


def write_target(df: DataFrame) -> None:
    (
        df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("origination_year")
        .saveAsTable(TARGET_TABLE)
    )


def write_quarantine(df: DataFrame) -> None:
    if df.count() > 0:
        df.write.format("delta").mode("append").save(QUARANTINE_PATH)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession, source_path: str = SOURCE_PATH) -> dict:
    raw_df = read_source(spark, source_path)
    source_count = raw_df.count()

    transformed_df = transform(raw_df)
    transformed_df = add_ingestion_metadata(transformed_df)

    valid_df, rejected_df = validate_and_split(transformed_df, spark)
    valid_count = valid_df.count()
    rejected_count = rejected_df.count()

    write_target(valid_df)
    write_quarantine(rejected_df)

    summary = {
        "table": "loan_accounts",
        "source_count": source_count,
        "valid_count": valid_count,
        "rejected_count": rejected_count,
    }
    print(f"[loan_accounts] Ingested {valid_count}/{source_count} records "
          f"({rejected_count} quarantined)")
    return summary


if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestLoanAccounts").getOrCreate()
    run(spark)
