"""
Ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads the legacy payment history extract, applies column renaming, type
conversions, code expansions, resolves loan_account_key FK, and derives
the payment_year partition column. Writes to the Delta Lake payments table.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_codes,
    parse_amount_10_2,
    parse_legacy_date,
    parse_legacy_timestamp,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "/mnt/landing/cdw_pmt_hist/"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_PATH = "/mnt/quarantine/cdw_pmt_hist/"


def read_source(spark: SparkSession, path: str) -> DataFrame:
    """Read legacy payment history extract."""
    try:
        return spark.read.parquet(path)
    except Exception:
        return spark.read.option("header", "true").option("inferSchema", "false").csv(path)


def resolve_loan_account_key(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join to loan_accounts to resolve surrogate key from account_number."""
    try:
        loan_accounts = spark.table("loan_warehouse.loan_accounts").select(
            F.col("loan_account_key"), F.col("account_number")
        )
        df = (
            df.join(
                loan_accounts,
                df["_legacy_ln_acct_nbr"] == loan_accounts["account_number"],
                "left",
            )
            .drop("account_number")
        )
    except Exception as e:
        print(f"WARNING: Could not resolve loan_account FK: {e}")
        df = df.withColumn("loan_account_key", F.lit(None).cast("bigint"))

    return df


def transform_payments(
    spark: SparkSession, raw: DataFrame
) -> tuple[DataFrame, DataFrame]:
    """Apply column mappings, type conversions, FK resolution, and partition derivation."""
    transformed = raw.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),
        F.col("LN_ACCT_NBR").alias("_legacy_ln_acct_nbr"),
        parse_legacy_date("PMT_DT", "payment_date"),
        parse_amount_10_2("PMT_AMT", "total_amount"),
        parse_amount_10_2("PMT_PRIN_AMT", "principal_amount"),
        parse_amount_10_2("PMT_INT_AMT", "interest_amount"),
        parse_amount_10_2("PMT_ESCROW_AMT", "escrow_amount"),
        parse_amount_10_2("PMT_LATE_FEE", "late_fee"),
        expand_codes("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        expand_codes("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
        parse_legacy_date("PMT_RECV_DT", "received_date"),
        parse_legacy_date("PMT_PROC_DT", "processed_date"),
        parse_legacy_timestamp("PMT_CRET_DT", "created_at"),
        parse_legacy_timestamp("PMT_UPDT_DT", "updated_at"),
    )

    # Derive partition column
    transformed = transformed.withColumn(
        "payment_year", F.year(F.col("payment_date")).cast("int")
    )

    # Resolve loan_account FK
    transformed = resolve_loan_account_key(spark, transformed)

    # Critical field validation
    transformed = transformed.withColumn(
        "_has_error",
        (
            F.col("payment_date").isNull()
            | F.col("total_amount").isNull()
            | F.col("type").isNull()
            | F.col("status").isNull()
        ),
    )

    drop_cols = ["_has_error", "_legacy_ln_acct_nbr"]
    good_df = transformed.filter(~F.col("_has_error")).drop(*drop_cols)
    quarantine_df = transformed.filter(F.col("_has_error")).drop("_has_error")

    return good_df, quarantine_df


def write_target(good_df: DataFrame, quarantine_df: DataFrame) -> dict:
    """Write results to Delta Lake and quarantine bad records."""
    source_count = good_df.count() + quarantine_df.count()

    good_df = good_df.withColumn("_ingestion_ts", F.current_timestamp())

    good_df.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).partitionBy("payment_year").saveAsTable(TARGET_TABLE)

    target_count = good_df.count()
    quarantine_count = quarantine_df.count()

    if quarantine_count > 0:
        quarantine_df.write.format("delta").mode("append").save(QUARANTINE_PATH)
        print(
            f"WARNING: {quarantine_count} payment records quarantined to {QUARANTINE_PATH}"
        )

    return {
        "table": "payments",
        "source_count": source_count,
        "target_count": target_count,
        "quarantine_count": quarantine_count,
    }


def run(spark: SparkSession | None = None) -> dict:
    """Main entry point."""
    if spark is None:
        spark = SparkSession.builder.appName("IngestPayments").getOrCreate()

    print("--- Ingesting CDW_PMT_HIST -> payments ---")
    raw = read_source(spark, SOURCE_PATH)
    print(f"Source record count: {raw.count()}")

    good_df, quarantine_df = transform_payments(spark, raw)
    stats = write_target(good_df, quarantine_df)

    print(f"Target records written: {stats['target_count']}")
    print(f"Quarantined records:    {stats['quarantine_count']}")
    return stats


if __name__ == "__main__":
    run()
