"""
Ingest legacy CDW_PMT_HIST data into modern Delta Lake payments table.

Key transformations:
  - Resolves loan_account_id FK via LN_ACCT_NBR -> loan_accounts.account_number
  - Expands payment type codes (REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT)
  - Expands payment status codes (PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING)
  - Derives payment_year and payment_month partition columns from PMT_DT

Source: CSV/Parquet export of CDW_PMT_HIST
Target: loan_warehouse.payments (Delta Lake)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transformations import (
    parse_date_col,
    parse_timestamp_col,
    parse_amount_col,
    expand_status_col,
    flag_parse_failures,
    quarantine_bad_records,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy-exports/CDW_PMT_HIST/"
LEGACY_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_migration.loan_warehouse.payments"
LOAN_TABLE = "loan_migration.loan_warehouse.loan_accounts"
QUARANTINE_PATH = "dbfs:/mnt/migration-quarantine/payments/"

CSV_OPTIONS = {
    "header": "true",
    "inferSchema": "false",
    "nullValue": "",
    "emptyValue": "",
}


def read_legacy_payments(spark: SparkSession) -> DataFrame:
    """Read legacy payment history data."""
    reader = spark.read.format(LEGACY_SOURCE_FORMAT)
    if LEGACY_SOURCE_FORMAT == "csv":
        reader = reader.options(**CSV_OPTIONS)
    return reader.load(LEGACY_SOURCE_PATH)


def resolve_loan_fk(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join with loan_accounts to resolve LN_ACCT_NBR -> loan_account_id FK."""
    loans = (
        spark.table(LOAN_TABLE)
        .select(
            F.col("loan_account_id").alias("_resolved_loan_id"),
            F.col("account_number").alias("_ln_acct_nbr"),
        )
    )
    df = df.join(
        loans,
        df["LN_ACCT_NBR"] == loans["_ln_acct_nbr"],
        "left"
    )
    df = df.withColumn("loan_account_id", F.col("_resolved_loan_id"))
    df = df.withColumn(
        "_bad_loan_fk",
        F.when(
            F.col("LN_ACCT_NBR").isNotNull() & F.col("loan_account_id").isNull(),
            F.lit(True)
        ).otherwise(F.lit(False))
    )
    return df.drop("_resolved_loan_id", "_ln_acct_nbr")


def transform_payments(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Apply all transformations from legacy CDW_PMT_HIST to modern payments."""

    # --- Date columns ---
    df = parse_date_col(df, "PMT_DT", "payment_date")
    df = parse_date_col(df, "PMT_RECV_DT", "received_date")
    df = parse_date_col(df, "PMT_PROC_DT", "processed_date")
    df = parse_timestamp_col(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "PMT_UPDT_DT", "updated_at")

    # --- Amount columns ---
    df = parse_amount_col(df, "PMT_AMT", "total_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_PRIN_AMT", "principal_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_INT_AMT", "interest_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_ESCROW_AMT", "escrow_amount", precision=10, scale=2)
    df = parse_amount_col(df, "PMT_LATE_FEE", "late_fee", precision=10, scale=2)

    # --- Status expansion ---
    df = expand_status_col(df, "PMT_TYP_CD", "type", PAYMENT_TYPE_MAP)
    df = expand_status_col(df, "PMT_STAT_CD", "status", PAYMENT_STATUS_MAP)

    # --- Derived partition columns ---
    df = df.withColumn("payment_year", F.year(F.col("payment_date")))
    df = df.withColumn("payment_month", F.month(F.col("payment_date")))

    # --- FK resolution ---
    df = resolve_loan_fk(spark, df)

    # --- Preserve legacy sequence ID ---
    df = df.withColumn("legacy_sequence_id", F.col("PMT_SEQ_NBR"))

    # --- Parse failure flags ---
    df = flag_parse_failures(df, "PMT_DT", "payment_date", "_bad_pmt_dt")
    df = flag_parse_failures(df, "PMT_AMT", "total_amount", "_bad_pmt_amt")

    # --- Lineage ---
    df = (
        df
        .withColumn("_migration_source", F.lit("CDW_PMT_HIST"))
        .withColumn("_migrated_at", F.current_timestamp())
    )

    return df


def run_payment_ingestion(spark: SparkSession) -> dict:
    """Execute payment history ingestion pipeline."""
    print("=" * 60)
    print("PAYMENT INGESTION: CDW_PMT_HIST -> payments")
    print("=" * 60)

    raw_df = read_legacy_payments(spark)
    source_count = raw_df.count()
    print(f"Source records read: {source_count}")

    transformed_df = transform_payments(spark, raw_df)

    quarantine_flags = ["_bad_pmt_dt", "_bad_pmt_amt", "_bad_loan_fk"]
    good_df, bad_df = quarantine_bad_records(transformed_df, quarantine_flags)
    bad_count = bad_df.count()
    if bad_count > 0:
        print(f"WARNING: {bad_count} records quarantined")
        bad_df.write.mode("overwrite").format("delta").save(QUARANTINE_PATH)
    else:
        print("No records quarantined")

    final_columns = [
        "legacy_sequence_id", "loan_account_id",
        "payment_date", "total_amount", "principal_amount",
        "interest_amount", "escrow_amount", "late_fee",
        "type", "status", "received_date", "processed_date",
        "payment_year", "payment_month",
        "created_at", "updated_at", "_migration_source", "_migrated_at",
    ]
    output_df = good_df.select(*final_columns)

    (
        output_df
        .write
        .format("delta")
        .mode("overwrite")
        .partitionBy("payment_year", "payment_month")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )

    target_count = spark.table(TARGET_TABLE).count()
    print(f"Target records written: {target_count}")
    print("Payment ingestion complete.")

    return {
        "source_count": source_count,
        "target_count": target_count,
        "quarantined_count": bad_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("LoanMigration_Payments").getOrCreate()
    stats = run_payment_ingestion(spark)
    print(f"\nFinal stats: {stats}")
