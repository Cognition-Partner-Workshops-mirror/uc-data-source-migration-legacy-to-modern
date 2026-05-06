"""
Ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads legacy borrower master data, applies transformations per column_mappings.md,
and writes to the modern borrowers Delta table.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from .utils import (
    expand_status_code,
    parse_amount_col,
    parse_date_col,
    parse_int_col,
    parse_timestamp_col,
    quarantine_bad_records,
    read_legacy_source,
)


def ingest_borrowers(spark: SparkSession, source_path: str,
                     file_format: str = "csv",
                     write_mode: str = "overwrite") -> dict:
    """Ingest borrower data from legacy CDW_BORR_MSTR source.

    Args:
        spark: Active SparkSession
        source_path: Path to CDW_BORR_MSTR source file(s)
        file_format: Source format ('csv' or 'parquet')
        write_mode: Delta write mode ('overwrite' or 'append')

    Returns:
        dict with source_count, target_count, quarantined_count
    """
    print("[INFO] Starting borrower ingestion from CDW_BORR_MSTR")

    # Read source
    raw_df = read_legacy_source(spark, source_path, file_format)
    source_count = raw_df.count()
    print(f"[INFO] Source records read: {source_count}")

    # --- Transformations ---

    # Rename and direct-copy columns
    df = raw_df.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        F.col("BORR_DOB_DT"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        F.col("BORR_CRDT_SCR"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        F.col("BORR_ANN_INCM"),
        F.col("BORR_CRET_DT"),
        F.col("BORR_UPDT_DT"),
        F.col("BORR_STAT_CD"),
    )

    # Parse date_of_birth: MM/DD/YYYY -> DATE
    df = parse_date_col(df, "BORR_DOB_DT", "date_of_birth")

    # Parse credit_score: string -> INT
    df = parse_int_col(df, "BORR_CRDT_SCR", "credit_score")

    # Parse annual_income: comma-formatted string -> DECIMAL(12,2)
    df = parse_amount_col(df, "BORR_ANN_INCM", "annual_income")

    # Parse timestamps
    df = parse_timestamp_col(df, "BORR_CRET_DT", "created_at")
    df = parse_timestamp_col(df, "BORR_UPDT_DT", "updated_at")

    # Expand status code: ACT -> ACTIVE, INA -> INACTIVE
    df = expand_status_code(df, "BORR_STAT_CD", "status", "borrower_status")

    # Drop intermediate source columns
    df = df.drop("BORR_DOB_DT", "BORR_CRDT_SCR", "BORR_ANN_INCM",
                 "BORR_CRET_DT", "BORR_UPDT_DT", "BORR_STAT_CD")

    # Add lineage columns
    df = df.withColumn("_migration_source", F.lit("CDW_BORR_MSTR")) \
           .withColumn("_migrated_at", F.current_timestamp())

    # Quarantine bad records
    clean_df = quarantine_bad_records(df, "borrowers", spark)

    # Write to Delta
    target_count = clean_df.count()
    clean_df.write \
        .mode(write_mode) \
        .format("delta") \
        .partitionBy("state") \
        .saveAsTable("loan_warehouse.borrowers")

    quarantined_count = source_count - target_count
    print(f"[INFO] Borrower ingestion complete: {target_count} written, "
          f"{quarantined_count} quarantined")

    return {
        "table": "borrowers",
        "source_count": source_count,
        "target_count": target_count,
        "quarantined_count": quarantined_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder \
        .appName("LoanMigration_Borrowers") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .getOrCreate()

    import sys
    source = sys.argv[1] if len(sys.argv) > 1 else "/mnt/legacy-export/CDW_BORR_MSTR/"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "csv"

    result = ingest_borrowers(spark, source, fmt)
    print(f"[RESULT] {result}")
