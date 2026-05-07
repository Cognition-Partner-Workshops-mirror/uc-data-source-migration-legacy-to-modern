"""
Ingestion script for CDW_PMT_HIST -> loan_warehouse.payments

Reads legacy payment history data and applies transformations:
- Resolves loan_account_id FK by joining on LN_ACCT_NBR -> loan_accounts.account_number
- Parses all date and amount string fields
- Expands payment type codes (REG, EXT, PRT, PRE)
- Expands payment status codes (PST, REV, NSF, PND)
- Preserves legacy payment ID for audit trail
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructField,
    StructType,
    StringType,
)

from transformations import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    add_ingestion_metadata,
    expand_status_column,
    flag_parse_errors,
    log_rejected_records,
    parse_amount_column,
    parse_date_column,
    parse_timestamp_column,
)


LEGACY_PAYMENT_SCHEMA = StructType([
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


def read_legacy_payments(spark: SparkSession, source_path: str) -> DataFrame:
    """Read legacy payment history data from CSV or Parquet source."""
    if source_path.endswith(".parquet") or source_path.endswith("/parquet"):
        return spark.read.schema(LEGACY_PAYMENT_SCHEMA).parquet(source_path)

    return (
        spark.read
        .schema(LEGACY_PAYMENT_SCHEMA)
        .option("header", "true")
        .option("quote", '"')
        .option("escape", '"')
        .csv(source_path)
    )


def resolve_loan_account_fk(
    df: DataFrame,
    loan_accounts_df: DataFrame,
) -> DataFrame:
    """
    Resolve LN_ACCT_NBR to loan_accounts.id foreign key.

    Unresolved records are flagged but retained.
    """
    account_lookup = loan_accounts_df.select(
        F.col("id").alias("loan_account_id"),
        F.col("account_number"),
    )
    df = df.join(
        account_lookup,
        df["LN_ACCT_NBR"] == account_lookup["account_number"],
        "left",
    ).drop("account_number")

    df = df.withColumn(
        "_loan_fk_error",
        F.when(
            F.col("loan_account_id").isNull() & F.col("LN_ACCT_NBR").isNotNull(),
            F.lit(True),
        ).otherwise(F.lit(False)),
    )

    return df


def transform_payments(df: DataFrame) -> DataFrame:
    """
    Transform legacy payment data to modern schema.

    Transformations:
    1. Preserve legacy ID for audit trail
    2. Parse all amount fields from comma-formatted strings
    3. Parse all date fields from MM/DD/YYYY strings
    4. Expand payment type and status codes
    """
    transformed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_payment_id"),
        F.col("loan_account_id"),
        # Date fields
        parse_date_column("PMT_DT", "payment_date"),
        # Amount fields
        parse_amount_column("PMT_AMT", 10, 2, "total_amount"),
        parse_amount_column("PMT_PRIN_AMT", 10, 2, "principal_amount"),
        parse_amount_column("PMT_INT_AMT", 10, 2, "interest_amount"),
        parse_amount_column("PMT_ESCROW_AMT", 10, 2, "escrow_amount"),
        parse_amount_column("PMT_LATE_FEE", 10, 2, "late_fee"),
        # Code expansions
        expand_status_column("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        expand_status_column("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
        # More dates
        parse_date_column("PMT_RECV_DT", "received_date"),
        parse_date_column("PMT_PROC_DT", "processed_date"),
        parse_timestamp_column("PMT_CRET_DT", "created_at"),
        parse_timestamp_column("PMT_UPDT_DT", "updated_at"),
        # Error flags carried from FK resolution
        F.col("_loan_fk_error"),
        # Raw values for error detection
        F.col("PMT_DT").alias("_raw_pmt_dt"),
        F.col("PMT_AMT").alias("_raw_pmt_amt"),
    )

    transformed = flag_parse_errors(transformed, "_raw_pmt_dt", "payment_date", "_pmt_dt_error")
    transformed = flag_parse_errors(transformed, "_raw_pmt_amt", "total_amount", "_pmt_amt_error")

    return transformed


def write_payments(
    df: DataFrame,
    target_table: str,
    rejection_path: str,
    mode: str = "overwrite",
) -> dict:
    """Write transformed payment data to Delta Lake."""
    error_columns = ["_loan_fk_error", "_pmt_dt_error", "_pmt_amt_error"]
    total_count = df.count()
    rejected_count = log_rejected_records(df, error_columns, "payments", rejection_path)

    clean_df = df.drop(
        "_loan_fk_error", "_raw_pmt_dt", "_raw_pmt_amt",
        "_pmt_dt_error", "_pmt_amt_error",
    )
    clean_df = add_ingestion_metadata(clean_df, "CDW_PMT_HIST")

    clean_df.write.mode(mode).format("delta").saveAsTable(target_table)

    stats = {
        "table": target_table,
        "source_count": total_count,
        "loaded_count": total_count,
        "rejected_count": rejected_count,
        "rejection_rate": f"{(rejected_count / max(total_count, 1)) * 100:.2f}%",
    }
    print(f"[INFO] Payments ingestion complete: {stats}")
    return stats


def run(spark: SparkSession, config: dict) -> dict:
    """
    Main entry point for payment history ingestion.

    Requires loan_accounts table to already be loaded (for FK resolution).
    """
    source_path = config["source_path"]
    target_table = config.get("target_table", "loan_warehouse.payments")
    rejection_path = config.get("rejection_path", "/mnt/data/rejections")
    mode = config.get("mode", "overwrite")
    loan_accounts_table = config.get("loan_accounts_table", "loan_warehouse.loan_accounts")

    print(f"[INFO] Starting payments ingestion from: {source_path}")
    raw_df = read_legacy_payments(spark, source_path)
    print(f"[INFO] Read {raw_df.count()} records from source")

    # Load loan accounts for FK resolution
    loan_accounts_df = spark.read.table(loan_accounts_table)

    # Resolve FKs then transform
    fk_resolved_df = resolve_loan_account_fk(raw_df, loan_accounts_df)
    transformed_df = transform_payments(fk_resolved_df)

    return write_payments(transformed_df, target_table, rejection_path, mode)
