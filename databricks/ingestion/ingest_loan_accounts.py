"""
Ingest CDW_LN_ACCT → loan_warehouse.loan_accounts

Key transformations:
  - Denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
    are dropped; replaced by a FK lookup into loan_warehouse.borrowers.
  - PROD_CD is resolved to loan_warehouse.loan_products.product_id.
  - All amount, date, rate, and status fields are parsed/expanded per the
    column mappings document.
  - An origination_year column is derived for Delta partitioning.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

from transforms import (
    parse_date,
    parse_timestamp,
    parse_amount,
    parse_int,
    parse_rate,
    parse_percent,
    expand_code,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "/mnt/landing/legacy/CDW_LN_ACCT"
TARGET_TABLE = "loan_warehouse.loan_accounts"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_accounts"

LEGACY_SCHEMA = StructType([
    StructField("LN_ACCT_NBR",    StringType(), True),
    StructField("BORR_ID",        StringType(), True),
    StructField("BORR_FST_NM",    StringType(), True),
    StructField("BORR_LST_NM",    StringType(), True),
    StructField("BORR_SSN_LST4",  StringType(), True),
    StructField("PROD_CD",        StringType(), True),
    StructField("LN_ORIG_AMT",    StringType(), True),
    StructField("LN_CURR_BAL",    StringType(), True),
    StructField("LN_INT_RT",      StringType(), True),
    StructField("LN_TERM_MOS",    StringType(), True),
    StructField("LN_PMT_AMT",     StringType(), True),
    StructField("LN_ORIG_DT",     StringType(), True),
    StructField("LN_MAT_DT",      StringType(), True),
    StructField("LN_1ST_PMT_DT",  StringType(), True),
    StructField("LN_NXT_PMT_DT",  StringType(), True),
    StructField("LN_STAT_CD",     StringType(), True),
    StructField("LN_DLQ_DAYS",    StringType(), True),
    StructField("LN_ESCROW_BAL",  StringType(), True),
    StructField("LN_LTV_PCT",     StringType(), True),
    StructField("PROP_ADDR_LN1",  StringType(), True),
    StructField("PROP_CTY_NM",    StringType(), True),
    StructField("PROP_ST_CD",     StringType(), True),
    StructField("PROP_ZIP_CD",    StringType(), True),
    StructField("PROP_TYP_CD",    StringType(), True),
    StructField("PROP_APRS_VAL",  StringType(), True),
    StructField("LN_CRET_DT",     StringType(), True),
    StructField("LN_UPDT_DT",     StringType(), True),
])


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH) -> DataFrame:
    try:
        return spark.read.parquet(path)
    except Exception:
        return (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .schema(LEGACY_SCHEMA)
            .csv(path)
        )


# ---------------------------------------------------------------------------
# FK resolution helpers
# ---------------------------------------------------------------------------

def resolve_borrower_fk(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join to borrowers to resolve BORR_ID → borrower_id (BIGINT FK)."""
    borrowers = spark.table("loan_warehouse.borrowers").select(
        F.col("borrower_id"),
        F.col("external_id").alias("_borr_external_id"),
    )
    return (
        df.join(borrowers, df["_borr_id_clean"] == borrowers["_borr_external_id"], "left")
          .drop("_borr_external_id", "_borr_id_clean")
    )


