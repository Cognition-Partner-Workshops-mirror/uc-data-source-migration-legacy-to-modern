"""
Ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads legacy borrower data from CSV/Parquet, applies type conversions and
status expansion, quarantines malformed rows, and writes to Delta Lake.

Usage (Databricks notebook or spark-submit):
    %run ./common_utils
    # or: from ingestion.common_utils import ...

    spark = SparkSession.builder.getOrCreate()
    ingest_borrowers(spark, source_path="dbfs:/mnt/legacy/CDW_BORR_MSTR.csv")
"""

import logging

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from common_utils import (
    BORROWER_STATUS_MAP,
    map_status_column,
    quarantine_malformed,
    read_legacy_csv,
    read_legacy_parquet,
    register_udfs,
    write_delta,
)

logger = logging.getLogger("cdw_migration.borrowers")

TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_TABLE = "loan_warehouse._quarantine_borrowers"

REQUIRED_COLUMNS = ["external_id", "first_name", "last_name"]


def ingest_borrowers(spark: SparkSession, source_path: str,
                     source_format: str = "csv"):
    """
    End-to-end ingestion of CDW_BORR_MSTR into loan_warehouse.borrowers.

    Parameters
    ----------
    spark : SparkSession
    source_path : str
        Path to the legacy borrower export (CSV or Parquet).
    source_format : str
        Either 'csv' or 'parquet'.
    """
    udfs = register_udfs(spark)

    # ------------------------------------------------------------------
    # 1. Read source
    # ------------------------------------------------------------------
    if source_format == "parquet":
        raw_df = read_legacy_parquet(spark, source_path)
    else:
        raw_df = read_legacy_csv(spark, source_path)

    source_count = raw_df.count()
    logger.info("Source row count: %d", source_count)

    # ------------------------------------------------------------------
    # 2. Rename & transform columns per column_mappings.md
    # ------------------------------------------------------------------
    transformed_df = (
        raw_df
        .withColumn("external_id", F.trim(F.col("BORR_ID")))
        .withColumn("first_name", F.trim(F.col("BORR_FST_NM")))
        .withColumn("last_name", F.trim(F.col("BORR_LST_NM")))
        .withColumn("middle_initial", F.trim(F.col("BORR_MID_INIT")))
        .withColumn("ssn_hash", F.trim(F.col("BORR_SSN_ENCR")))
        .withColumn("date_of_birth", udfs["parse_date"](F.col("BORR_DOB_DT")))
        .withColumn("address_line1", F.trim(F.col("BORR_ADDR_LN1")))
        .withColumn("address_line2", F.trim(F.col("BORR_ADDR_LN2")))
        .withColumn("city", F.trim(F.col("BORR_CTY_NM")))
        .withColumn("state", F.trim(F.col("BORR_ST_CD")))
        .withColumn("zip_code", F.trim(F.col("BORR_ZIP_CD")))
        .withColumn("phone", F.trim(F.col("BORR_PH_NBR")))
        .withColumn("email", F.trim(F.col("BORR_EMAIL_ADDR")))
        .withColumn("credit_score", udfs["parse_int"](F.col("BORR_CRDT_SCR")))
        .withColumn("employment_status", F.trim(F.col("BORR_EMP_STAT")))
        .withColumn("annual_income", udfs["parse_amount_12_2"](F.col("BORR_ANN_INCM")))
        .withColumn("created_at", udfs["parse_timestamp"](F.col("BORR_CRET_DT")))
        .withColumn("updated_at", udfs["parse_timestamp"](F.col("BORR_UPDT_DT")))
    )

    # Expand status codes: ACT -> ACTIVE, INA -> INACTIVE
    transformed_df = map_status_column(
        transformed_df, "BORR_STAT_CD", "status", BORROWER_STATUS_MAP
    )

    # Drop BORR_REC_TYP (not needed in modern schema) and legacy columns
    legacy_cols = [c for c in raw_df.columns if c.startswith(("BORR_", "borr_"))]
    modern_df = transformed_df.drop(*legacy_cols)

    # Add audit columns
    modern_df = (
        modern_df
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit("CDW_BORR_MSTR"))
    )

    # ------------------------------------------------------------------
    # 3. Quarantine malformed rows
    # ------------------------------------------------------------------
    valid_df, quarantine_df = quarantine_malformed(
        modern_df, TARGET_TABLE, REQUIRED_COLUMNS
    )

    # ------------------------------------------------------------------
    # 4. Write to Delta Lake
    # ------------------------------------------------------------------
    write_delta(valid_df, TARGET_TABLE, mode="overwrite", partition_cols=["state"])

    if quarantine_df.count() > 0:
        write_delta(quarantine_df, QUARANTINE_TABLE, mode="overwrite")

    # ------------------------------------------------------------------
    # 5. Post-write validation
    # ------------------------------------------------------------------
    target_count = spark.table(TARGET_TABLE).count()
    quarantine_count = quarantine_df.count()

    logger.info("Ingestion complete for %s", TARGET_TABLE)
    logger.info("  Source rows:      %d", source_count)
    logger.info("  Target rows:      %d", target_count)
    logger.info("  Quarantined rows: %d", quarantine_count)
    logger.info("  Reconciliation:   %s",
                "PASS" if source_count == target_count + quarantine_count else "FAIL")

    return {
        "source_count": source_count,
        "target_count": target_count,
        "quarantine_count": quarantine_count,
        "reconciled": source_count == target_count + quarantine_count,
    }


# ---------------------------------------------------------------------------
# Notebook / spark-submit entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    spark = SparkSession.builder.appName("CDW_Borrower_Ingestion").getOrCreate()

    path = sys.argv[1] if len(sys.argv) > 1 else "dbfs:/mnt/legacy/CDW_BORR_MSTR.csv"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "csv"

    result = ingest_borrowers(spark, source_path=path, source_format=fmt)
    print(f"Ingestion result: {result}")
