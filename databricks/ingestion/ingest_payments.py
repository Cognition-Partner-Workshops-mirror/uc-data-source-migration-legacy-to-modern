"""
Ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Key transformations:
- Resolves loan_account_id via lookup against loan_warehouse.loan_accounts
- Parses all date and amount strings
- Expands payment type codes (REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT)
- Expands payment status codes (PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING)
- Preserves legacy PMT_SEQ_NBR as legacy_payment_id for traceability

Prerequisites: loan_accounts table must be ingested first.

Usage:
    spark = SparkSession.builder.getOrCreate()
    ingest_payments(spark, source_path="dbfs:/mnt/legacy/CDW_PMT_HIST.csv")
"""

import logging

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from common_utils import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    map_status_column,
    quarantine_malformed,
    read_legacy_csv,
    read_legacy_parquet,
    register_udfs,
    write_delta,
)

logger = logging.getLogger("cdw_migration.payments")

TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_TABLE = "loan_warehouse._quarantine_payments"

REQUIRED_COLUMNS = [
    "loan_account_id", "payment_date", "total_amount", "type", "status",
]


def ingest_payments(spark: SparkSession, source_path: str,
                    source_format: str = "csv"):
    """
    End-to-end ingestion of CDW_PMT_HIST into loan_warehouse.payments.
    """
    udfs = register_udfs(spark)

    # ------------------------------------------------------------------
    # 1. Read source
    # ------------------------------------------------------------------
    if source_format == "parquet":
        raw_df = read_legacy_parquet(spark, source_path)
    else:
        raw_df = read_legacy_csv(spark, source_path)

    source_count = raw_df.count()
    logger.info("Source row count: %d", source_count)

    # ------------------------------------------------------------------
    # 2. Load lookup table for FK resolution
    # ------------------------------------------------------------------
    loan_accounts_df = (
        spark.table("loan_warehouse.loan_accounts")
        .select(
            F.col("loan_key").alias("_lk_loan_id"),
            F.col("account_number").alias("_lk_acct_nbr"),
        )
    )

    # ------------------------------------------------------------------
    # 3. Transform columns
    # ------------------------------------------------------------------
    transformed_df = (
        raw_df
        .withColumn("legacy_payment_id", F.trim(F.col("PMT_SEQ_NBR")))
        .withColumn("_acct_nbr_lookup", F.trim(F.col("LN_ACCT_NBR")))
        .withColumn("payment_date", udfs["parse_date"](F.col("PMT_DT")))
        .withColumn("total_amount", udfs["parse_amount_10_2"](F.col("PMT_AMT")))
        .withColumn("principal_amount", udfs["parse_amount_10_2"](F.col("PMT_PRIN_AMT")))
        .withColumn("interest_amount", udfs["parse_amount_10_2"](F.col("PMT_INT_AMT")))
        .withColumn("escrow_amount", udfs["parse_amount_10_2"](F.col("PMT_ESCROW_AMT")))
        .withColumn("late_fee", udfs["parse_amount_10_2"](F.col("PMT_LATE_FEE")))
        .withColumn("received_date", udfs["parse_date"](F.col("PMT_RECV_DT")))
        .withColumn("processed_date", udfs["parse_date"](F.col("PMT_PROC_DT")))
        .withColumn("created_at", udfs["parse_timestamp"](F.col("PMT_CRET_DT")))
        .withColumn("updated_at", udfs["parse_timestamp"](F.col("PMT_UPDT_DT")))
    )

    # Expand payment type codes: REG -> REGULAR, etc.
    transformed_df = map_status_column(
        transformed_df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP
    )

    # Expand payment status codes: PST -> POSTED, etc.
    transformed_df = map_status_column(
        transformed_df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP
    )

    # ------------------------------------------------------------------
    # 4. Resolve loan_account_id via join
    # ------------------------------------------------------------------
    joined_df = (
        transformed_df
        .join(loan_accounts_df,
              transformed_df["_acct_nbr_lookup"] == loan_accounts_df["_lk_acct_nbr"],
              "left")
        .withColumn("loan_account_id", F.col("_lk_loan_id"))
    )

    unresolved_loans = joined_df.filter(F.col("loan_account_id").isNull()).count()
    if unresolved_loans > 0:
        logger.warning("Unresolved loan_account_id for %d payments", unresolved_loans)

    # ------------------------------------------------------------------
    # 5. Select final columns
    # ------------------------------------------------------------------
    all_legacy_cols = [c for c in raw_df.columns]
    lookup_cols = ["_acct_nbr_lookup", "_lk_loan_id", "_lk_acct_nbr"]
    modern_df = joined_df.drop(*(all_legacy_cols + lookup_cols))

    # Add audit columns
    modern_df = (
        modern_df
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit("CDW_PMT_HIST"))
    )

    # ------------------------------------------------------------------
    # 6. Quarantine malformed rows
    # ------------------------------------------------------------------
    valid_df, quarantine_df = quarantine_malformed(
        modern_df, TARGET_TABLE, REQUIRED_COLUMNS
    )

    # ------------------------------------------------------------------
    # 7. Write to Delta Lake
    # ------------------------------------------------------------------
    # Compute partition columns before writing
    valid_df = (
        valid_df
        .withColumn("payment_year", F.year(F.col("payment_date")))
        .withColumn("payment_month", F.month(F.col("payment_date")))
    )
    write_delta(valid_df, TARGET_TABLE, mode="overwrite",
                partition_cols=["payment_year", "payment_month"])

    if quarantine_df.count() > 0:
        write_delta(quarantine_df, QUARANTINE_TABLE, mode="overwrite")

    # ------------------------------------------------------------------
    # 8. Post-write validation
    # ------------------------------------------------------------------
    target_count = spark.table(TARGET_TABLE).count()
    quarantine_count = quarantine_df.count()

    logger.info("Ingestion complete for %s", TARGET_TABLE)
    logger.info("  Source rows:      %d", source_count)
    logger.info("  Target rows:      %d", target_count)
    logger.info("  Quarantined rows: %d", quarantine_count)

    return {
        "source_count": source_count,
        "target_count": target_count,
        "quarantine_count": quarantine_count,
        "unresolved_loans": unresolved_loans,
        "reconciled": source_count == target_count + quarantine_count,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    spark = SparkSession.builder.appName("CDW_Payment_Ingestion").getOrCreate()

    path = sys.argv[1] if len(sys.argv) > 1 else "dbfs:/mnt/legacy/CDW_PMT_HIST.csv"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "csv"

    result = ingest_payments(spark, source_path=path, source_format=fmt)
    print(f"Ingestion result: {result}")