def resolve_product_fk(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join to loan_products to resolve PROD_CD → product_id (BIGINT FK)."""
    products = spark.table("loan_warehouse.loan_products").select(
        F.col("product_id"),
        F.col("code").alias("_prod_code"),
    )
    return (
        df.join(products, df["_prod_cd_clean"] == products["_prod_code"], "left")
          .drop("_prod_code", "_prod_cd_clean")
    )


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(spark: SparkSession, df: DataFrame) -> tuple[DataFrame, DataFrame]:
    transformed = (
        df
        .withColumn("account_number",     F.trim(F.col("LN_ACCT_NBR")))
        .withColumn("_borr_id_clean",     F.trim(F.col("BORR_ID")))
        .withColumn("_prod_cd_clean",     F.trim(F.col("PROD_CD")))
        .withColumn("original_amount",    parse_amount(F.col("LN_ORIG_AMT")))
        .withColumn("current_balance",    parse_amount(F.col("LN_CURR_BAL")))
        .withColumn("interest_rate",      parse_rate(F.col("LN_INT_RT")))
        .withColumn("term_months",        parse_int(F.col("LN_TERM_MOS")))
        .withColumn("monthly_payment",    parse_amount(F.col("LN_PMT_AMT"), 10, 2))
        .withColumn("origination_date",   parse_date(F.col("LN_ORIG_DT")))
        .withColumn("maturity_date",      parse_date(F.col("LN_MAT_DT")))
        .withColumn("first_payment_date", parse_date(F.col("LN_1ST_PMT_DT")))
        .withColumn("next_payment_date",  parse_date(F.col("LN_NXT_PMT_DT")))
        .withColumn("status",             expand_code(F.col("LN_STAT_CD"), LOAN_STATUS_MAP, default="Active"))
        .withColumn("delinquency_days",   parse_int(F.col("LN_DLQ_DAYS")))
        .withColumn("escrow_balance",     parse_amount(F.col("LN_ESCROW_BAL"), 10, 2))
        .withColumn("ltv_percent",        parse_percent(F.col("LN_LTV_PCT")))
        .withColumn("property_address",   F.trim(F.col("PROP_ADDR_LN1")))
        .withColumn("property_city",      F.trim(F.col("PROP_CTY_NM")))
        .withColumn("property_state",     F.trim(F.col("PROP_ST_CD")))
        .withColumn("property_zip",       F.trim(F.col("PROP_ZIP_CD")))
        .withColumn("property_type",      expand_code(F.col("PROP_TYP_CD"), PROPERTY_TYPE_MAP, default="Other"))
        .withColumn("appraised_value",    parse_amount(F.col("PROP_APRS_VAL")))
        .withColumn("origination_year",   F.year(parse_date(F.col("LN_ORIG_DT"))))
        .withColumn("created_at",         parse_timestamp(F.col("LN_CRET_DT")))
        .withColumn("updated_at",         parse_timestamp(F.col("LN_UPDT_DT")))
        # Drop denormalized borrower columns — we use the FK instead
        .drop("BORR_FST_NM", "BORR_LST_NM", "BORR_SSN_LST4")
    )

    # Resolve foreign keys
    transformed = resolve_borrower_fk(spark, transformed)
    transformed = resolve_product_fk(spark, transformed)

    # Quarantine: missing required fields or unresolvable FKs
    quarantine_condition = (
        F.col("account_number").isNull()
        | (F.col("account_number") == F.lit(""))
        | F.col("borrower_id").isNull()
        | F.col("product_id").isNull()
        | F.col("original_amount").isNull()
        | F.col("current_balance").isNull()
        | F.col("interest_rate").isNull()
        | F.col("origination_date").isNull()
        | F.col("maturity_date").isNull()
    )

    quarantine_reasons = (
        F.when(F.col("borrower_id").isNull(), F.lit("Unresolvable BORR_ID"))
         .when(F.col("product_id").isNull(), F.lit("Unresolvable PROD_CD"))
         .otherwise(F.lit("Missing required field"))
    )

    quarantine = (
        transformed
        .filter(quarantine_condition)
        .withColumn("_quarantine_reason", quarantine_reasons)
        .withColumn("_quarantine_ts", F.current_timestamp())
    )

    good = transformed.filter(~quarantine_condition)

    target_columns = [
        "account_number", "borrower_id", "product_id",
        "original_amount", "current_balance", "interest_rate",
        "term_months", "monthly_payment", "origination_date", "maturity_date",
        "first_payment_date", "next_payment_date", "status", "delinquency_days",
        "escrow_balance", "ltv_percent", "property_address", "property_city",
        "property_state", "property_zip", "property_type", "appraised_value",
        "origination_year", "created_at", "updated_at",
    ]

    return good.select(target_columns), quarantine


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(df: DataFrame, table: str = TARGET_TABLE) -> None:
    from delta.tables import DeltaTable

    if DeltaTable.isDeltaTable(df.sparkSession, table):
        delta_table = DeltaTable.forName(df.sparkSession, table)
        (
            delta_table.alias("tgt")
            .merge(df.alias("src"), "tgt.account_number = src.account_number")
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )
    else:
        (
            df.write
            .format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .partitionBy("status")
            .saveAsTable(table)
        )


def write_quarantine(df: DataFrame, table: str = QUARANTINE_TABLE) -> None:
    if df.count() > 0:
        (
            df.write
            .format("delta")
            .mode("append")
            .saveAsTable(table)
        )
        print(f"WARNING: {df.count()} loan account record(s) quarantined to {table}")
    else:
        print("No loan account records quarantined.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession, source_path: str = SOURCE_PATH) -> dict:
    raw = read_source(spark, source_path)
    source_count = raw.count()
    print(f"[loan_accounts] Source rows read: {source_count}")

    good, quarantine = transform(spark, raw)
    good_count = good.count()
    quarantine_count = quarantine.count()

    print(f"[loan_accounts] Good rows:        {good_count}")
    print(f"[loan_accounts] Quarantined rows:  {quarantine_count}")

    write_target(good)
    write_quarantine(quarantine)

    return {
        "table": TARGET_TABLE,
        "source_count": source_count,
        "target_count": good_count,
        "quarantine_count": quarantine_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest CDW_LN_ACCT → loan_accounts").getOrCreate()
    stats = run(spark)
    print(f"[loan_accounts] Ingestion complete: {stats}")
