"""
PySpark ingestion script: CDW_PMT_HIST → loan_warehouse.payments

Reads from a legacy CSV/Parquet extract of the CDW_PMT_HIST table and transforms
all VARCHAR columns into proper Spark SQL types. Key operations:
  - Resolves LN_ACCT_NBR → loan_accounts.id via lookup on loan_accounts.account_number
  - Expands payment type codes: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
  - Expands payment status codes: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
  - Parses all date strings and comma-formatted amounts
  - Derives payment_year partition column from payment_date

Usage (Databricks notebook cell):
    %run ./transform_utils
    %run ./ingest_payments

Or as a standalone script:
    spark-submit --master local[*] ingest_payments.py \
        --source-path /mnt/landing/cdw_pmt_hist/ \
        --source-format csv \
        --target-table loan_warehouse.payments
"""

import argparse
import logging
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transform_utils import (
    parse_date_mmddyyyy,
    parse_timestamp_mmddyyyy,
    parse_decimal_amount,
    expand_status_code,
    tag_malformed_rows,
    log_unmapped_codes,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

logger = logging.getLogger("cdw_migration.payments")
logger.setLevel(logging.INFO)


def read_legacy_payments(spark: SparkSession, source_path: str,
                         source_format: str = "csv") -> DataFrame:
    """
    Read the legacy CDW_PMT_HIST extract from the landing zone.
    """
    if source_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "")
            .csv(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from legacy CDW_PMT_HIST at %s", df.count(), source_path)
    return df


def resolve_loan_account_fk(df: DataFrame, spark: SparkSession,
                            accounts_table: str = "loan_warehouse.loan_accounts") -> DataFrame:
    """
    Resolve legacy LN_ACCT_NBR to modern loan_accounts.id via lookup on
    loan_accounts.account_number. Unresolvable FKs are flagged, not dropped.
    """
    accounts_lookup = spark.table(accounts_table).select(
        F.col("id").alias("_resolved_loan_account_id"),
        F.col("account_number").alias("_acct_lookup_key"),
    )

    df = df.join(
        accounts_lookup,
        df["LN_ACCT_NBR"] == accounts_lookup["_acct_lookup_key"],
        "left"
    )

    # Flag unresolved FKs for quality reporting
    df = df.withColumn(
        "_unresolved_loan_account",
        F.when(F.col("_resolved_loan_account_id").isNull(), F.lit(True)).otherwise(F.lit(False))
    )

    unresolved = df.filter(F.col("_unresolved_loan_account")).count()
    if unresolved > 0:
        logger.warning("Found %d payments with unresolvable LN_ACCT_NBR", unresolved)

    return df


def transform_payments(df: DataFrame, spark: SparkSession) -> DataFrame:
    """
    Transform legacy CDW_PMT_HIST columns to the modern payments schema.

    Transformations applied:
      - LN_ACCT_NBR: resolved to loan_account_id via FK lookup
      - PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE:
        comma-formatted string → DECIMAL
      - PMT_TYP_CD: expanded to full type name
      - PMT_STAT_CD: expanded to full status name
      - All date fields: MM/DD/YYYY → DateType or TimestampType
      - payment_year: derived from payment_date for partitioning
    """
    # Resolve FK first
    df = resolve_loan_account_fk(df, spark)

    transformed = (
        df
        # Preserve legacy payment ID for audit trail
        .withColumn("legacy_payment_id", F.col("PMT_SEQ_NBR"))

        # Resolved FK
        .withColumn("loan_account_id", F.col("_resolved_loan_account_id"))

        # Financial fields
        .withColumn("total_amount", parse_decimal_amount("PMT_AMT", 10, 2))
        .withColumn("principal_amount", parse_decimal_amount("PMT_PRIN_AMT", 10, 2))
        .withColumn("interest_amount", parse_decimal_amount("PMT_INT_AMT", 10, 2))
        .withColumn("escrow_amount", parse_decimal_amount("PMT_ESCROW_AMT", 10, 2))
        .withColumn("late_fee", parse_decimal_amount("PMT_LATE_FEE", 10, 2))

        # Status/type code expansion
        .withColumn("type", expand_status_code("PMT_TYP_CD", PAYMENT_TYPE_MAP))
        .withColumn("status", expand_status_code("PMT_STAT_CD", PAYMENT_STATUS_MAP))

        # Date fields
        .withColumn("payment_date", parse_date_mmddyyyy("PMT_DT"))
        .withColumn("received_date", parse_date_mmddyyyy("PMT_RECV_DT"))
        .withColumn("processed_date", parse_date_mmddyyyy("PMT_PROC_DT"))
        .withColumn("created_at", parse_timestamp_mmddyyyy("PMT_CRET_DT"))
        .withColumn("updated_at", parse_timestamp_mmddyyyy("PMT_UPDT_DT"))

        # Derived partition column
        .withColumn("payment_year", F.year(parse_date_mmddyyyy("PMT_DT")))
    )

    # Log unmapped codes
    log_unmapped_codes(transformed, "PMT_TYP_CD", "type", "CDW_PMT_HIST")
    log_unmapped_codes(transformed, "PMT_STAT_CD", "status", "CDW_PMT_HIST")

    modern_columns = [
        "legacy_payment_id", "loan_account_id", "payment_date",
        "total_amount", "principal_amount", "interest_amount",
        "escrow_amount", "late_fee",
        "type", "status",
        "received_date", "processed_date",
        "created_at", "updated_at",
        "payment_year",
    ]
    return transformed.select(modern_columns)


def write_payments(df: DataFrame, target_table: str = "loan_warehouse.payments") -> None:
    """
    Write transformed payment data to the Delta Lake target table.
    Uses merge (upsert) on legacy_payment_id for idempotent reruns.
    The payment_year partition column is derived during transformation.
    """
    row_count = df.count()
    logger.info("Writing %d payment records to %s", row_count, target_table)

    df.createOrReplaceTempView("payments_staging")

    spark = df.sparkSession
    spark.sql(f"""
        MERGE INTO {target_table} AS target
        USING payments_staging AS source
        ON target.legacy_payment_id = source.legacy_payment_id
        WHEN MATCHED THEN UPDATE SET
            loan_account_id  = source.loan_account_id,
            payment_date     = source.payment_date,
            total_amount     = source.total_amount,
            principal_amount = source.principal_amount,
            interest_amount  = source.interest_amount,
            escrow_amount    = source.escrow_amount,
            late_fee         = source.late_fee,
            type             = source.type,
            status           = source.status,
            received_date    = source.received_date,
            processed_date   = source.processed_date,
            created_at       = source.created_at,
            updated_at       = source.updated_at,
            payment_year     = source.payment_year,
            _migration_ts    = current_timestamp()
        WHEN NOT MATCHED THEN INSERT (
            legacy_payment_id, loan_account_id, payment_date,
            total_amount, principal_amount, interest_amount,
            escrow_amount, late_fee,
            type, status,
            received_date, processed_date,
            created_at, updated_at,
            payment_year
        ) VALUES (
            source.legacy_payment_id, source.loan_account_id, source.payment_date,
            source.total_amount, source.principal_amount, source.interest_amount,
            source.escrow_amount, source.late_fee,
            source.type, source.status,
            source.received_date, source.processed_date,
            source.created_at, source.updated_at,
            source.payment_year
        )
    """)
    logger.info("Payment ingestion complete: %d records processed", row_count)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest CDW_PMT_HIST to loan_warehouse.payments"
    )
    parser.add_argument("--source-path", required=True, help="Path to legacy CSV/Parquet extract")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--target-table", default="loan_warehouse.payments")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_Payment_Ingestion").getOrCreate()

    raw_df = read_legacy_payments(spark, args.source_path, args.source_format)
    transformed_df = transform_payments(raw_df, spark)
    write_payments(transformed_df, args.target_table)

    spark.stop()
