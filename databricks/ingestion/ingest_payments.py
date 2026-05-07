"""
Ingestion script: CDW_PMT_HIST → loan_warehouse.payments

Reads legacy payment history data, transforms all VARCHAR columns to
proper types, expands status/type codes, resolves loan_account_id FK,
and writes to the Delta Lake payments table.

IMPORTANT: Run ingest_loan_accounts BEFORE this script.

Usage (Databricks notebook):
    %run ./common
    %run ./ingest_payments
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

from common import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status,
    parse_legacy_amount,
    parse_legacy_date,
    parse_legacy_timestamp,
    tag_ingestion_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "dbfs:/mnt/legacy-extracts/cdw_pmt_hist/"
TARGET_TABLE = "loan_warehouse.payments"
SOURCE_FORMAT = "csv"

LEGACY_SCHEMA = StructType([
    StructField("PMT_SEQ_NBR", StringType(), True),
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("PMT_DT", StringType(), True),
    StructField("PMT_AMT", StringType(), True),
    StructField("PMT_PRIN_AMT", StringType(), True),
    StructField("PMT_INT_AMT", StringType(), True),
    StructField("PMT_ESCROW_AMT", StringType(), True),
    StructField("PMT_LATE_FEE", StringType(), True),
    StructField("PMT_TYP_CD", StringType(), True),
    StructField("PMT_STAT_CD", StringType(), True),
    StructField("PMT_RECV_DT", StringType(), True),
    StructField("PMT_PROC_DT", StringType(), True),
    StructField("PMT_CRET_DT", StringType(), True),
    StructField("PMT_UPDT_DT", StringType(), True),
])


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def extract(spark: SparkSession) -> DataFrame:
    reader = spark.read.format(SOURCE_FORMAT).schema(LEGACY_SCHEMA)
    if SOURCE_FORMAT == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(SOURCE_PATH)
    print(f"[ingest_payments] Extracted {df.count()} rows from {SOURCE_PATH}")
    return df


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(spark: SparkSession, df: DataFrame) -> DataFrame:
    # Resolve loan_account_id FK from already-loaded loan_accounts
    loans_lookup = spark.table("loan_warehouse.loan_accounts").select(
        F.col("loan_account_id"),
        F.col("account_number").alias("_acct_nbr"),
    )

    transformed = df.select(
        F.trim(F.col("PMT_SEQ_NBR")).alias("legacy_sequence_nbr"),
        F.trim(F.col("LN_ACCT_NBR")).alias("_ln_acct_nbr_raw"),
        parse_legacy_date("PMT_DT").alias("payment_date"),
        parse_legacy_amount("PMT_AMT", 10, 2).alias("total_amount"),
        parse_legacy_amount("PMT_PRIN_AMT", 10, 2).alias("principal_amount"),
        parse_legacy_amount("PMT_INT_AMT", 10, 2).alias("interest_amount"),
        F.coalesce(parse_legacy_amount("PMT_ESCROW_AMT", 10, 2), F.lit(0.00)).alias("escrow_amount"),
        F.coalesce(parse_legacy_amount("PMT_LATE_FEE", 10, 2), F.lit(0.00)).alias("late_fee"),
        expand_status("PMT_TYP_CD", PAYMENT_TYPE_MAP).alias("type"),
        expand_status("PMT_STAT_CD", PAYMENT_STATUS_MAP).alias("status"),
        parse_legacy_date("PMT_RECV_DT").alias("received_date"),
        parse_legacy_date("PMT_PROC_DT").alias("processed_date"),
        parse_legacy_timestamp("PMT_CRET_DT").alias("created_at"),
        parse_legacy_timestamp("PMT_UPDT_DT").alias("updated_at"),
    )

    # Derive payment_year partition column
    transformed = transformed.withColumn(
        "payment_year",
        F.year(F.col("payment_date")),
    )

    # Resolve loan FK
    transformed = transformed.join(
        loans_lookup,
        transformed["_ln_acct_nbr_raw"] == loans_lookup["_acct_nbr"],
        "left",
    ).drop("_acct_nbr", "_ln_acct_nbr_raw")

    # Log orphaned payments
    orphan_count = transformed.filter(F.col("loan_account_id").isNull()).count()
    if orphan_count > 0:
        print(f"[ingest_payments] WARNING: {orphan_count} payments have no matching loan account")

    # Payment component sum validation
    transformed = transformed.withColumn(
        "_component_sum",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0)),
    )

    mismatch_count = transformed.filter(
        F.abs(F.col("_component_sum") - F.col("total_amount")) > 0.01
    ).count()
    if mismatch_count > 0:
        print(
            f"[ingest_payments] WARNING: {mismatch_count} payments have "
            f"component sum ≠ total_amount — data integrity issue from CDW"
        )
        transformed.filter(
            F.abs(F.col("_component_sum") - F.col("total_amount")) > 0.01
        ).select(
            "legacy_sequence_nbr", "total_amount", "_component_sum",
        ).show(truncate=False)

    transformed = transformed.drop("_component_sum")
    transformed = tag_ingestion_metadata(transformed, "CDW_PMT_HIST")

    print(f"[ingest_payments] Transformed {transformed.count()} rows")
    return transformed


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load(df: DataFrame):
    df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).partitionBy("payment_year").saveAsTable(TARGET_TABLE)
    print(f"[ingest_payments] Loaded data into {TARGET_TABLE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession):
    raw = extract(spark)
    clean = transform(spark, raw)
    load(clean)
    print("[ingest_payments] Pipeline complete")


if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestPayments").getOrCreate()
    run(spark)
