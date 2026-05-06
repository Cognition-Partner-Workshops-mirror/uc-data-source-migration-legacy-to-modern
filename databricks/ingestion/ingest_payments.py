"""
Ingestion script: CDW_PMT_HIST -> loan_warehouse.payments

Reads legacy payment history data, applies transformations per column_mappings.md,
resolves FK reference to loan_accounts, and writes to the modern payments Delta table.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from .utils import (
    expand_status_code,
    parse_amount_col,
    parse_date_col,
    parse_timestamp_col,
    quarantine_bad_records,
    read_legacy_source,
)


def ingest_payments(spark: SparkSession, source_path: str,
                    file_format: str = "csv",
                    write_mode: str = "overwrite") -> dict:
    """Ingest payment data from legacy CDW_PMT_HIST source.

    Resolves loan_account_id FK by joining against the already-loaded
    loan_accounts table.

    Args:
        spark: Active SparkSession
        source_path: Path to CDW_PMT_HIST source file(s)
        file_format: Source format ('csv' or 'parquet')
        write_mode: Delta write mode ('overwrite' or 'append')

    Returns:
        dict with source_count, target_count, quarantined_count
    """
    print("[INFO] Starting payment ingestion from CDW_PMT_HIST")

    # Read source
    raw_df = read_legacy_source(spark, source_path, file_format)
    source_count = raw_df.count()
    print(f"[INFO] Source records read: {source_count}")

    # --- FK Resolution ---
    loans_lookup = spark.table("loan_warehouse.loan_accounts") \
        .select(F.col("id").alias("_loan_id"), F.col("account_number"))

    # --- Transformations ---

    df = raw_df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_payment_id"),
        F.col("LN_ACCT_NBR"),
        F.col("PMT_DT"),
        F.col("PMT_AMT"),
        F.col("PMT_PRIN_AMT"),
        F.col("PMT_INT_AMT"),
        F.col("PMT_ESCROW_AMT"),
        F.col("PMT_LATE_FEE"),
        F.col("PMT_TYP_CD"),
        F.col("PMT_STAT_CD"),
        F.col("PMT_RECV_DT"),
        F.col("PMT_PROC_DT"),
        F.col("PMT_CRET_DT"),
        F.col("PMT_UPDT_DT"),
    )

    # Resolve loan account FK
    df = df.join(loans_lookup, df["LN_ACCT_NBR"] == loans_lookup["account_number"], "left") \
           .withColumn("loan_account_id", F.col("_loan_id")) \
           .drop("_loan_id", "account_number") \
           .withColumn(
               "_err_loan_account_id",
               F.when(F.col("loan_account_id").isNull() & F.col("LN_ACCT_NBR").isNotNull(),
                      F.concat(F.lit("Loan account not found: "), F.col("LN_ACCT_NBR")))
           )

    # Parse amounts
    df = parse_amount_col(df, "PMT_AMT", "total_amount", precision=10)
    df = parse_amount_col(df, "PMT_PRIN_AMT", "principal_amount", precision=10)
    df = parse_amount_col(df, "PMT_INT_AMT", "interest_amount", precision=10)
    df = parse_amount_col(df, "PMT_ESCROW_AMT", "escrow_amount", precision=10)
    df = parse_amount_col(df, "PMT_LATE_FEE", "late_fee", precision=10)

    # Parse dates
    df = parse_date_col(df, "PMT_DT", "payment_date")
    df = parse_date_col(df, "PMT_RECV_DT", "received_date")
    df = parse_date_col(df, "PMT_PROC_DT", "processed_date")

    # Parse timestamps
    df = parse_timestamp_col(df, "PMT_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "PMT_UPDT_DT", "updated_at")

    # Expand status codes
    df = expand_status_code(df, "PMT_TYP_CD", "type", "payment_type")
    df = expand_status_code(df, "PMT_STAT_CD", "status", "payment_status")

    # Derive partition columns
    df = df.withColumn("payment_year", F.year(F.col("payment_date"))) \
           .withColumn("payment_month", F.month(F.col("payment_date")))

    # Drop intermediate source columns
    df = df.drop(
        "LN_ACCT_NBR", "PMT_AMT", "PMT_PRIN_AMT", "PMT_INT_AMT",
        "PMT_ESCROW_AMT", "PMT_LATE_FEE", "PMT_DT", "PMT_TYP_CD",
        "PMT_STAT_CD", "PMT_RECV_DT", "PMT_PROC_DT", "PMT_CRET_DT",
        "PMT_UPDT_DT"
    )

    # Add lineage columns
    df = df.withColumn("_migration_source", F.lit("CDW_PMT_HIST")) \
           .withColumn("_migrated_at", F.current_timestamp())

    # Quarantine bad records
    clean_df = quarantine_bad_records(df, "payments", spark)

    # Write to Delta
    target_count = clean_df.count()
    clean_df.write \
        .mode(write_mode) \
        .format("delta") \
        .partitionBy("payment_year", "payment_month") \
        .saveAsTable("loan_warehouse.payments")

    quarantined_count = source_count - target_count
    print(f"[INFO] Payment ingestion complete: {target_count} written, "
          f"{quarantined_count} quarantined")

    return {
        "table": "payments",
        "source_count": source_count,
        "target_count": target_count,
        "quarantined_count": quarantined_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder \
        .appName("LoanMigration_Payments") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .getOrCreate()

    import sys
    source = sys.argv[1] if len(sys.argv) > 1 else "/mnt/legacy-export/CDW_PMT_HIST/"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "csv"

    result = ingest_payments(spark, source, fmt)
    print(f"[RESULT] {result}")
