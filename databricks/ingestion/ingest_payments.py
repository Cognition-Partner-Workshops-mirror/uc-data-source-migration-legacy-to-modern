"""
Ingest legacy CDW_PMT_HIST into the modern payments Delta Lake table.

Source : CSV or Parquet export of CDW_PMT_HIST
Target : loan_warehouse.payments (Delta)

Transformations applied (per column_mappings.md):
  - LN_ACCT_NBR resolved to loan_account_id via lookup against loan_accounts.account_number
  - PMT_SEQ_NBR preserved as legacy_sequence_nbr for audit reconciliation
  - Comma-formatted amount strings → DecimalType
  - Date strings (MM/DD/YYYY) → DateType / TimestampType
  - PMT_TYP_CD expanded: REG → REGULAR, EXT → EXTRA, PRT → PARTIAL, PRE → PREPAYMENT
  - PMT_STAT_CD expanded: PST → POSTED, REV → REVERSED, NSF → NSF, PND → PENDING
  - Null / malformed values are logged, never silently dropped
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    expand_code,
    parse_amount,
    parse_date,
    parse_timestamp,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy_exports/CDW_PMT_HIST"
LEGACY_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.payments"


def read_legacy_payments(spark: SparkSession, path: str = LEGACY_SOURCE_PATH,
                         fmt: str = LEGACY_SOURCE_FORMAT) -> DataFrame:
    """Read the legacy payment history source file."""
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(path)


def resolve_loan_account_ids(spark: SparkSession) -> DataFrame:
    """Load the loan account lookup table (account_number → id) from the
    already-ingested modern loan_accounts Delta table."""
    return spark.table("loan_warehouse.loan_accounts").select(
        F.col("id").alias("loan_account_id"),
        F.col("account_number").alias("_acct_number"),
    )


def transform_payments(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Apply all column mappings, FK resolution, and type conversions.

    Adds a _parse_errors column for per-row warnings.
    """
    # Step 1: Apply scalar transformations
    transformed = df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),
        F.col("LN_ACCT_NBR").alias("_acct_number"),          # temporary; for FK join
        parse_date(F.col("PMT_DT")).alias("payment_date"),
        parse_amount(F.col("PMT_AMT"), precision=10, scale=2).alias("total_amount"),
        parse_amount(F.col("PMT_PRIN_AMT"), precision=10, scale=2).alias("principal_amount"),
        parse_amount(F.col("PMT_INT_AMT"), precision=10, scale=2).alias("interest_amount"),
        parse_amount(F.col("PMT_ESCROW_AMT"), precision=10, scale=2).alias("escrow_amount"),
        parse_amount(F.col("PMT_LATE_FEE"), precision=10, scale=2).alias("late_fee"),
        expand_code(F.col("PMT_TYP_CD"), PAYMENT_TYPE_MAP).alias("type"),
        expand_code(F.col("PMT_STAT_CD"), PAYMENT_STATUS_MAP).alias("status"),
        parse_date(F.col("PMT_RECV_DT")).alias("received_date"),
        parse_date(F.col("PMT_PROC_DT")).alias("processed_date"),
        parse_timestamp(F.col("PMT_CRET_DT")).alias("created_at"),
        parse_timestamp(F.col("PMT_UPDT_DT")).alias("updated_at"),
    )

    # Step 2: Resolve loan_account_id FK via left join
    loan_lookup = resolve_loan_account_ids(spark)
    transformed = transformed.join(loan_lookup, on="_acct_number", how="left")

    # Step 3: Build per-row error log
    error_checks = F.array_remove(
        F.array(
            F.when(F.col("loan_account_id").isNull(),
                   F.concat(F.lit("LN_ACCT_NBR lookup failed for "), F.col("_acct_number"))),
            F.when(F.col("payment_date").isNull(), F.lit("PMT_DT failed date parse")),
            F.when(F.col("total_amount").isNull(), F.lit("PMT_AMT failed decimal parse")),
            F.when(F.col("type").isNull(), F.lit("PMT_TYP_CD is null")),
            F.when(F.col("status").isNull(), F.lit("PMT_STAT_CD is null")),
        ),
        None,
    )

    transformed = (
        transformed
        .withColumn("_parse_errors", error_checks)
        .drop("_acct_number")
    )

    return transformed


def log_errors(df: DataFrame, spark: SparkSession) -> None:
    """Print and persist rows that had parse warnings."""
    error_rows = df.filter(F.size("_parse_errors") > 0)
    error_count = error_rows.count()
    if error_count > 0:
        print(f"[WARN] {error_count} payment row(s) had parse warnings:")
        error_rows.select("legacy_sequence_nbr", "_parse_errors").show(truncate=False)
        error_rows.write.format("delta").mode("overwrite").saveAsTable(
            "loan_warehouse._payment_ingestion_errors"
        )
    else:
        print("[INFO] All payment rows parsed successfully — no warnings.")


def write_payments(df: DataFrame) -> None:
    """Write clean payment records to the target Delta table."""
    clean = df.drop("_parse_errors")
    clean.write.format("delta").mode("overwrite").saveAsTable(TARGET_TABLE)
    print(f"[INFO] Wrote {clean.count()} payment records to {TARGET_TABLE}.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    spark = SparkSession.builder.appName("Ingest_Payments").getOrCreate()

    print("[INFO] Reading legacy CDW_PMT_HIST …")
    raw = read_legacy_payments(spark)
    source_count = raw.count()
    print(f"[INFO] Source row count: {source_count}")

    print("[INFO] Transforming payment records …")
    transformed = transform_payments(raw, spark)

    log_errors(transformed, spark)
    write_payments(transformed)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[INFO] Target row count: {target_count}")
    if source_count != target_count:
        print(f"[ERROR] Row count mismatch! Source={source_count}, Target={target_count}")
    else:
        print("[INFO] Row count reconciliation passed.")


if __name__ == "__main__":
    main()
