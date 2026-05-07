"""
Ingest legacy CDW_PMT_HIST into Delta Lake payments table.

Source : CSV/Parquet export of CDW_PMT_HIST
Target : loan_warehouse.payments (Delta Lake)

Key transformations:
  - Resolve LN_ACCT_NBR -> loan_key via lookup against loan_accounts table
  - Parse all amount strings -> DECIMAL
  - Parse date strings -> DATE / TIMESTAMP
  - Expand PMT_TYP_CD (REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT)
  - Expand PMT_STAT_CD (PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING)
  - Derive payment_year partition column from payment_date
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from .transforms import (
    parse_date,
    parse_timestamp,
    parse_amount,
    expand_status,
    add_ingestion_timestamp,
    log_malformed_rows,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

REQUIRED_COLS = ["legacy_sequence_nbr", "loan_key", "payment_date", "total_amount", "type", "status"]


def read_source(spark: SparkSession, source_path: str, source_format: str = "csv") -> DataFrame:
    reader = spark.read.format(source_format)
    if source_format == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(source_path)


def transform(df: DataFrame, loan_accounts_df: DataFrame) -> DataFrame:
    """
    Transform CDW_PMT_HIST and resolve the loan_key foreign key.

    Parameters:
        df               : Raw CDW_PMT_HIST DataFrame
        loan_accounts_df : The loan_accounts Delta table (must have account_number, loan_key)
    """
    loan_lookup = loan_accounts_df.select(
        F.col("account_number").alias("_acct_nbr"),
        F.col("loan_key"),
    )

    transformed = (
        df
        .select(
            F.trim(F.col("PMT_SEQ_NBR")).alias("legacy_sequence_nbr"),
            F.trim(F.col("LN_ACCT_NBR")).alias("_acct_nbr_lookup"),
            parse_date("PMT_DT").alias("payment_date"),
            parse_amount("PMT_AMT", 10, 2).alias("total_amount"),
            parse_amount("PMT_PRIN_AMT", 10, 2).alias("principal_amount"),
            parse_amount("PMT_INT_AMT", 10, 2).alias("interest_amount"),
            parse_amount("PMT_ESCROW_AMT", 10, 2).alias("escrow_amount"),
            parse_amount("PMT_LATE_FEE", 10, 2).alias("late_fee"),
            expand_status("PMT_TYP_CD", PAYMENT_TYPE_MAP).alias("type"),
            expand_status("PMT_STAT_CD", PAYMENT_STATUS_MAP).alias("status"),
            parse_date("PMT_RECV_DT").alias("received_date"),
            parse_date("PMT_PROC_DT").alias("processed_date"),
            parse_timestamp("PMT_CRET_DT").alias("created_at"),
            parse_timestamp("PMT_UPDT_DT").alias("updated_at"),
        )
    )

    # Resolve loan_key FK
    transformed = transformed.join(
        loan_lookup,
        transformed["_acct_nbr_lookup"] == loan_lookup["_acct_nbr"],
        "left",
    ).drop("_acct_nbr_lookup", "_acct_nbr")

    # Derive partition column
    transformed = transformed.withColumn(
        "payment_year", F.year(F.col("payment_date"))
    )

    return transformed


def run(
    spark: SparkSession,
    source_path: str,
    loan_accounts_table: str = "loan_warehouse.loan_accounts",
    target_table: str = "loan_warehouse.payments",
    error_path: str = "dbfs:/mnt/quarantine/payments/",
    source_format: str = "csv",
    write_mode: str = "append",
) -> dict:
    raw_df = read_source(spark, source_path, source_format)
    source_count = raw_df.count()
    print(f"[payments] Source rows read: {source_count}")

    loan_accounts_df = spark.table(loan_accounts_table)

    transformed_df = transform(raw_df, loan_accounts_df)
    transformed_df = add_ingestion_timestamp(transformed_df)

    unresolved_loan = transformed_df.filter(F.col("loan_key").isNull()).count()
    if unresolved_loan > 0:
        print(f"[payments] WARNING: {unresolved_loan} rows with unresolved loan_key")

    valid_df, quarantine_count = log_malformed_rows(
        transformed_df, REQUIRED_COLS, "CDW_PMT_HIST", error_path
    )
    print(f"[payments] Quarantined rows: {quarantine_count}")

    valid_count = valid_df.count()
    (
        valid_df
        .write
        .format("delta")
        .mode(write_mode)
        .partitionBy("payment_year")
        .option("mergeSchema", "true")
        .saveAsTable(target_table)
    )
    print(f"[payments] Rows written to {target_table}: {valid_count}")

    return {
        "table": target_table,
        "source_count": source_count,
        "valid_count": valid_count,
        "quarantine_count": quarantine_count,
        "unresolved_loan_keys": unresolved_loan,
    }
