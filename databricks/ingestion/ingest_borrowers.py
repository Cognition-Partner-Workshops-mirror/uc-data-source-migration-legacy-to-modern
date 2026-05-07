"""
Ingestion notebook: CDW_BORR_MSTR -> loan_warehouse.borrowers

Run in Databricks as a notebook or via `spark-submit`.
Reads the legacy borrower master data (CSV/Parquet), applies transformations
per column_mappings.md, and writes to the modern Delta Lake borrowers table.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    expand_borrower_status,
    parse_amount,
    parse_date_mmddyyyy,
    parse_int,
    parse_timestamp_mmddyyyy,
)

# ---------------------------------------------------------------------------
# Configuration  (override via Databricks widgets or job parameters)
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/legacy-export/CDW_BORR_MSTR"   # CSV or Parquet
SOURCE_FORMAT = "csv"                                     # csv | parquet
TARGET_TABLE = "loan_warehouse.borrowers"
WRITE_MODE = "overwrite"                                  # overwrite | append

# ---------------------------------------------------------------------------
# Spark session (already available in Databricks notebooks as `spark`)
# ---------------------------------------------------------------------------
spark = SparkSession.builder.appName("ingest_borrowers").getOrCreate()
spark.conf.set("spark.sql.legacy.timeParserPolicy", "CORRECTED")

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
_LOG_TAG = "[ingest_borrowers]"


def _log(msg: str) -> None:
    print(f"{_LOG_TAG} {msg}")


# ---------------------------------------------------------------------------
# Read source
# ---------------------------------------------------------------------------

def read_source(path: str, fmt: str) -> DataFrame:
    """Read legacy CSV or Parquet export of CDW_BORR_MSTR."""
    _log(f"Reading source from {path} (format={fmt})")
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    df = reader.load(path)
    _log(f"Source row count: {df.count()}")
    return df


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame) -> DataFrame:
    """Apply all column mappings for the borrowers table."""

    # Track rows that fail critical parsing so we can log them
    transformed = df.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_date_mmddyyyy(F.col("BORR_DOB_DT")).alias("date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        parse_int(F.col("BORR_CRDT_SCR")).alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount(F.col("BORR_ANN_INCM")).alias("annual_income"),
        parse_timestamp_mmddyyyy(F.col("BORR_CRET_DT")).alias("created_at"),
        parse_timestamp_mmddyyyy(F.col("BORR_UPDT_DT")).alias("updated_at"),
        expand_borrower_status(F.col("BORR_STAT_CD")).alias("status"),
        F.col("BORR_REC_TYP").alias("_legacy_record_type"),
    )

    # ------- Null / malformed-value checks (log, do NOT drop) -------
    required_cols = ["external_id", "first_name", "last_name"]
    for col_name in required_cols:
        null_count = transformed.filter(F.col(col_name).isNull()).count()
        if null_count > 0:
            _log(f"WARNING: {null_count} rows have NULL {col_name}")

    bad_dates = transformed.filter(
        F.col("date_of_birth").isNull() & df["BORR_DOB_DT"].isNotNull()
    ).count()
    if bad_dates > 0:
        _log(f"WARNING: {bad_dates} rows had unparseable date_of_birth values")

    bad_income = transformed.filter(
        F.col("annual_income").isNull() & df["BORR_ANN_INCM"].isNotNull()
    ).count()
    if bad_income > 0:
        _log(f"WARNING: {bad_income} rows had unparseable annual_income values")

    _log(f"Transformed row count: {transformed.count()}")
    return transformed


# ---------------------------------------------------------------------------
# Write to Delta Lake
# ---------------------------------------------------------------------------

def write_target(df: DataFrame, table: str, mode: str) -> None:
    """Write the transformed DataFrame to the target Delta table."""
    _log(f"Writing {df.count()} rows to {table} (mode={mode})")
    df.write.format("delta").mode(mode).option(
        "mergeSchema", "true"
    ).saveAsTable(table)
    _log("Write complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    source_df = read_source(SOURCE_PATH, SOURCE_FORMAT)
    transformed_df = transform(source_df)
    write_target(transformed_df, TARGET_TABLE, WRITE_MODE)
    _log("Borrower ingestion finished successfully.")


if __name__ == "__main__":
    main()
