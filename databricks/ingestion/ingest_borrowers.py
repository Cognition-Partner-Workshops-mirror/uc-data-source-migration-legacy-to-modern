"""
Borrower ingestion script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads the legacy borrower master table (all-VARCHAR, cryptic column names)
and transforms it into the modern borrowers Delta Lake table with proper types.

Transformations applied:
  - BORR_DOB_DT (VARCHAR MM/DD/YYYY) → date_of_birth (DATE)
  - BORR_ANN_INCM (VARCHAR "92,500") → annual_income (DECIMAL(12,2))
  - BORR_CRDT_SCR (VARCHAR "745") → credit_score (INT)
  - BORR_STAT_CD (ACT/INA) → status (Active/Inactive)
  - BORR_CRET_DT / BORR_UPDT_DT → created_at / updated_at (TIMESTAMP)
  - BORR_REC_TYP dropped (not needed in modern schema)

Malformed rows are flagged and routed to quarantine, never silently dropped.
"""

import logging

from pyspark.sql import SparkSession, functions as F

from config import (
    SOURCE_PATHS,
    TARGET_TABLES,
    QUARANTINE_TABLE,
    BORROWER_LEGACY_SCHEMA,
    BORROWER_STATUS_MAP,
)
from transformations import (
    parse_date,
    parse_timestamp,
    parse_amount,
    parse_integer,
    expand_status_code,
    add_etl_metadata,
    tag_malformed_rows,
    log_malformed_summary,
    read_legacy_source,
)

logger = logging.getLogger("cdw_migration.ingest_borrowers")


def ingest_borrowers(spark: SparkSession, file_format: str = "csv") -> dict:
    """
    Main ingestion function for borrowers.

    Returns a dict with row counts for reconciliation:
      {"source_count": int, "target_count": int, "quarantine_count": int}
    """
    logger.info("Starting borrower ingestion from CDW_BORR_MSTR")

    # -------------------------------------------------------------------------
    # Step 1: Read legacy source data
    # -------------------------------------------------------------------------
    raw_df = read_legacy_source(
        spark, SOURCE_PATHS["borrowers"], BORROWER_LEGACY_SCHEMA, file_format
    )
    source_count = raw_df.count()
    logger.info(f"Read {source_count} rows from CDW_BORR_MSTR")

    # -------------------------------------------------------------------------
    # Step 2: Apply column-level transformations per column_mappings.md
    # -------------------------------------------------------------------------
    transformed_df = raw_df.select(
        # Natural key — direct copy
        F.col("BORR_ID").alias("external_id"),

        # Name fields — direct copy
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),

        # SSN hash — direct copy (re-encryption recommended post-migration)
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),

        # Date of birth — parse MM/DD/YYYY string to DATE
        parse_date("BORR_DOB_DT", "date_of_birth"),

        # Address fields — direct copy
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),

        # Contact fields — direct copy
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),

        # Credit score — parse VARCHAR to INT
        parse_integer("BORR_CRDT_SCR", "credit_score"),

        # Employment status — direct copy
        F.col("BORR_EMP_STAT").alias("employment_status"),

        # Annual income — remove commas, parse to DECIMAL(12,2)
        parse_amount("BORR_ANN_INCM", "annual_income"),

        # Status — expand abbreviation (ACT→Active, INA→Inactive)
        expand_status_code("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),

        # Audit timestamps — parse MM/DD/YYYY to TIMESTAMP (midnight)
        parse_timestamp("BORR_CRET_DT", "created_at"),
        parse_timestamp("BORR_UPDT_DT", "updated_at"),

        # Note: BORR_REC_TYP is intentionally dropped per column_mappings.md
    )

    # -------------------------------------------------------------------------
    # Step 3: Flag malformed rows (required fields that parsed to NULL)
    # -------------------------------------------------------------------------
    required_cols = ["external_id", "first_name", "last_name"]
    transformed_df = tag_malformed_rows(transformed_df, required_cols)
    log_malformed_summary(transformed_df, "borrowers")

    # -------------------------------------------------------------------------
    # Step 4: Separate clean vs. quarantine records
    # -------------------------------------------------------------------------
    clean_df = transformed_df.filter(~F.col("_is_malformed")).drop("_is_malformed")
    quarantine_df = transformed_df.filter(F.col("_is_malformed")).drop("_is_malformed")

    # Add ETL metadata to clean records
    clean_df = add_etl_metadata(clean_df, "CDW_BORR_MSTR")

    # -------------------------------------------------------------------------
    # Step 5: Write clean records to Delta Lake target table
    # -------------------------------------------------------------------------
    clean_count = clean_df.count()
    logger.info(f"Writing {clean_count} clean borrower records to {TARGET_TABLES['borrowers']}")

    clean_df.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(TARGET_TABLES["borrowers"])

    # -------------------------------------------------------------------------
    # Step 6: Write quarantine records (if any) for manual review
    # -------------------------------------------------------------------------
    quarantine_count = quarantine_df.count()
    if quarantine_count > 0:
        logger.warning(f"Writing {quarantine_count} quarantined borrower records")
        quarantine_with_meta = add_etl_metadata(quarantine_df, "CDW_BORR_MSTR")
        quarantine_with_meta.withColumn(
            "_quarantine_reason", F.lit("Required field NULL after transformation")
        ).write.format("delta").mode("append").option(
            "mergeSchema", "true"
        ).saveAsTable(QUARANTINE_TABLE)

    # -------------------------------------------------------------------------
    # Return reconciliation counts
    # -------------------------------------------------------------------------
    result = {
        "source_count": source_count,
        "target_count": clean_count,
        "quarantine_count": quarantine_count,
    }
    logger.info(f"Borrower ingestion complete: {result}")
    return result


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Migration_Borrowers").getOrCreate()
    ingest_borrowers(spark)
    spark.stop()
