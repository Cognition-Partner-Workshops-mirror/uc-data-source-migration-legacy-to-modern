"""
Ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads legacy loan product data, converts types (term months, amounts, dates),
maps status to boolean is_active, and writes to Delta Lake.

Usage:
    spark = SparkSession.builder.getOrCreate()
    ingest_loan_products(spark, source_path="dbfs:/mnt/legacy/CDW_LN_PROD.csv")
"""

import logging

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from common_utils import (
    PRODUCT_STATUS_MAP,
    quarantine_malformed,
    read_legacy_csv,
    read_legacy_parquet,
    register_udfs,
    write_delta,
)

logger = logging.getLogger("cdw_migration.loan_products")

TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_products"

REQUIRED_COLUMNS = ["code", "name", "type", "term_months", "rate_type"]


def ingest_loan_products(spark: SparkSession, source_path: str,
                         source_format: str = "csv"):
    """
    End-to-end ingestion of CDW_LN_PROD into loan_warehouse.loan_products.
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
    # 2. Transform columns per column_mappings.md
    # ------------------------------------------------------------------
    # Build boolean mapping for product status
    status_expr = F.create_map(
        *[F.lit(x) for kv in {k: str(v) for k, v in PRODUCT_STATUS_MAP.items()}.items()
          for x in kv]
    )

    transformed_df = (
        raw_df
        .withColumn("code", F.trim(F.col("PROD_CD")))
        .withColumn("name", F.trim(F.col("PROD_DESC_TXT")))
        .withColumn("type", F.trim(F.col("PROD_TYP_CD")))
        .withColumn("term_months", udfs["parse_int"](F.col("PROD_TERM_MOS")))
        .withColumn("rate_type", F.trim(F.col("PROD_RT_TYP")))
        .withColumn("min_amount", udfs["parse_amount_12_2"](F.col("PROD_MIN_AMT")))
        .withColumn("max_amount", udfs["parse_amount_12_2"](F.col("PROD_MAX_AMT")))
        .withColumn(
            "is_active",
            F.when(
                status_expr[F.upper(F.trim(F.col("PROD_STAT_CD")))] == "True",
                F.lit(True)
            ).otherwise(F.lit(False)))
        .withColumn("effective_date", udfs["parse_date"](F.col("PROD_EFF_DT")))
        .withColumn("expiration_date", udfs["parse_date"](F.col("PROD_EXP_DT")))
    )

    # Drop legacy columns
    legacy_cols = [c for c in raw_df.columns if c.startswith(("PROD_", "prod_"))]
    modern_df = transformed_df.drop(*legacy_cols)

    # Add audit columns
    modern_df = (
        modern_df
        .withColumn("_ingestion_ts", F.current_timestamp())
        .withColumn("_source_system", F.lit("CDW_LN_PROD"))
    )

    # ------------------------------------------------------------------
    # 3. Quarantine malformed rows
    # ------------------------------------------------------------------
    valid_df, quarantine_df = quarantine_malformed(
        modern_df, TARGET_TABLE, REQUIRED_COLUMNS
    )

    # ------------------------------------------------------------------
    # 4. Write to Delta Lake (no partitioning — small reference table)
    # ------------------------------------------------------------------
    write_delta(valid_df, TARGET_TABLE, mode="overwrite")

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

    return {
        "source_count": source_count,
        "target_count": target_count,
        "quarantine_count": quarantine_count,
        "reconciled": source_count == target_count + quarantine_count,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    spark = SparkSession.builder.appName("CDW_LoanProduct_Ingestion").getOrCreate()

    path = sys.argv[1] if len(sys.argv) > 1 else "dbfs:/mnt/legacy/CDW_LN_PROD.csv"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "csv"

    result = ingest_loan_products(spark, source_path=path, source_format=fmt)
    print(f"Ingestion result: {result}")
