"""
PySpark ingestion script: CDW_PMT_HIST → loan_warehouse.payments

Reads legacy payment history data, resolves loan account FK references,
applies type conversions and status expansion, validates payment component
sums, and writes to a Delta Lake table.

Mapping reference: data/mappings/column_mappings.md § CDW_PMT_HIST → payments
Known data anomaly: payment component sums may not equal total amount
(see docs/DATA_ANOMALY_REPORT.md Anomaly #1).

Usage:
    spark-submit ingest_payments.py --source /mnt/landing/cdw_pmt_hist/ --format csv
"""

import argparse
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType
from transformations import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount_10_2,
    expand_status_code,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

TARGET_TABLE = "loan_warehouse.payments"


def read_source(spark: SparkSession, source_path: str, fmt: str) -> DataFrame:
    """Read legacy CDW_PMT_HIST data from CSV or Parquet."""
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(source_path)
    elif fmt == "parquet":
        return reader.parquet(source_path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def resolve_loan_account_ids(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Resolve legacy LN_ACCT_NBR strings to modern loan_accounts.id via account_number lookup.
    Records with unresolvable loan references are flagged but not dropped.
    """
    loan_accounts = spark.table("loan_warehouse.loan_accounts").select(
        F.col("id").alias("_loan_account_id"),
        F.col("account_number").alias("_acct_nbr"),
    )
    joined = df.join(
        loan_accounts,
        df["LN_ACCT_NBR"] == loan_accounts["_acct_nbr"],
        "left",
    )
    orphaned_count = joined.filter(F.col("_loan_account_id").isNull()).count()
    if orphaned_count > 0:
        print(
            f"WARNING: {orphaned_count} payment records have LN_ACCT_NBR that does not "
            f"match any loan account. These are orphaned records (see Anomaly #7)."
        )
    return joined


def validate_payment_components(df: DataFrame) -> DataFrame:
    """
    Validate that payment component amounts sum to the total amount.
    Adds a _sum_mismatch flag column for records where discrepancy exceeds $0.01.
    Catches Anomaly #1 (payment component sum mismatch) from DATA_ANOMALY_REPORT.
    """
    # Parse amounts into temp columns for validation
    df = df.withColumn(
        "_parsed_total",
        F.regexp_replace(F.trim(F.col("PMT_AMT")), r"[$%,\s]", "").cast(DecimalType(10, 2)),
    )
    df = df.withColumn(
        "_parsed_principal",
        F.regexp_replace(F.trim(F.col("PMT_PRIN_AMT")), r"[$%,\s]", "").cast(DecimalType(10, 2)),
    )
    df = df.withColumn(
        "_parsed_interest",
        F.regexp_replace(F.trim(F.col("PMT_INT_AMT")), r"[$%,\s]", "").cast(DecimalType(10, 2)),
    )
    df = df.withColumn(
        "_parsed_escrow",
        F.regexp_replace(F.trim(F.col("PMT_ESCROW_AMT")), r"[$%,\s]", "").cast(DecimalType(10, 2)),
    )
    df = df.withColumn(
        "_parsed_late_fee",
        F.regexp_replace(F.trim(F.col("PMT_LATE_FEE")), r"[$%,\s]", "").cast(DecimalType(10, 2)),
    )

    # Compute component sum and discrepancy
    df = df.withColumn(
        "_component_sum",
        F.coalesce(F.col("_parsed_principal"), F.lit(0).cast(DecimalType(10, 2)))
        + F.coalesce(F.col("_parsed_interest"), F.lit(0).cast(DecimalType(10, 2)))
        + F.coalesce(F.col("_parsed_escrow"), F.lit(0).cast(DecimalType(10, 2)))
        + F.coalesce(F.col("_parsed_late_fee"), F.lit(0).cast(DecimalType(10, 2))),
    )
    df = df.withColumn(
        "_sum_mismatch",
        F.abs(F.col("_parsed_total") - F.col("_component_sum")) > 0.01,
    )

    # Log mismatched records
    mismatch_count = df.filter(F.col("_sum_mismatch")).count()
    if mismatch_count > 0:
        print(
            f"DATA_ANOMALY: {mismatch_count} payment records have component sum mismatch. "
            f"Details:"
        )
        df.filter(F.col("_sum_mismatch")).select(
            "PMT_SEQ_NBR", "_parsed_total", "_component_sum",
            "_parsed_principal", "_parsed_interest", "_parsed_escrow", "_parsed_late_fee",
        ).show(truncate=False)

    return df


def transform_payments(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Apply all transformations from legacy CDW_PMT_HIST to modern payments schema.
    Resolves loan account FK and validates payment component integrity.
    """
    # Tag records missing required fields
    df = df.withColumn(
        "_has_required_fields",
        F.col("PMT_SEQ_NBR").isNotNull()
        & F.col("LN_ACCT_NBR").isNotNull()
        & F.col("PMT_AMT").isNotNull(),
    )

    quarantine_df = df.filter(~F.col("_has_required_fields"))
    if quarantine_df.count() > 0:
        print(
            f"WARNING: {quarantine_df.count()} payment records missing required fields. "
            f"Writing to quarantine."
        )
        quarantine_df.show(truncate=False)

    valid_df = df.filter(F.col("_has_required_fields"))

    # Validate payment component sums (Anomaly #1)
    valid_df = validate_payment_components(valid_df)

    # Resolve FK references
    valid_df = resolve_loan_account_ids(spark, valid_df)

    # Apply column transformations
    result = valid_df.select(
        F.col("PMT_SEQ_NBR").alias("legacy_sequence_nbr"),
        F.col("_loan_account_id").alias("loan_account_id"),
        # Date parsing
        parse_legacy_date("PMT_DT", "payment_date"),
        # Amount parsing
        parse_legacy_amount_10_2("PMT_AMT", "total_amount"),
        parse_legacy_amount_10_2("PMT_PRIN_AMT", "principal_amount"),
        parse_legacy_amount_10_2("PMT_INT_AMT", "interest_amount"),
        parse_legacy_amount_10_2("PMT_ESCROW_AMT", "escrow_amount"),
        parse_legacy_amount_10_2("PMT_LATE_FEE", "late_fee"),
        # Status/type expansion
        expand_status_code("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type"),
        expand_status_code("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status"),
        # Additional date fields
        parse_legacy_date("PMT_RECV_DT", "received_date"),
        parse_legacy_date("PMT_PROC_DT", "processed_date"),
        parse_legacy_timestamp("PMT_CRET_DT", "created_at"),
        parse_legacy_timestamp("PMT_UPDT_DT", "updated_at"),
        # Audit columns
        F.current_timestamp().alias("_ingestion_ts"),
        F.lit("CDW_PMT_HIST").alias("_source_system"),
    )

    return result


def write_to_delta(df: DataFrame, mode: str = "overwrite"):
    """Write transformed payments to Delta table, partitioned by status."""
    df.write.format("delta").mode(mode).partitionBy("status").saveAsTable(TARGET_TABLE)
    print(f"Successfully wrote {df.count()} records to {TARGET_TABLE}")


def main():
    parser = argparse.ArgumentParser(description="Ingest CDW_PMT_HIST → payments")
    parser.add_argument("--source", required=True, help="Path to source data files")
    parser.add_argument(
        "--format", default="csv", choices=["csv", "parquet"], help="Source file format"
    )
    parser.add_argument(
        "--mode", default="overwrite", choices=["overwrite", "append"], help="Write mode"
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_PMT_HIST_Ingestion").getOrCreate()

    print(f"Reading source data from {args.source} (format={args.format})")
    source_df = read_source(spark, args.source, args.format)
    source_count = source_df.count()
    print(f"Source record count: {source_count}")

    print("Applying transformations (including FK resolution and payment validation)...")
    transformed_df = transform_payments(spark, source_df)
    target_count = transformed_df.count()
    print(f"Transformed record count: {target_count}")

    if source_count != target_count:
        print(
            f"WARNING: Row count mismatch — source={source_count}, target={target_count}."
        )

    print(f"Writing to Delta table {TARGET_TABLE} (mode={args.mode})")
    write_to_delta(transformed_df, args.mode)

    spark.stop()


if __name__ == "__main__":
    main()
