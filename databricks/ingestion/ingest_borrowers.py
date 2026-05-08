"""
Ingest legacy CDW_BORR_MSTR into the modern borrowers Delta Lake table.

Source : CSV or Parquet export of CDW_BORR_MSTR
Target : loan_warehouse.borrowers (Delta)

Transformations applied (per column_mappings.md):
  - Date strings (MM/DD/YYYY) → DateType / TimestampType
  - Comma-formatted amount strings → DecimalType
  - Credit score string → IntegerType
  - Status code expansion: ACT → ACTIVE, INA → INACTIVE
  - BORR_REC_TYP column is dropped (no modern equivalent)
  - Null / malformed values are logged, never silently dropped
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    BORROWER_STATUS_MAP,
    expand_code,
    parse_amount,
    parse_date,
    parse_int,
    parse_timestamp,
)

# ---------------------------------------------------------------------------
# Configuration — adjust these paths for your Databricks environment
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy_exports/CDW_BORR_MSTR"
LEGACY_SOURCE_FORMAT = "csv"  # Change to "parquet" if applicable
TARGET_TABLE = "loan_warehouse.borrowers"


def read_legacy_borrowers(spark: SparkSession, path: str = LEGACY_SOURCE_PATH,
                          fmt: str = LEGACY_SOURCE_FORMAT) -> DataFrame:
    """Read the legacy borrower source file (CSV or Parquet)."""
    reader = spark.read.format(fmt)
    if fmt == "csv":
        # Legacy exports typically include a header row
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(path)


def transform_borrowers(df: DataFrame) -> DataFrame:
    """Apply all column mappings and type conversions for borrowers.

    Adds a _parse_errors column that collects per-row warnings so that no
    record is silently dropped.
    """
    transformed = df.select(
        # Direct copies
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),

        # Date conversions
        parse_date(F.col("BORR_DOB_DT")).alias("date_of_birth"),

        # Address fields — direct copies
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),

        # Numeric conversions
        parse_int(F.col("BORR_CRDT_SCR")).alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount(F.col("BORR_ANN_INCM")).alias("annual_income"),

        # Status code expansion
        expand_code(F.col("BORR_STAT_CD"), BORROWER_STATUS_MAP).alias("status"),

        # Timestamp conversions
        parse_timestamp(F.col("BORR_CRET_DT")).alias("created_at"),
        parse_timestamp(F.col("BORR_UPDT_DT")).alias("updated_at"),
    )

    # ------------------------------------------------------------------
    # Build a per-row error log for malformed / null values
    # ------------------------------------------------------------------
    error_checks = F.array_remove(
        F.array(
            F.when(F.col("external_id").isNull(), F.lit("BORR_ID is null")),
            F.when(F.col("first_name").isNull(), F.lit("BORR_FST_NM is null")),
            F.when(F.col("last_name").isNull(), F.lit("BORR_LST_NM is null")),
            F.when(F.col("date_of_birth").isNull() & F.col("BORR_DOB_DT").isNotNull(),
                   F.lit("BORR_DOB_DT failed date parse")),
            F.when(F.col("credit_score").isNull() & F.col("BORR_CRDT_SCR").isNotNull(),
                   F.lit("BORR_CRDT_SCR failed int parse")),
            F.when(F.col("annual_income").isNull() & F.col("BORR_ANN_INCM").isNotNull(),
                   F.lit("BORR_ANN_INCM failed decimal parse")),
        ),
        None,  # remove null array elements (checks that passed)
    )

    # Re-join original columns needed for error checking, then drop them
    transformed_with_errors = (
        df.select(
            F.col("BORR_DOB_DT"),
            F.col("BORR_CRDT_SCR"),
            F.col("BORR_ANN_INCM"),
        )
        .withColumn("_row_idx", F.monotonically_increasing_id())
    )

    transformed = transformed.withColumn("_row_idx", F.monotonically_increasing_id())
    result = transformed.join(transformed_with_errors, "_row_idx", "left")

    result = result.withColumn("_parse_errors", error_checks).drop(
        "_row_idx", "BORR_DOB_DT", "BORR_CRDT_SCR", "BORR_ANN_INCM"
    )

    return result


def log_errors(df: DataFrame, spark: SparkSession) -> None:
    """Print and persist rows that had parse warnings."""
    error_rows = df.filter(F.size("_parse_errors") > 0)
    error_count = error_rows.count()
    if error_count > 0:
        print(f"[WARN] {error_count} borrower row(s) had parse warnings:")
        error_rows.select("external_id", "_parse_errors").show(truncate=False)
        # Optionally persist error rows for downstream review
        error_rows.write.format("delta").mode("overwrite").saveAsTable(
            "loan_warehouse._borrower_ingestion_errors"
        )
    else:
        print("[INFO] All borrower rows parsed successfully — no warnings.")


def write_borrowers(df: DataFrame) -> None:
    """Write the clean borrower records to the target Delta table."""
    # Drop the internal error-tracking column before writing to the gold table
    clean = df.drop("_parse_errors")
    clean.write.format("delta").mode("overwrite").saveAsTable(TARGET_TABLE)
    print(f"[INFO] Wrote {clean.count()} borrower records to {TARGET_TABLE}.")


# ---------------------------------------------------------------------------
# Entry point — run as a Databricks notebook or submitted job
# ---------------------------------------------------------------------------
def main() -> None:
    spark = SparkSession.builder.appName("Ingest_Borrowers").getOrCreate()

    print("[INFO] Reading legacy CDW_BORR_MSTR …")
    raw = read_legacy_borrowers(spark)
    source_count = raw.count()
    print(f"[INFO] Source row count: {source_count}")

    print("[INFO] Transforming borrower records …")
    transformed = transform_borrowers(raw)

    log_errors(transformed, spark)
    write_borrowers(transformed)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[INFO] Target row count: {target_count}")
    if source_count != target_count:
        print(f"[ERROR] Row count mismatch! Source={source_count}, Target={target_count}")
    else:
        print("[INFO] Row count reconciliation passed.")


if __name__ == "__main__":
    main()
