"""
Payment ingestion script: CDW_PMT_HIST → loan_warehouse.payments

Reads the legacy payment history table and transforms it into the modern
payments Delta Lake table with proper types and FK references.

Transformations applied:
  - LN_ACCT_NBR → loan_account_id via loan_accounts.account_number lookup
  - PMT_AMT, PMT_PRIN_AMT, etc. (VARCHAR with commas) → DECIMAL(10,2)
  - PMT_TYP_CD (REG/EXT/PRT/PRE) → type (Regular/Extra/Partial/Prepayment)
  - PMT_STAT_CD (PST/REV/NSF/PND) → status (Posted/Reversed/NSF/Pending)
  - All dates (MM/DD/YYYY) → DATE or TIMESTAMP
  - payment_year derived from payment_date for partitioning
  - PMT_SEQ_NBR preserved as legacy_sequence_nbr for audit trail

Malformed rows are flagged and routed to quarantine, never silently dropped.
"""

import logging

from pyspark.sql import SparkSession, functions as F

from config import (
    SOURCE_PATHS,
    TARGET_TABLES,
    QUARANTINE_TABLE,
    PAYMENT_LEGACY_SCHEMA,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)
from transformations import (
    parse_date,
    parse_timestamp,
    parse_amount_10_2,
    expand_status_code,
    add_etl_metadata,
    tag_malformed_rows,
    log_malformed_summary,
    read_legacy_source,
)

logger = logging.getLogger("cdw_migration.ingest_payments")


def ingest_payments(spark: SparkSession, file_format: str = "csv") -> dict:
    """
    Main ingestion function for payments.

    Requires loan_accounts table to already be loaded (for FK lookup).

    Returns a dict with row counts for reconciliation:
      {"source_count": int, "target_count": int, "quarantine_count": int,
       "orphan_loan_count": int}
    """
    logger.info("Starting payment ingestion from CDW_PMT_HIST")

    # -------------------------------------------------------------------------
    # Step 1: Read legacy source data
    # -------------------------------------------------------------------------
    raw_df = read_legacy_source(
        spark, SOURCE_PATHS["payments"], PAYMENT_LEGACY_SCHEMA, file_format
    )
    source_count = raw_df.count()
    logger.info(f"Read {source_count} rows from CDW_PMT_HIST")

    # -------------------------------------------------------------------------
    # Step 2: Load loan_accounts for FK resolution
    # -------------------------------------------------------------------------
    loans_df = spark.table(TARGET_TABLES["loan_accounts"]).select(
        F.col("loan_account_id"), F.col("account_number")
    )

    # -------------------------------------------------------------------------
    # Step 3: Apply column-level transformations per column_mappings.md
    # -------------------------------------------------------------------------
    transformed_df = raw_df.select(
        # Legacy sequence number — preserved for audit trail
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),

        # Legacy loan account number — will be resolved to FK below
        F.col("LN_ACCT_NBR").alias("_legacy_account_number"),

        # Payment date — parse MM/DD/YYYY to DATE
        parse_date("PMT_DT", "payment_date"),

        # Payment amounts — remove commas, parse to DECIMAL(10,2)
        parse_amount_10_2("PMT_AMT", "total_amount"),
        parse_amount_10_2("PMT_PRIN_AMT", "principal_amount"),
        parse_amount_10_2("PMT_INT_AMT", "interest_amount"),
        parse_amount_10_2("PMT_ESCROW_AMT", "escrow_amount"),
        parse_amount_10_2("PMT_LATE_FEE", "late_fee"),

        # Payment type — expand abbreviation (REG→Regular, etc.)
        expand_status_code("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),

        # Payment status — expand abbreviation (PST→Posted, etc.)
        expand_status_code("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),

        # Processing dates — parse MM/DD/YYYY to DATE
        parse_date("PMT_RECV_DT", "received_date"),
        parse_date("PMT_PROC_DT", "processed_date"),

        # Audit timestamps — parse MM/DD/YYYY to TIMESTAMP
        parse_timestamp("PMT_CRET_DT", "created_at"),
        parse_timestamp("PMT_UPDT_DT", "updated_at"),
    )

    # -------------------------------------------------------------------------
    # Step 4: Resolve loan account FK (LN_ACCT_NBR → loan_account_id)
    # -------------------------------------------------------------------------
    with_loan_fk = transformed_df.join(
        loans_df,
        transformed_df["_legacy_account_number"] == loans_df["account_number"],
        "left",
    ).drop("account_number", "_legacy_account_number")

    orphan_loan_count = with_loan_fk.filter(F.col("loan_account_id").isNull()).count()
    if orphan_loan_count > 0:
        logger.warning(
            f"{orphan_loan_count} payments reference loan accounts "
            "not found in the loan_accounts table"
        )

    # -------------------------------------------------------------------------
    # Step 5: Derive partition column (payment_year from payment_date)
    # -------------------------------------------------------------------------
    with_partition = with_loan_fk.withColumn(
        "payment_year", F.year(F.col("payment_date"))
    )

    # -------------------------------------------------------------------------
    # Step 6: Flag malformed rows
    # -------------------------------------------------------------------------
    required_cols = ["loan_account_id", "payment_date", "total_amount", "type", "status"]
    with_flags = tag_malformed_rows(with_partition, required_cols)
    log_malformed_summary(with_flags, "payments")

    # -------------------------------------------------------------------------
    # Step 7: Separate clean vs. quarantine
    # -------------------------------------------------------------------------
    clean_df = with_flags.filter(~F.col("_is_malformed")).drop("_is_malformed")
    quarantine_df = with_flags.filter(F.col("_is_malformed")).drop("_is_malformed")

    clean_df = add_etl_metadata(clean_df, "CDW_PMT_HIST")

    # -------------------------------------------------------------------------
    # Step 8: Write clean records to Delta Lake
    # -------------------------------------------------------------------------
    clean_count = clean_df.count()
    logger.info(
        f"Writing {clean_count} clean payment records to "
        f"{TARGET_TABLES['payments']}"
    )

    clean_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).partitionBy("payment_year").saveAsTable(TARGET_TABLES["payments"])

    # -------------------------------------------------------------------------
    # Step 9: Write quarantine records (if any)
    # -------------------------------------------------------------------------
    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        logger.warning(f"Writing {quarantine_count} quarantined payment records")
        quarantine_with_meta = add_etl_metadata(quarantine_df, "CDW_PMT_HIST")
        quarantine_with_meta.withColumn(
            "_quarantine_reason", F.lit("Required field NULL after transformation")
        ).write.format("delta").mode("append").option(
            "mergeSchema", "true"
        ).saveAsTable(QUARANTINE_TABLE)

    result = {
        "source_count": source_count,
        "target_count": clean_count,
        "quarantine_count": quarantine_count,
        "orphan_loan_count": orphan_loan_count,
    }
    logger.info(f"Payment ingestion complete: {result}")
    return result


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Migration_Payments").getOrCreate()
    ingest_payments(spark)
    spark.stop()
