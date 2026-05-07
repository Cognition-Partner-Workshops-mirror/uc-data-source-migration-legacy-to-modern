"""
Ingestion script: CDW_PMT_HIST → loan_warehouse.payments

Reads legacy payment history, applies type conversions, expands status codes,
validates payment component sums, and writes to Delta Lake.
Partitioned by payment_year.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from common_transforms import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    expand_status_code,
    add_ingestion_metadata,
    flag_null_required_fields,
    log_rejected_records,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_PMT_HIST/"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_PATH = "dbfs:/mnt/legacy-cdw/quarantine/payments/"
COMPONENT_SUM_TOLERANCE = 0.02

REQUIRED_FIELDS = [
    "payment_id", "loan_account_number", "payment_date",
    "total_amount", "type", "status",
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
    transformed = df.select(
        F.trim(F.col("PMT_SEQ_NBR")).alias("payment_id"),
        F.trim(F.col("LN_ACCT_NBR")).alias("loan_account_number"),
        parse_legacy_date("PMT_DT", "payment_date"),
        parse_legacy_amount("PMT_AMT", "total_amount"),
        parse_legacy_amount("PMT_PRIN_AMT", "principal_amount"),
        parse_legacy_amount("PMT_INT_AMT", "interest_amount"),
        parse_legacy_amount("PMT_ESCROW_AMT", "escrow_amount"),
        parse_legacy_amount("PMT_LATE_FEE", "late_fee"),
        expand_status_code("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        expand_status_code("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
        parse_legacy_date("PMT_RECV_DT", "received_date"),
        parse_legacy_date("PMT_PROC_DT", "processed_date"),
        parse_legacy_timestamp("PMT_CRET_DT", "created_at"),
        parse_legacy_timestamp("PMT_UPDT_DT", "updated_at"),
    )

    # Validate payment component sum
    transformed = transformed.withColumn(
        "_component_sum",
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0))
    )
    transformed = transformed.withColumn(
        "component_sum_valid",
        F.abs(F.col("total_amount") - F.col("_component_sum")) <= COMPONENT_SUM_TOLERANCE
    )
    transformed = transformed.drop("_component_sum")

    # Derive partition key
    transformed = transformed.withColumn(
        "payment_year",
        F.year(F.col("payment_date"))
    )

    # Default null late_fee to 0
    transformed = transformed.withColumn(
        "late_fee",
        F.coalesce(F.col("late_fee"), F.lit(0))
    )

    return transformed


def validate_and_split(df: DataFrame, spark: SparkSession) -> tuple:
    df = flag_null_required_fields(df, REQUIRED_FIELDS)
    valid_df, rejected_df = log_rejected_records(df, "_has_nulls", "payments", spark)
    valid_df = valid_df.drop("_has_nulls")
    return valid_df, rejected_df


def write_target(df: DataFrame) -> None:
    (
        df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("payment_year")
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
        "table": "payments",
        "source_count": source_count,
        "valid_count": valid_count,
        "rejected_count": rejected_count,
    }
    print(f"[payments] Ingested {valid_count}/{source_count} records "
          f"({rejected_count} quarantined)")
    return summary


if __name__ == "__main__":
    spark = SparkSession.builder.appName("IngestPayments").getOrCreate()
    run(spark)
