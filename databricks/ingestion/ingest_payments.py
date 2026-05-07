"""Ingest legacy CDW_PMT_HIST into modern payments Delta table.

Key transformations:
- Resolve LN_ACCT_NBR → loan_account_id FK via loan_accounts table lookup
- Expand payment type and status codes
- Parse all date/amount string columns
"""

import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from common import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    drop_flag_columns,
    expand_status,
    log_parse_errors,
    parse_amount_col,
    parse_date_col,
    parse_timestamp_col,
)

logger = logging.getLogger("ingestion.payments")
logging.basicConfig(level=logging.INFO)

SOURCE_PATH = "dbfs:/mnt/landing/legacy/cdw_pmt_hist"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"
LOAN_ACCOUNT_TABLE = "loan_warehouse.loan_accounts"


def read_source(spark: SparkSession, path: str = SOURCE_PATH, fmt: str = SOURCE_FORMAT) -> DataFrame:
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(path)


def resolve_loan_account_fk(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Join to loan_accounts table to resolve LN_ACCT_NBR → loan_account_id."""
    accounts = spark.table(LOAN_ACCOUNT_TABLE).select(
        F.col("id").alias("loan_account_id"),
        F.col("account_number").alias("_acct_nbr"),
    )
    df = df.join(accounts, df["LN_ACCT_NBR"] == accounts["_acct_nbr"], "left")
    df = df.withColumn(
        "_flag_loan_account_id_unresolved",
        F.when(F.col("loan_account_id").isNull(), F.lit(True)).otherwise(F.lit(False)),
    )
    unresolved = df.filter(F.col("loan_account_id").isNull()).count()
    if unresolved > 0:
        logger.warning("%d payments have unresolved loan_account_id", unresolved)
    return df.drop("LN_ACCT_NBR", "_acct_nbr")


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Apply all column mappings and type conversions for payments."""

    # Preserve legacy ID for traceability
    df = df.withColumnRenamed("PMT_SEQ_NBR", "legacy_payment_id")

    # Resolve loan account FK
    df = resolve_loan_account_fk(df, spark)

    # Amount parsing
    df = parse_amount_col(df, "PMT_AMT", "total_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)

    # Date parsing
    df = parse_date_col(df, "PMT_DT", "payment_date")
    df = parse_date_col(df, "PMT_RECV_DT", "received_date")
    df = parse_date_col(df, "PMT_PROC_DT", "processed_date")

    # Timestamp parsing
    df = parse_timestamp_col(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "PMT_UPDT_DT", "updated_at")

    # Status/type expansion
    df = expand_status(df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)
    df = expand_status(df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # Drop replaced legacy columns
    legacy_cols_to_drop = [
        "PMT_AMT", "PMT_PRIN_AMT", "PMT_INT_AMT", "PMT_ESCROW_AMT", "PMT_LATE_FEE",
        "PMT_DT", "PMT_RECV_DT", "PMT_PROC_DT", "PMT_CRET_DT", "PMT_UPDT_DT",
        "PMT_TYP_CD", "PMT_STAT_CD",
    ]
    df = df.drop(*legacy_cols_to_drop)

    return df


def write_target(df: DataFrame, table: str = TARGET_TABLE) -> None:
    (
        df
        .write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(table)
    )


def run(spark: SparkSession) -> int:
    """Execute the payment ingestion pipeline. Returns source row count."""
    logger.info("Reading legacy payment data from %s", SOURCE_PATH)
    raw_df = read_source(spark)
    source_count = raw_df.count()
    logger.info("Source row count: %d", source_count)

    logger.info("Applying transformations (includes FK resolution)")
    transformed_df = transform(raw_df, spark)

    log_parse_errors(transformed_df, "payments", logger)
    clean_df = drop_flag_columns(transformed_df)

    logger.info("Writing to %s", TARGET_TABLE)
    write_target(clean_df)

    target_count = spark.table(TARGET_TABLE).count()
    logger.info("Target row count: %d", target_count)

    if source_count != target_count:
        logger.error(
            "Row count mismatch! source=%d target=%d", source_count, target_count
        )

    return source_count


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest_Payments").getOrCreate()
    run(spark)
