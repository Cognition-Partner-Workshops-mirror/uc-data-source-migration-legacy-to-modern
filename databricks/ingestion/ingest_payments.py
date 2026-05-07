"""
PySpark ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Key transformations:
- Resolve LN_ACCT_NBR -> loan_account_id via loan_accounts table lookup
- Parse all VARCHAR amounts and dates
- Expand payment type and status codes
- Extract payment_year partition key from payment_date
- Validate payment component integrity (principal + interest + escrow + late_fee vs total)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

try:
    from transforms import (
        parse_legacy_date,
        parse_legacy_timestamp,
        parse_legacy_amount,
        expand_status_code,
        flag_parse_failures,
        PAYMENT_TYPE_MAP,
        PAYMENT_STATUS_MAP,
    )
except ImportError:
    pass


LEGACY_SOURCE_PATH = "/mnt/legacy-cdw/CDW_PMT_HIST"
TARGET_TABLE = "loan_warehouse.payments"
SOURCE_FORMAT = "csv"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "quote": '"',
    "escape": '"',
}


def read_legacy_payments(spark: SparkSession) -> DataFrame:
    reader = spark.read.format(SOURCE_FORMAT)
    if SOURCE_FORMAT == "csv":
        for k, v in CSV_OPTIONS.items():
            reader = reader.option(k, v)
    return reader.load(LEGACY_SOURCE_PATH)


def transform_payments(raw: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Apply column mappings from CDW_PMT_HIST -> payments.
    Resolves loan_account_id via lookup join.
    Validates payment component integrity.
    """
    # -- FK lookup ----------------------------------------------------------
    accounts = spark.table("loan_warehouse.loan_accounts").select(
        F.col("loan_id").alias("loan_account_id"),
        F.col("account_number").alias("_acct_nbr"),
    )

    # -- Column transforms -------------------------------------------------
    transformed = (
        raw
        .withColumn("_acct_nbr", F.trim(F.col("LN_ACCT_NBR")))
        .withColumn("payment_date", parse_legacy_date("PMT_DT"))
        .withColumn("total_amount", parse_legacy_amount("PMT_AMT", precision=10, scale=2))
        .withColumn("principal_amount", parse_legacy_amount("PMT_PRIN_AMT", precision=10, scale=2))
        .withColumn("interest_amount", parse_legacy_amount("PMT_INT_AMT", precision=10, scale=2))
        .withColumn("escrow_amount", parse_legacy_amount("PMT_ESCROW_AMT", precision=10, scale=2))
        .withColumn("late_fee", parse_legacy_amount("PMT_LATE_FEE", precision=10, scale=2))
        .withColumn("type", expand_status_code("PMT_TYP_CD", PAYMENT_TYPE_MAP))
        .withColumn("status", expand_status_code("PMT_STAT_CD", PAYMENT_STATUS_MAP))
        .withColumn("received_date", parse_legacy_date("PMT_RECV_DT"))
        .withColumn("processed_date", parse_legacy_date("PMT_PROC_DT"))
        .withColumn("created_at", parse_legacy_timestamp("PMT_CRET_DT"))
        .withColumn("updated_at", parse_legacy_timestamp("PMT_UPDT_DT"))
        .withColumn("_legacy_pmt_seq", F.col("PMT_SEQ_NBR"))
    )

    # -- Derive partition key -----------------------------------------------
    transformed = transformed.withColumn(
        "payment_year", F.year(F.col("payment_date"))
    )

    # -- Join to resolve loan FK --------------------------------------------
    transformed = transformed.join(accounts, on="_acct_nbr", how="left")

    # -- Flag orphaned payments ---------------------------------------------
    transformed = transformed.withColumn(
        "_fk_warning",
        F.when(
            F.col("loan_account_id").isNull(),
            F.concat(F.col("_legacy_pmt_seq"), F.lit(": orphan — loan account '"),
                     F.col("_acct_nbr"), F.lit("' not found"))
        )
    )

    # -- Payment component integrity check ----------------------------------
    component_sum = (
        F.coalesce(F.col("principal_amount"), F.lit(0))
        + F.coalesce(F.col("interest_amount"), F.lit(0))
        + F.coalesce(F.col("escrow_amount"), F.lit(0))
        + F.coalesce(F.col("late_fee"), F.lit(0))
    )
    transformed = transformed.withColumn(
        "_integrity_warning",
        F.when(
            F.col("total_amount").isNotNull()
            & (F.abs(component_sum - F.col("total_amount")) > 0.01),
            F.concat(
                F.col("_legacy_pmt_seq"),
                F.lit(": component sum ("),
                F.format_number(component_sum, 2),
                F.lit(") != total ("),
                F.format_number(F.col("total_amount"), 2),
                F.lit("), delta = "),
                F.format_number(F.abs(component_sum - F.col("total_amount")), 2),
            )
        )
    )

    # Log warnings
    for wc in ["_fk_warning", "_integrity_warning"]:
        warnings = transformed.filter(F.col(wc).isNotNull()).select(wc).collect()
        for row in warnings:
            print(f"WARNING [{wc}]: {row[0]}")

    return transformed.select(
        "loan_account_id", "payment_date", "payment_year",
        "total_amount", "principal_amount", "interest_amount",
        "escrow_amount", "late_fee",
        "type", "status",
        "received_date", "processed_date",
        "created_at", "updated_at", "_legacy_pmt_seq",
    )


def write_payments(df: DataFrame, mode: str = "overwrite") -> None:
    (
        df.write
        .format("delta")
        .mode(mode)
        .partitionBy("payment_year")
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )


def run(spark: SparkSession = None) -> int:
    if spark is None:
        spark = SparkSession.builder.getOrCreate()

    print("=" * 70)
    print("INGESTION: CDW_PMT_HIST -> loan_warehouse.payments")
    print("=" * 70)

    raw = read_legacy_payments(spark)
    source_count = raw.count()
    print(f"Source rows read: {source_count}")

    transformed = transform_payments(raw, spark)
    target_count = transformed.count()
    print(f"Target rows to write: {target_count}")

    write_payments(transformed)
    print(f"SUCCESS: {target_count} rows written to {TARGET_TABLE}")

    return target_count


if __name__ == "__main__":
    run()
