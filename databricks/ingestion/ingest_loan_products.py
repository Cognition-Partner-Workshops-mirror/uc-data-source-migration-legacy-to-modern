"""
Loan product ingestion script: CDW_LN_PROD → loan_warehouse.loan_products

Reads the legacy loan product reference table and transforms it into
the modern loan_products Delta Lake table with proper types.

Transformations applied:
  - PROD_TERM_MOS (VARCHAR "360") → term_months (INT)
  - PROD_MIN_AMT / PROD_MAX_AMT (VARCHAR "50,000") → DECIMAL(12,2)
  - PROD_STAT_CD (ACT/INA) → is_active (BOOLEAN)
  - PROD_EFF_DT / PROD_EXP_DT (VARCHAR MM/DD/YYYY) → DATE

Malformed rows are flagged and routed to quarantine, never silently dropped.
"""

import logging

from pyspark.sql import SparkSession, functions as F

from config import (
    SOURCE_PATHS,
    TARGET_TABLES,
    QUARANTINE_TABLE,
    LOAN_PRODUCT_LEGACY_SCHEMA,
    PRODUCT_STATUS_MAP,
)
from transformations import (
    parse_date,
    parse_amount,
    parse_integer,
    expand_to_boolean,
    add_etl_metadata,
    tag_malformed_rows,
    log_malformed_summary,
    read_legacy_source,
)

logger = logging.getLogger("cdw_migration.ingest_loan_products")


def ingest_loan_products(spark: SparkSession, file_format: str = "csv") -> dict:
    """
    Main ingestion function for loan products.

    Returns a dict with row counts for reconciliation:
      {"source_count": int, "target_count": int, "quarantine_count": int}
    """
    logger.info("Starting loan product ingestion from CDW_LN_PROD")

    # -------------------------------------------------------------------------
    # Step 1: Read legacy source data
    # -------------------------------------------------------------------------
    raw_df = read_legacy_source(
        spark, SOURCE_PATHS["loan_products"], LOAN_PRODUCT_LEGACY_SCHEMA, file_format
    )
    source_count = raw_df.count()
    logger.info(f"Read {source_count} rows from CDW_LN_PROD")

    # -------------------------------------------------------------------------
    # Step 2: Apply column-level transformations per column_mappings.md
    # -------------------------------------------------------------------------
    transformed_df = raw_df.select(
        # Natural key — direct copy
        F.col("PROD_CD").alias("code"),

        # Description renamed to name — direct copy
        F.col("PROD_DESC_TXT").alias("name"),

        # Product type (FXD, ARM, FHA, VA) — direct copy
        F.col("PROD_TYP_CD").alias("type"),

        # Term in months — parse VARCHAR to INT
        parse_integer("PROD_TERM_MOS", "term_months"),

        # Rate type (FIXED, VARIABLE) — direct copy
        F.col("PROD_RT_TYP").alias("rate_type"),

        # Amount range — remove commas, parse to DECIMAL(12,2)
        parse_amount("PROD_MIN_AMT", "min_amount"),
        parse_amount("PROD_MAX_AMT", "max_amount"),

        # Active flag — convert status code to boolean (ACT→true, INA→false)
        expand_to_boolean("PROD_STAT_CD", PRODUCT_STATUS_MAP, "is_active"),

        # Dates — parse MM/DD/YYYY to DATE
        parse_date("PROD_EFF_DT", "effective_date"),
        parse_date("PROD_EXP_DT", "expiration_date"),
    )

    # -------------------------------------------------------------------------
    # Step 3: Flag malformed rows (required fields that are NULL)
    # -------------------------------------------------------------------------
    required_cols = ["code", "name", "type", "term_months", "rate_type"]
    transformed_df = tag_malformed_rows(transformed_df, required_cols)
    log_malformed_summary(transformed_df, "loan_products")

    # -------------------------------------------------------------------------
    # Step 4: Separate clean vs. quarantine records
    # -------------------------------------------------------------------------
    clean_df = transformed_df.filter(~F.col("_is_malformed")).drop("_is_malformed")
    quarantine_df = transformed_df.filter(F.col("_is_malformed")).drop("_is_malformed")

    # Add ETL metadata
    clean_df = add_etl_metadata(clean_df, "CDW_LN_PROD")

    # -------------------------------------------------------------------------
    # Step 5: Write clean records to Delta Lake target table
    # -------------------------------------------------------------------------
    clean_count = clean_df.count()
    logger.info(f"Writing {clean_count} clean loan product records to {TARGET_TABLES['loan_products']}")

    clean_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLES["loan_products"])

    # -------------------------------------------------------------------------
    # Step 6: Write quarantine records (if any)
    # -------------------------------------------------------------------------
    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        logger.warning(f"Writing {quarantine_count} quarantined loan product records")
        quarantine_with_meta = add_etl_metadata(quarantine_df, "CDW_LN_PROD")
        quarantine_with_meta.withColumn(
            "_quarantine_reason", F.lit("Required field NULL after transformation")
        ).write.format("delta").mode("append").option(
            "mergeSchema", "true"
        ).saveAsTable(QUARANTINE_TABLE)

    result = {
        "source_count": source_count,
        "target_count": clean_count,
        "quarantine_count": quarantine_count,
    }
    logger.info(f"Loan product ingestion complete: {result}")
    return result


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Migration_LoanProducts").getOrCreate()
    ingest_loan_products(spark)
    spark.stop()
