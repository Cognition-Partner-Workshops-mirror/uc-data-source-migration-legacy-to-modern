"""
Ingest CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment history extract, applies type conversions, expands
status/type codes, derives partition columns (payment_year, payment_month),
then writes to the payments Delta table.

Usage (Databricks notebook cell):
    %run ./transforms
    %run ./ingest_payments
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
)

from transforms import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_status,
    parse_amount,
    parse_date_mmddyyyy,
    parse_timestamp_mmddyyyy,
    tag_load_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/landing/legacy/CDW_PMT_HIST/"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_PATH = "dbfs:/mnt/landing/quarantine/CDW_PMT_HIST/"

LEGACY_SCHEMA = StructType(
    [
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
    ]
)


def read_legacy_payments(spark: SparkSession):
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


def transform_payments(df):
    """Apply column mappings and type conversions for payment history."""
    payment_date_col = parse_date_mmddyyyy(F.col("PMT_DT"))

    transformed = df.select(
        F.trim(F.col("PMT_SEQ_NBR")).alias("legacy_payment_id"),
        F.trim(F.col("LN_ACCT_NBR")).alias("loan_account_number"),
        payment_date_col.alias("payment_date"),
        parse_amount(F.col("PMT_AMT"), 10, 2).alias("total_amount"),
        parse_amount(F.col("PMT_PRIN_AMT"), 10, 2).alias("principal_amount"),
        parse_amount(F.col("PMT_INT_AMT"), 10, 2).alias("interest_amount"),
        parse_amount(F.col("PMT_ESCROW_AMT"), 10, 2).alias("escrow_amount"),
        parse_amount(F.col("PMT_LATE_FEE"), 10, 2).alias("late_fee"),
        expand_status(F.col("PMT_TYP_CD"), PAYMENT_TYPE_MAP, "UNKNOWN").alias("type"),
        expand_status(F.col("PMT_STAT_CD"), PAYMENT_STATUS_MAP, "UNKNOWN").alias(
            "status"
        ),
        parse_date_mmddyyyy(F.col("PMT_RECV_DT")).alias("received_date"),
        parse_date_mmddyyyy(F.col("PMT_PROC_DT")).alias("processed_date"),
        F.year(payment_date_col).alias("payment_year"),
        F.month(payment_date_col).alias("payment_month"),
        parse_timestamp_mmddyyyy(F.col("PMT_CRET_DT")).alias("created_at"),
        parse_timestamp_mmddyyyy(F.col("PMT_UPDT_DT")).alias("updated_at"),
        *tag_load_metadata("CDW_PMT_HIST"),
    )
    return transformed


def quarantine_bad_records(df):
    """Quarantine payments missing required fields."""
    bad_mask = (
        F.col("legacy_payment_id").isNull()
        | (F.trim(F.col("legacy_payment_id")) == "")
        | F.col("loan_account_number").isNull()
        | (F.trim(F.col("loan_account_number")) == "")
        | F.col("payment_date").isNull()
        | F.col("total_amount").isNull()
    )

    bad_records = df.filter(bad_mask)
    clean_records = df.filter(~bad_mask)

    bad_count = bad_records.count()
    if bad_count > 0:
        print(f"[WARN] Quarantining {bad_count} payment records with missing required fields")
        bad_records.write.format("delta").mode("append").save(QUARANTINE_PATH)
    else:
        print("[INFO] No bad payment records found")

    return clean_records


def validate_referential_integrity(spark: SparkSession, df):
    """
    Check that loan_account_number exists in the loan_accounts target table.
    Log warnings for orphaned references but do NOT drop records.
    """
    account_numbers = spark.table("loan_warehouse.loan_accounts").select(
        "account_number"
    )

    orphan_payments = df.join(
        account_numbers,
        df.loan_account_number == account_numbers.account_number,
        "left_anti",
    )
    orphan_count = orphan_payments.count()
    if orphan_count > 0:
        print(
            f"[WARN] {orphan_count} payments reference loan account numbers not found in loan_accounts table"
        )
        orphan_payments.select("legacy_payment_id", "loan_account_number").show(
            truncate=False
        )

    return df


def write_payments(df):
    """Merge into the target Delta table using legacy_payment_id as the business key."""
    df.createOrReplaceTempView("payments_staged")

    merge_sql = f"""
    MERGE INTO {TARGET_TABLE} AS target
    USING payments_staged AS source
    ON target.legacy_payment_id = source.legacy_payment_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """
    spark = df.sparkSession
    spark.sql(merge_sql)
    print(f"[INFO] Payments merged into {TARGET_TABLE}")


def run(spark: SparkSession):
    """Main entry point for payment ingestion."""
    print("=" * 60)
    print("Starting payment ingestion: CDW_PMT_HIST -> payments")
    print("=" * 60)

    raw_df = read_legacy_payments(spark)
    raw_count = raw_df.count()
    print(f"[INFO] Read {raw_count} raw payment records from source")

    transformed_df = transform_payments(raw_df)
    clean_df = quarantine_bad_records(transformed_df)
    clean_count = clean_df.count()
    print(f"[INFO] {clean_count} clean payment records after validation")

    validate_referential_integrity(spark, clean_df)
    write_payments(clean_df)

    final_count = spark.table(TARGET_TABLE).count()
    print(f"[INFO] Target table {TARGET_TABLE} now has {final_count} rows")
    print(f"[INFO] Source: {raw_count} | Quarantined: {raw_count - clean_count} | Loaded: {clean_count}")
    print("=" * 60)
    return {"source_count": raw_count, "clean_count": clean_count, "target_count": final_count}


# Allow direct execution in a Databricks notebook
# spark = SparkSession.builder.getOrCreate()
# run(spark)
