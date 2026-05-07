"""
PySpark Ingestion Script: CDW_PMT_HIST → loan_warehouse.payments

Reads from legacy payment history source and transforms into
the modern normalized payments table.

Anomalies handled:
  - ANO-001: Numeric amounts as strings with commas
  - ANO-002: Dates in MM/DD/YYYY string format
  - ANO-003: Orphaned loan account references
  - ANO-004: Status/type code expansion
  - ANO-008: Payment component amounts not summing to total
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DecimalType, IntegerType
)
from functools import reduce
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/legacy-cdw/CDW_PMT_HIST"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
LOAN_TABLE = "loan_warehouse.loan_accounts"
DQ_LOG_TABLE = "loan_warehouse.data_quality_log"
RUN_ID = f"payment_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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

PAYMENT_TYPE_MAP = {
    "REG": "REGULAR", "EXT": "EXTRA", "PRT": "PARTIAL", "PRE": "PREPAYMENT"
}
PAYMENT_STATUS_MAP = {
    "PST": "POSTED", "REV": "REVERSED", "NSF": "NSF", "PND": "PENDING"
}


def read_source(spark: SparkSession) -> DataFrame:
    if SOURCE_FORMAT == "csv":
        return (
            spark.read.schema(LEGACY_SCHEMA)
            .option("header", "true").csv(SOURCE_PATH)
        )
    return spark.read.parquet(SOURCE_PATH)


def parse_legacy_date(col_name: str, alias: str) -> F.Column:
    return F.coalesce(
        F.to_date(F.col(col_name), "MM/dd/yyyy"),
        F.to_date(F.col(col_name), "yyyy-MM-dd"),
    ).alias(alias)


def parse_legacy_amount(col_name: str, alias: str) -> F.Column:
    cleaned = F.regexp_replace(F.col(col_name), r"[$,\s]", "")
    return cleaned.cast(DecimalType(10, 2)).alias(alias)


def expand_status(col_name: str, mapping: dict, alias: str) -> F.Column:
    mapping_expr = F.create_map(
        *[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    upper_col = F.upper(F.trim(F.col(col_name)))
    return F.coalesce(mapping_expr[upper_col], upper_col).alias(alias)


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    loans = spark.table(LOAN_TABLE).select(
        F.col("loan_account_id"), F.col("account_number").alias("ln_acct_nbr")
    )

    return (
        df
        .join(loans, df["LN_ACCT_NBR"] == loans["ln_acct_nbr"], "left")
        .select(
            F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),
            F.col("loan_account_id"),
            parse_legacy_date("PMT_DT", "payment_date"),
            parse_legacy_amount("PMT_AMT", "total_amount"),
            parse_legacy_amount("PMT_PRIN_AMT", "principal_amount"),
            parse_legacy_amount("PMT_INT_AMT", "interest_amount"),
            parse_legacy_amount("PMT_ESCROW_AMT", "escrow_amount"),
            parse_legacy_amount("PMT_LATE_FEE", "late_fee"),
            expand_status("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
            expand_status("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
            parse_legacy_date("PMT_RECV_DT", "received_date"),
            parse_legacy_date("PMT_PROC_DT", "processed_date"),
            F.coalesce(
                F.to_timestamp(F.col("PMT_CRET_DT"), "MM/dd/yyyy"),
                F.to_timestamp(F.col("PMT_CRET_DT"), "yyyy-MM-dd"),
                F.current_timestamp()
            ).alias("created_at"),
            F.coalesce(
                F.to_timestamp(F.col("PMT_UPDT_DT"), "MM/dd/yyyy"),
                F.to_timestamp(F.col("PMT_UPDT_DT"), "yyyy-MM-dd"),
                F.current_timestamp()
            ).alias("updated_at"),
            F.year(
                F.coalesce(
                    F.to_date(F.col("PMT_DT"), "MM/dd/yyyy"),
                    F.to_date(F.col("PMT_DT"), "yyyy-MM-dd"),
                )
            ).alias("payment_year"),
            F.current_timestamp().alias("_ingestion_ts"),
            F.lit("CDW").alias("_source_system"),
        )
    )


def detect_anomalies(source_df: DataFrame, spark: SparkSession) -> DataFrame:
    anomalies = []

    # ANO-003: Orphaned loan account references
    loan_accts = spark.table(LOAN_TABLE).select(
        F.col("account_number").alias("valid_ln_acct")
    )
    orphan_loans = (
        source_df
        .join(loan_accts, source_df["LN_ACCT_NBR"] == loan_accts["valid_ln_acct"], "left_anti")
        .filter(F.col("LN_ACCT_NBR").isNotNull())
        .select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_PMT_HIST").alias("source_table"),
            F.col("PMT_SEQ_NBR").alias("source_record_id"),
            F.lit("LN_ACCT_NBR").alias("column_name"),
            F.lit("FK_VIOLATION").alias("anomaly_type"),
            F.lit("CRITICAL").alias("severity"),
            F.concat(F.lit("Loan account "), F.col("LN_ACCT_NBR"),
                     F.lit(" not found in loan_accounts")).alias("description"),
            F.col("LN_ACCT_NBR").alias("original_value"),
            F.lit(None).cast(StringType()).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
    )
    anomalies.append(orphan_loans)

    # ANO-008: Payment components don't sum to total
    amt = lambda c: F.coalesce(
        F.regexp_replace(F.col(c), r"[$,\s]", "").cast(DecimalType(10, 2)),
        F.lit(0).cast(DecimalType(10, 2))
    )
    recon_df = source_df.withColumn(
        "component_sum",
        amt("PMT_PRIN_AMT") + amt("PMT_INT_AMT") + amt("PMT_ESCROW_AMT") + amt("PMT_LATE_FEE")
    ).withColumn(
        "total_parsed", amt("PMT_AMT")
    ).withColumn(
        "delta", F.abs(F.col("component_sum") - F.col("total_parsed"))
    )

    bad_recon = recon_df.filter(F.col("delta") > 0.02).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_PMT_HIST").alias("source_table"),
        F.col("PMT_SEQ_NBR").alias("source_record_id"),
        F.lit("PMT_AMT").alias("column_name"),
        F.lit("BUSINESS_RULE").alias("anomaly_type"),
        F.lit("MEDIUM").alias("severity"),
        F.concat(
            F.lit("Component sum="), F.col("component_sum"),
            F.lit(" vs total="), F.col("total_parsed"),
            F.lit(" delta="), F.round(F.col("delta"), 2)
        ).alias("description"),
        F.col("PMT_AMT").alias("original_value"),
        F.col("component_sum").cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(bad_recon)

    # ANO-006: Null required fields
    for col_name in ["PMT_SEQ_NBR", "LN_ACCT_NBR", "PMT_AMT", "PMT_STAT_CD"]:
        null_records = source_df.filter(
            F.col(col_name).isNull() | (F.trim(F.col(col_name)) == "")
        ).select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_PMT_HIST").alias("source_table"),
            F.coalesce(F.col("PMT_SEQ_NBR"), F.lit("UNKNOWN")).alias("source_record_id"),
            F.lit(col_name).alias("column_name"),
            F.lit("NULL_REQUIRED").alias("anomaly_type"),
            F.lit("CRITICAL").alias("severity"),
            F.lit(f"Required field {col_name} is null/blank").alias("description"),
            F.col(col_name).alias("original_value"),
            F.lit(None).cast(StringType()).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
        anomalies.append(null_records)

    return reduce(DataFrame.unionByName, anomalies)


def run(spark: SparkSession) -> dict:
    print(f"[{RUN_ID}] Starting payment ingestion...")
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"[{RUN_ID}] Source rows: {source_count}")

    anomaly_df = detect_anomalies(source_df, spark)
    anomaly_count = anomaly_df.count()
    print(f"[{RUN_ID}] Anomalies detected: {anomaly_count}")
    if anomaly_count > 0:
        anomaly_df.write.mode("append").saveAsTable(DQ_LOG_TABLE)

    transformed_df = transform(source_df, spark)
    transformed_df.createOrReplaceTempView("payments_staging")
    spark.sql(f"""
        MERGE INTO {TARGET_TABLE} AS target
        USING payments_staging AS source
        ON target.legacy_sequence_nbr = source.legacy_sequence_nbr
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[{RUN_ID}] Target rows: {target_count}")
    return {
        "run_id": RUN_ID,
        "source_count": source_count,
        "target_count": target_count,
        "anomaly_count": anomaly_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW Payment Ingestion").getOrCreate()
    result = run(spark)
    print(f"Ingestion complete: {result}")
