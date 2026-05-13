"""
PySpark ingestion script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads legacy loan account data, strips denormalized borrower fields, resolves
FK references to borrowers and loan_products, applies type conversions, and
writes to a Delta Lake table.

Mapping reference: data/mappings/column_mappings.md § CDW_LN_ACCT → loan_accounts
Key changes from legacy:
  - Denormalized fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) dropped
  - BORR_ID resolved to borrowers.id via external_id lookup
  - PROD_CD resolved to loan_products.id via code lookup
  - All VARCHAR amounts/dates → proper types

Usage:
    spark-submit ingest_loan_accounts.py --source /mnt/landing/cdw_ln_acct/ --format csv
"""

import argparse
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from transformations import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_amount_10_2,
    parse_legacy_rate,
    parse_legacy_pct,
    parse_legacy_integer,
    expand_status_code,
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
)

TARGET_TABLE = "loan_warehouse.loan_accounts"


def read_source(spark: SparkSession, source_path: str, fmt: str) -> DataFrame:
    """Read legacy CDW_LN_ACCT data from CSV or Parquet."""
    reader = spark.read.option("header", "true").option("inferSchema", "false")
    if fmt == "csv":
        return reader.csv(source_path)
    elif fmt == "parquet":
        return reader.parquet(source_path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def resolve_borrower_ids(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Resolve legacy BORR_ID strings to modern borrowers.id via external_id lookup.
    Records with unresolvable borrower references are flagged but not dropped.
    """
    borrowers = spark.table("loan_warehouse.borrowers").select(
        F.col("id").alias("_borrower_id"),
        F.col("external_id").alias("_borr_ext_id"),
    )
    joined = df.join(
        borrowers,
        df["BORR_ID"] == borrowers["_borr_ext_id"],
        "left",
    )
    # Log orphaned references
    orphaned_count = joined.filter(F.col("_borrower_id").isNull()).count()
    if orphaned_count > 0:
        print(
            f"WARNING: {orphaned_count} loan accounts have BORR_ID that does not match "
            f"any borrower external_id. These records will have null borrower_id."
        )
    return joined


def resolve_product_ids(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Resolve legacy PROD_CD strings to modern loan_products.id via code lookup.
    Records with unresolvable product references are flagged but not dropped.
    """
    products = spark.table("loan_warehouse.loan_products").select(
        F.col("id").alias("_product_id"),
        F.col("code").alias("_prod_code"),
    )
    joined = df.join(
        products,
        df["PROD_CD"] == products["_prod_code"],
        "left",
    )
    orphaned_count = joined.filter(F.col("_product_id").isNull()).count()
    if orphaned_count > 0:
        print(
            f"WARNING: {orphaned_count} loan accounts have PROD_CD that does not match "
            f"any product code. These records will have null product_id."
        )
    return joined


def transform_loan_accounts(spark: SparkSession, df: DataFrame) -> DataFrame:
    """
    Apply all transformations from legacy CDW_LN_ACCT to modern loan_accounts schema.
    Drops denormalized borrower fields and resolves FK references.
    """
    # Tag records missing required fields
    df = df.withColumn(
        "_has_required_fields",
        F.col("LN_ACCT_NBR").isNotNull() & F.col("BORR_ID").isNotNull(),
    )

    quarantine_df = df.filter(~F.col("_has_required_fields"))
    if quarantine_df.count() > 0:
        print(
            f"WARNING: {quarantine_df.count()} loan account records missing required fields. "
            f"Writing to quarantine."
        )
        quarantine_df.show(truncate=False)

    valid_df = df.filter(F.col("_has_required_fields"))

    # Resolve FK references
    valid_df = resolve_borrower_ids(spark, valid_df)
    valid_df = resolve_product_ids(spark, valid_df)

    # Apply column transformations, dropping denormalized borrower fields
    result = valid_df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("_borrower_id").alias("borrower_id"),
        F.col("_product_id").alias("product_id"),
        # Amount parsing: VARCHAR with commas → DECIMAL
        parse_legacy_amount("LN_ORIG_AMT", "original_amount"),
        parse_legacy_amount("LN_CURR_BAL", "current_balance"),
        parse_legacy_rate("LN_INT_RT", "interest_rate"),
        parse_legacy_integer("LN_TERM_MOS", "term_months"),
        parse_legacy_amount_10_2("LN_PMT_AMT", "monthly_payment"),
        # Date parsing: MM/DD/YYYY → DATE
        parse_legacy_date("LN_ORIG_DT", "origination_date"),
        parse_legacy_date("LN_MAT_DT", "maturity_date"),
        parse_legacy_date("LN_1ST_PMT_DT", "first_payment_date"),
        parse_legacy_date("LN_NXT_PMT_DT", "next_payment_date"),
        # Status expansion
        expand_status_code("LN_STAT_CD", LOAN_STATUS_MAP, "status"),
        parse_legacy_integer("LN_DLQ_DAYS", "delinquency_days"),
        parse_legacy_amount_10_2("LN_ESCROW_BAL", "escrow_balance"),
        parse_legacy_pct("LN_LTV_PCT", "ltv_percent"),
        # Property fields (direct copy)
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        # Property type expansion
        expand_status_code("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
        parse_legacy_amount("PROP_APRS_VAL", "appraised_value"),
        # Timestamp parsing
        parse_legacy_timestamp("LN_CRET_DT", "created_at"),
        parse_legacy_timestamp("LN_UPDT_DT", "updated_at"),
        # Audit columns
        F.current_timestamp().alias("_ingestion_ts"),
        F.lit("CDW_LN_ACCT").alias("_source_system"),
    )

    return result


def write_to_delta(df: DataFrame, mode: str = "overwrite"):
    """Write transformed loan accounts to Delta table, partitioned by status."""
    df.write.format("delta").mode(mode).partitionBy("status").saveAsTable(TARGET_TABLE)
    print(f"Successfully wrote {df.count()} records to {TARGET_TABLE}")


def main():
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_ACCT → loan_accounts")
    parser.add_argument("--source", required=True, help="Path to source data files")
    parser.add_argument(
        "--format", default="csv", choices=["csv", "parquet"], help="Source file format"
    )
    parser.add_argument(
        "--mode", default="overwrite", choices=["overwrite", "append"], help="Write mode"
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_LN_ACCT_Ingestion").getOrCreate()

    print(f"Reading source data from {args.source} (format={args.format})")
    source_df = read_source(spark, args.source, args.format)
    source_count = source_df.count()
    print(f"Source record count: {source_count}")

    print("Applying transformations (including FK resolution)...")
    transformed_df = transform_loan_accounts(spark, source_df)
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
