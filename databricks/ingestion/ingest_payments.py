"""
PySpark ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads legacy payment data, applies transformations, validates component
reconciliation, and writes to Delta Lake.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DecimalType, TimestampType, BooleanType
)

LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_PMT_HIST/"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_TABLE = "loan_warehouse._quarantine_payments"
DATE_FORMAT = "MM/dd/yyyy"
RECONCILIATION_TOLERANCE = 0.02

# Legacy payment type code mappings
PAYMENT_TYPE_MAP = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

# Legacy payment status code mappings
PAYMENT_STATUS_MAP = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}

LEGACY_SCHEMA = StructType([
    StructField("PMT_SEQ_NBR", StringType(), False),
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


def parse_legacy_amount(col_name: str):
    """Strip non-numeric chars and cast to DecimalType. Defaults null/blank to 0."""
    cleaned = F.regexp_replace(F.col(col_name), r"[^0-9.\-]", "")
    return F.when(
        (F.col(col_name).isNull()) | (F.trim(F.col(col_name)) == ""),
        F.lit(0).cast(DecimalType(10, 2))
    ).otherwise(cleaned.cast(DecimalType(10, 2)))


def expand_code(col_name: str, code_map: dict):
    """Generic code expansion using a lookup dict; unknown codes prefixed with UNKNOWN:."""
    expr = F.lit(None).cast(StringType())
    for code, expanded in code_map.items():
        expr = F.when(F.col(col_name) == code, expanded).otherwise(expr)
    return F.coalesce(expr, F.concat(F.lit("UNKNOWN:"), F.coalesce(F.col(col_name), F.lit("NULL"))))


def read_legacy_payments(spark: SparkSession) -> DataFrame:
    return (
        spark.read
        .option("header", "true")
        .schema(LEGACY_SCHEMA)
        .csv(LEGACY_SOURCE_PATH)
    )


def transform_payments(df: DataFrame) -> DataFrame:
    """Transform legacy payment fields: rename columns, parse dates/amounts, expand codes."""
    return df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_id"),
        F.col("LN_ACCT_NBR").alias("_legacy_loan_account_number"),
        F.to_date(F.col("PMT_DT"), DATE_FORMAT).alias("payment_date"),
        parse_legacy_amount("PMT_AMT").alias("total_amount"),
        parse_legacy_amount("PMT_PRIN_AMT").alias("principal_amount"),
        parse_legacy_amount("PMT_INT_AMT").alias("interest_amount"),
        parse_legacy_amount("PMT_ESCROW_AMT").alias("escrow_amount"),
        parse_legacy_amount("PMT_LATE_FEE").alias("late_fee"),
        expand_code("PMT_TYP_CD", PAYMENT_TYPE_MAP).alias("type"),
        expand_code("PMT_STAT_CD", PAYMENT_STATUS_MAP).alias("status"),
        F.to_date(F.col("PMT_RECV_DT"), DATE_FORMAT).alias("received_date"),
        F.to_date(F.col("PMT_PROC_DT"), DATE_FORMAT).alias("processed_date"),
        F.to_date(F.col("PMT_CRET_DT"), DATE_FORMAT).cast(TimestampType()).alias("created_at"),
        F.to_date(F.col("PMT_UPDT_DT"), DATE_FORMAT).cast(TimestampType()).alias("updated_at"),
    )


def add_reconciliation(df: DataFrame) -> DataFrame:
    """Compute component sum and reconciliation flag."""
    return (
        df
        .withColumn("component_sum",
            F.col("principal_amount")
            + F.col("interest_amount")
            + F.col("escrow_amount")
            + F.col("late_fee")
        )
        .withColumn("reconciled",
            F.abs(F.col("total_amount") - F.col("component_sum")) <= RECONCILIATION_TOLERANCE
        )
    )


def resolve_foreign_keys(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Resolve LN_ACCT_NBR to loan_accounts.id."""
    loan_accounts = spark.table("loan_warehouse.loan_accounts").select(
        F.col("id").alias("loan_account_id"),
        F.col("account_number")
    )
    resolved = (
        df
        .join(loan_accounts,
              df["_legacy_loan_account_number"] == loan_accounts["account_number"],
              "left")
        .drop("_legacy_loan_account_number", "account_number")
    )
    return resolved


def quarantine_bad_records(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    critical_filter = (
        F.col("loan_account_id").isNotNull()
        & F.col("payment_date").isNotNull()
        & F.col("total_amount").isNotNull()
    )
    good = df.filter(critical_filter)
    bad = df.filter(~critical_filter).withColumn(
        "_quarantine_reason",
        F.concat_ws(", ",
            F.when(F.col("loan_account_id").isNull(), F.lit("orphaned loan account (FK not found)")),
            F.when(F.col("payment_date").isNull(), F.lit("missing payment_date")),
            F.when(F.col("total_amount").isNull(), F.lit("missing total_amount")),
        )
    ).withColumn("_quarantine_ts", F.current_timestamp())

    return good, bad


def run(spark: SparkSession):
    print("=== Payment Ingestion: START ===")

    raw_df = read_legacy_payments(spark)
    source_count = raw_df.count()
    print(f"Source record count: {source_count}")

    transformed_df = transform_payments(raw_df)
    reconciled_df = add_reconciliation(transformed_df)

    unreconciled = reconciled_df.filter(~F.col("reconciled")).count()
    if unreconciled > 0:
        print(f"WARNING: {unreconciled} payments failed reconciliation check")

    resolved_df = resolve_foreign_keys(reconciled_df, spark)
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

    print("=== Payment Ingestion: COMPLETE ===")
    return source_count, good_count, bad_count


if __name__ == "__main__":
    spark = SparkSession.builder.getOrCreate()
    run(spark)
