"""
Ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads legacy loan account data, applies transformations per column_mappings.md,
resolves FK references to borrowers and loan_products, drops denormalized
borrower fields, and writes to the modern loan_accounts Delta table.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from .utils import (
    expand_status_code,
    parse_amount_col,
    parse_date_col,
    parse_decimal_col,
    parse_int_col,
    parse_timestamp_col,
    quarantine_bad_records,
    read_legacy_source,
)


def ingest_loan_accounts(spark: SparkSession, source_path: str,
                         file_format: str = "csv",
                         write_mode: str = "overwrite") -> dict:
    """Ingest loan account data from legacy CDW_LN_ACCT source.

    Resolves borrower_id and product_id foreign keys by joining against
    the already-loaded borrowers and loan_products tables.

    Args:
        spark: Active SparkSession
        source_path: Path to CDW_LN_ACCT source file(s)
        file_format: Source format ('csv' or 'parquet')
        write_mode: Delta write mode ('overwrite' or 'append')

    Returns:
        dict with source_count, target_count, quarantined_count
    """
    print("[INFO] Starting loan account ingestion from CDW_LN_ACCT")

    # Read source
    raw_df = read_legacy_source(spark, source_path, file_format)
    source_count = raw_df.count()
    print(f"[INFO] Source records read: {source_count}")

    # --- FK Resolution ---
    # Load lookup tables for borrower and product ID resolution
    borrowers_lookup = spark.table("loan_warehouse.borrowers") \
        .select(F.col("id").alias("_borrower_id"), F.col("external_id"))

    products_lookup = spark.table("loan_warehouse.loan_products") \
        .select(F.col("id").alias("_product_id"), F.col("code").alias("_prod_code"))

    # --- Transformations ---

    # Select relevant columns (drop denormalized borrower fields)
    df = raw_df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID"),
        F.col("PROD_CD"),
        F.col("LN_ORIG_AMT"),
        F.col("LN_CURR_BAL"),
        F.col("LN_INT_RT"),
        F.col("LN_TERM_MOS"),
        F.col("LN_PMT_AMT"),
        F.col("LN_ORIG_DT"),
        F.col("LN_MAT_DT"),
        F.col("LN_1ST_PMT_DT"),
        F.col("LN_NXT_PMT_DT"),
        F.col("LN_STAT_CD"),
        F.col("LN_DLQ_DAYS"),
        F.col("LN_ESCROW_BAL"),
        F.col("LN_LTV_PCT"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        F.col("PROP_TYP_CD"),
        F.col("PROP_APRS_VAL"),
        F.col("LN_CRET_DT"),
        F.col("LN_UPDT_DT"),
    )

    # Resolve borrower FK
    df = df.join(borrowers_lookup, df["BORR_ID"] == borrowers_lookup["external_id"], "left") \
           .withColumn("borrower_id", F.col("_borrower_id")) \
           .drop("_borrower_id", "external_id") \
           .withColumn(
               "_err_borrower_id",
               F.when(F.col("borrower_id").isNull() & F.col("BORR_ID").isNotNull(),
                      F.concat(F.lit("Borrower not found: "), F.col("BORR_ID")))
           )

    # Resolve product FK
    df = df.join(products_lookup, df["PROD_CD"] == products_lookup["_prod_code"], "left") \
           .withColumn("product_id", F.col("_product_id")) \
           .drop("_product_id", "_prod_code") \
           .withColumn(
               "_err_product_id",
               F.when(F.col("product_id").isNull() & F.col("PROD_CD").isNotNull(),
                      F.concat(F.lit("Product not found: "), F.col("PROD_CD")))
           )

    # Parse amounts
    df = parse_amount_col(df, "LN_ORIG_AMT", "original_amount")
    df = parse_amount_col(df, "LN_CURR_BAL", "current_balance")
    df = parse_amount_col(df, "LN_PMT_AMT", "monthly_payment", precision=10)
    df = parse_amount_col(df, "LN_ESCROW_BAL", "escrow_balance", precision=10)
    df = parse_amount_col(df, "PROP_APRS_VAL", "appraised_value")

    # Parse rates and percentages
    df = parse_decimal_col(df, "LN_INT_RT", "interest_rate", precision=5, scale=3)
    df = parse_decimal_col(df, "LN_LTV_PCT", "ltv_percent", precision=5, scale=2)

    # Parse integers
    df = parse_int_col(df, "LN_TERM_MOS", "term_months")
    df = parse_int_col(df, "LN_DLQ_DAYS", "delinquency_days")

    # Parse dates
    df = parse_date_col(df, "LN_ORIG_DT", "origination_date")
    df = parse_date_col(df, "LN_MAT_DT", "maturity_date")
    df = parse_date_col(df, "LN_1ST_PMT_DT", "first_payment_date")
    df = parse_date_col(df, "LN_NXT_PMT_DT", "next_payment_date")

    # Parse timestamps
    df = parse_timestamp_col(df, "LN_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "LN_UPDT_DT", "updated_at")

    # Expand status codes
    df = expand_status_code(df, "LN_STAT_CD", "status", "loan_status")
    df = expand_status_code(df, "PROP_TYP_CD", "property_type", "property_type")

    # Derive origination_year for partitioning
    df = df.withColumn("origination_year", F.year(F.col("origination_date")))

    # Drop intermediate source columns
    df = df.drop(
        "BORR_ID", "PROD_CD", "LN_ORIG_AMT", "LN_CURR_BAL", "LN_INT_RT",
        "LN_TERM_MOS", "LN_PMT_AMT", "LN_ORIG_DT", "LN_MAT_DT",
        "LN_1ST_PMT_DT", "LN_NXT_PMT_DT", "LN_STAT_CD", "LN_DLQ_DAYS",
        "LN_ESCROW_BAL", "LN_LTV_PCT", "PROP_TYP_CD", "PROP_APRS_VAL",
        "LN_CRET_DT", "LN_UPDT_DT"
    )

    # Add lineage columns
    df = df.withColumn("_migration_source", F.lit("CDW_LN_ACCT")) \
           .withColumn("_migrated_at", F.current_timestamp())

    # Quarantine bad records
    clean_df = quarantine_bad_records(df, "loan_accounts", spark)

    # Write to Delta
    target_count = clean_df.count()
    clean_df.write \
        .mode(write_mode) \
        .format("delta") \
        .partitionBy("status", "origination_year") \
        .saveAsTable("loan_warehouse.loan_accounts")

    quarantined_count = source_count - target_count
    print(f"[INFO] Loan account ingestion complete: {target_count} written, "
          f"{quarantined_count} quarantined")

    return {
        "table": "loan_accounts",
        "source_count": source_count,
        "target_count": target_count,
        "quarantined_count": quarantined_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder \
        .appName("LoanMigration_LoanAccounts") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .getOrCreate()

    import sys
    source = sys.argv[1] if len(sys.argv) > 1 else "/mnt/legacy-export/CDW_LN_ACCT/"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "csv"

    result = ingest_loan_accounts(spark, source, fmt)
    print(f"[RESULT] {result}")
