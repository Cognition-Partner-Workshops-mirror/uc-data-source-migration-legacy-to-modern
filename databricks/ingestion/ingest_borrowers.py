"""
PySpark ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads legacy borrower data (CSV/Parquet), applies transformations per
column_mappings.md, and writes to Delta Lake.

Usage (Databricks notebook or job):
    %run ./ingest_borrowers
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DateType, DecimalType, IntegerType,
    TimestampType
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy-cdw/CDW_BORR_MSTR/"
TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_TABLE = "loan_warehouse._quarantine_borrowers"
DATE_FORMAT = "MM/dd/yyyy"

# ---------------------------------------------------------------------------
# Schema for legacy source (all VARCHAR -> StringType)
# ---------------------------------------------------------------------------
LEGACY_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), False),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_MID_INIT", StringType(), True),
    StructField("BORR_SSN_ENCR", StringType(), True),
    StructField("BORR_DOB_DT", StringType(), True),
    StructField("BORR_ADDR_LN1", StringType(), True),
    StructField("BORR_ADDR_LN2", StringType(), True),
    StructField("BORR_CTY_NM", StringType(), True),
    StructField("BORR_ST_CD", StringType(), True),
    StructField("BORR_ZIP_CD", StringType(), True),
    StructField("BORR_PH_NBR", StringType(), True),
    StructField("BORR_EMAIL_ADDR", StringType(), True),
    StructField("BORR_CRDT_SCR", StringType(), True),
    StructField("BORR_EMP_STAT", StringType(), True),
    StructField("BORR_ANN_INCM", StringType(), True),
    StructField("BORR_CRET_DT", StringType(), True),
    StructField("BORR_UPDT_DT", StringType(), True),
    StructField("BORR_STAT_CD", StringType(), True),
    StructField("BORR_REC_TYP", StringType(), True),
])


def read_legacy_borrowers(spark: SparkSession) -> DataFrame:
    """Read legacy borrower data from CSV or Parquet source."""
    return (
        spark.read
        .option("header", "true")
        .schema(LEGACY_SCHEMA)
        .csv(LEGACY_SOURCE_PATH)
    )


def parse_legacy_amount(col_name: str):
    """Remove commas and non-numeric chars, cast to decimal.
    Handles legacy amounts like '285,000' or '$1,487.02'."""
    # Strip everything except digits, decimal point, and minus sign
    cleaned = F.regexp_replace(F.col(col_name), r"[^0-9.\-]", "")
    return F.when(
        (F.col(col_name).isNull()) | (F.trim(F.col(col_name)) == ""),
        F.lit(None).cast(DecimalType(12, 2))
    ).otherwise(cleaned.cast(DecimalType(12, 2)))


def parse_legacy_date(col_name: str):
    """Parse MM/DD/YYYY string to DateType."""
    return F.to_date(F.col(col_name), DATE_FORMAT)


def expand_status(col_name: str):
    """Expand legacy status code abbreviations."""
    return (
        F.when(F.col(col_name) == "ACT", "ACTIVE")
        .when(F.col(col_name) == "INA", "INACTIVE")
        .otherwise(F.concat(F.lit("UNKNOWN:"), F.coalesce(F.col(col_name), F.lit("NULL"))))
    )


def transform_borrowers(df: DataFrame) -> DataFrame:
    """Apply all transformations from legacy to modern schema.
    Maps cryptic CDW column names to meaningful modern names,
    parses dates/amounts, and expands status code abbreviations."""
    return df.select(
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_legacy_date("BORR_DOB_DT").alias("date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        F.col("BORR_CRDT_SCR").cast(IntegerType()).alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_legacy_amount("BORR_ANN_INCM").alias("annual_income"),
        expand_status("BORR_STAT_CD").alias("status"),
        parse_legacy_date("BORR_CRET_DT").cast(TimestampType()).alias("created_at"),
        parse_legacy_date("BORR_UPDT_DT").cast(TimestampType()).alias("updated_at"),
    )


def quarantine_bad_records(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Separate records that fail critical validation from clean records.
    Bad records are written to a quarantine table instead of being silently dropped.
    """
    # Critical fields that must be present for a valid borrower record
    # Records failing this filter go to quarantine instead of being dropped
    critical_filter = (
        F.col("external_id").isNotNull()
        & F.col("first_name").isNotNull()
        & F.col("last_name").isNotNull()
        & F.col("ssn_hash").isNotNull()
    )
    good = df.filter(critical_filter)
    bad = df.filter(~critical_filter).withColumn(
        "_quarantine_reason",
        F.concat_ws(", ",
            F.when(F.col("external_id").isNull(), F.lit("missing external_id")),
            F.when(F.col("first_name").isNull(), F.lit("missing first_name")),
            F.when(F.col("last_name").isNull(), F.lit("missing last_name")),
            F.when(F.col("ssn_hash").isNull(), F.lit("missing ssn_hash")),
        )
    ).withColumn("_quarantine_ts", F.current_timestamp())

    return good, bad


def validate_credit_scores(df: DataFrame) -> DataFrame:
    """Flag credit scores outside valid range (300-850)."""
    return df.withColumn(
        "credit_score",
        F.when(
            (F.col("credit_score") >= 300) & (F.col("credit_score") <= 850),
            F.col("credit_score")
        ).otherwise(F.lit(None).cast(IntegerType()))
    )


def run(spark: SparkSession):
    """Main ingestion pipeline."""
    print("=== Borrower Ingestion: START ===")

    raw_df = read_legacy_borrowers(spark)
    source_count = raw_df.count()
    print(f"Source record count: {source_count}")

    transformed_df = transform_borrowers(raw_df)
    good_df, bad_df = quarantine_bad_records(transformed_df)
    good_df = validate_credit_scores(good_df)

    good_count = good_df.count()
    bad_count = bad_df.count()
    print(f"Clean records: {good_count}, Quarantined records: {bad_count}")

    # Write clean records to target
    (
        good_df.write
        .format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )
    print(f"Wrote {good_count} records to {TARGET_TABLE}")

    # Write bad records to quarantine
    if bad_count > 0:
        (
            bad_df.write
            .format("delta")
            .mode("append")
            .option("mergeSchema", "true")
            .saveAsTable(QUARANTINE_TABLE)
        )
        print(f"Quarantined {bad_count} records to {QUARANTINE_TABLE}")

    print("=== Borrower Ingestion: COMPLETE ===")
    return source_count, good_count, bad_count


# When run as a Databricks notebook
if __name__ == "__main__":
    spark = SparkSession.builder.getOrCreate()
    run(spark)
