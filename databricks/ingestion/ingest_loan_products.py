"""
Ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads legacy loan product data, applies transformations per column_mappings.md,
and writes to the modern loan_products Delta table.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from .utils import (
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    quarantine_bad_records,
    read_legacy_source,
)


def ingest_loan_products(spark: SparkSession, source_path: str,
                         file_format: str = "csv",
                         write_mode: str = "overwrite") -> dict:
    """Ingest loan product data from legacy CDW_LN_PROD source.

    Args:
        spark: Active SparkSession
        source_path: Path to CDW_LN_PROD source file(s)
        file_format: Source format ('csv' or 'parquet')
        write_mode: Delta write mode ('overwrite' or 'append')

    Returns:
        dict with source_count, target_count, quarantined_count
    """
    print("[INFO] Starting loan product ingestion from CDW_LN_PROD")

    # Read source
    raw_df = read_legacy_source(spark, source_path, file_format)
    source_count = raw_df.count()
    print(f"[INFO] Source records read: {source_count}")

    # --- Transformations ---

    df = raw_df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        F.col("PROD_TERM_MOS"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        F.col("PROD_MIN_AMT"),
        F.col("PROD_MAX_AMT"),
        F.col("PROD_STAT_CD"),
        F.col("PROD_EFF_DT"),
        F.col("PROD_EXP_DT"),
    )

    # Parse term_months: string -> INT
    df = parse_int_col(df, "PROD_TERM_MOS", "term_months")

    # Parse min/max amounts: comma-formatted -> DECIMAL(12,2)
    df = parse_amount_col(df, "PROD_MIN_AMT", "min_amount")
    df = parse_amount_col(df, "PROD_MAX_AMT", "max_amount")

    # Convert status to boolean: ACT -> true, INA -> false
    df = df.withColumn(
        "is_active",
        F.when(F.col("PROD_STAT_CD") == "ACT", F.lit(True))
         .when(F.col("PROD_STAT_CD") == "INA", F.lit(False))
         .otherwise(F.lit(None))
    ).withColumn(
        "_err_is_active",
        F.when(
            F.col("PROD_STAT_CD").isNotNull() &
            ~F.col("PROD_STAT_CD").isin("ACT", "INA"),
            F.concat(F.lit("Unknown product status: "), F.col("PROD_STAT_CD"))
        )
    )

    # Parse dates
    df = parse_date_col(df, "PROD_EFF_DT", "effective_date")
    df = parse_date_col(df, "PROD_EXP_DT", "expiration_date")

    # Drop intermediate columns
    df = df.drop("PROD_TERM_MOS", "PROD_MIN_AMT", "PROD_MAX_AMT",
                 "PROD_STAT_CD", "PROD_EFF_DT", "PROD_EXP_DT")

    # Add lineage columns
    df = df.withColumn("_migration_source", F.lit("CDW_LN_PROD")) \
           .withColumn("_migrated_at", F.current_timestamp())

    # Quarantine bad records
    clean_df = quarantine_bad_records(df, "loan_products", spark)

    # Write to Delta
    target_count = clean_df.count()
    clean_df.write \
        .mode(write_mode) \
        .format("delta") \
        .saveAsTable("loan_warehouse.loan_products")

    quarantined_count = source_count - target_count
    print(f"[INFO] Loan product ingestion complete: {target_count} written, "
          f"{quarantined_count} quarantined")

    return {
        "table": "loan_products",
        "source_count": source_count,
        "target_count": target_count,
        "quarantined_count": quarantined_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder \
        .appName("LoanMigration_LoanProducts") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .getOrCreate()

    import sys
    source = sys.argv[1] if len(sys.argv) > 1 else "/mnt/legacy-export/CDW_LN_PROD/"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "csv"

    result = ingest_loan_products(spark, source, fmt)
    print(f"[RESULT] {result}")
