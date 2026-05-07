"""
Ingest CDW_BORR_MSTR → loan_warehouse.borrowers

Reads the legacy borrower master from a CSV/Parquet source file, applies all
column mappings and type conversions documented in data/mappings/column_mappings.md,
and writes the result to the modern Delta Lake borrowers table.

Records that fail transformation are quarantined to a separate table rather
than silently dropped.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType,
)

from transforms import (
    parse_date,
    parse_timestamp,
    parse_amount,
    parse_int,
    expand_code,
    BORROWER_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "/mnt/landing/legacy/CDW_BORR_MSTR"   # CSV or Parquet
TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_TABLE = "loan_warehouse._quarantine_borrowers"

# Schema for CSV ingestion (all VARCHAR in legacy → all StringType here)
LEGACY_SCHEMA = StructType([
    StructField("BORR_ID",         StringType(), True),
    StructField("BORR_FST_NM",     StringType(), True),
    StructField("BORR_LST_NM",     StringType(), True),
    StructField("BORR_MID_INIT",   StringType(), True),
    StructField("BORR_SSN_ENCR",   StringType(), True),
    StructField("BORR_DOB_DT",     StringType(), True),
    StructField("BORR_ADDR_LN1",   StringType(), True),
    StructField("BORR_ADDR_LN2",   StringType(), True),
    StructField("BORR_CTY_NM",     StringType(), True),
    StructField("BORR_ST_CD",      StringType(), True),
    StructField("BORR_ZIP_CD",     StringType(), True),
    StructField("BORR_PH_NBR",     StringType(), True),
    StructField("BORR_EMAIL_ADDR", StringType(), True),
    StructField("BORR_CRDT_SCR",   StringType(), True),
    StructField("BORR_EMP_STAT",   StringType(), True),
    StructField("BORR_ANN_INCM",   StringType(), True),
    StructField("BORR_CRET_DT",    StringType(), True),
    StructField("BORR_UPDT_DT",    StringType(), True),
    StructField("BORR_STAT_CD",    StringType(), True),
    StructField("BORR_REC_TYP",    StringType(), True),
])


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH) -> DataFrame:
    """Read legacy borrower data.  Tries Parquet first, falls back to CSV."""
    try:
        return spark.read.parquet(path)
    except Exception:
        return (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .schema(LEGACY_SCHEMA)
            .csv(path)
        )


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Apply all column mappings and return (good_records, quarantine_records).

    Quarantine criteria: NULL in BORR_ID, BORR_FST_NM, or BORR_LST_NM
    (these are NOT NULL in the target table).
    """
    transformed = (
        df
        .withColumn("external_id",        F.trim(F.col("BORR_ID")))
        .withColumn("first_name",         F.trim(F.col("BORR_FST_NM")))
        .withColumn("last_name",          F.trim(F.col("BORR_LST_NM")))
        .withColumn("middle_initial",     F.trim(F.col("BORR_MID_INIT")))
        .withColumn("ssn_hash",           F.trim(F.col("BORR_SSN_ENCR")))
        .withColumn("date_of_birth",      parse_date(F.col("BORR_DOB_DT")))
        .withColumn("address_line1",      F.trim(F.col("BORR_ADDR_LN1")))
        .withColumn("address_line2",      F.trim(F.col("BORR_ADDR_LN2")))
        .withColumn("city",               F.trim(F.col("BORR_CTY_NM")))
        .withColumn("state",              F.trim(F.col("BORR_ST_CD")))
        .withColumn("zip_code",           F.trim(F.col("BORR_ZIP_CD")))
        .withColumn("phone",              F.trim(F.col("BORR_PH_NBR")))
        .withColumn("email",              F.trim(F.col("BORR_EMAIL_ADDR")))
        .withColumn("credit_score",       parse_int(F.col("BORR_CRDT_SCR")))
        .withColumn("employment_status",  F.trim(F.col("BORR_EMP_STAT")))
        .withColumn("annual_income",      parse_amount(F.col("BORR_ANN_INCM")))
        .withColumn("status",             expand_code(F.col("BORR_STAT_CD"), BORROWER_STATUS_MAP, default="Active"))
        .withColumn("created_at",         parse_timestamp(F.col("BORR_CRET_DT")))
        .withColumn("updated_at",         parse_timestamp(F.col("BORR_UPDT_DT")))
        # BORR_REC_TYP is intentionally dropped per column_mappings.md
    )

    # Tag rows that violate NOT NULL constraints
    quarantine_condition = (
        F.col("external_id").isNull()
        | F.col("first_name").isNull()
        | F.col("last_name").isNull()
        | (F.col("external_id") == F.lit(""))
        | (F.col("first_name") == F.lit(""))
        | (F.col("last_name") == F.lit(""))
    )

    quarantine = (
        transformed
        .filter(quarantine_condition)
        .withColumn("_quarantine_reason", F.lit("Missing required field (external_id, first_name, or last_name)"))
        .withColumn("_quarantine_ts", F.current_timestamp())
    )

    good = transformed.filter(~quarantine_condition)

    # Select only modern columns for the target table
    target_columns = [
        "external_id", "first_name", "last_name", "middle_initial",
        "ssn_hash", "date_of_birth", "address_line1", "address_line2",
        "city", "state", "zip_code", "phone", "email", "credit_score",
        "employment_status", "annual_income", "status", "created_at", "updated_at",
    ]

    return good.select(target_columns), quarantine


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(df: DataFrame, table: str = TARGET_TABLE) -> None:
    """Merge-upsert into the borrowers Delta table on external_id."""
    from delta.tables import DeltaTable

    if DeltaTable.isDeltaTable(df.sparkSession, table):
        delta_table = DeltaTable.forName(df.sparkSession, table)
        (
            delta_table.alias("tgt")
            .merge(df.alias("src"), "tgt.external_id = src.external_id")
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )
    else:
        (
            df.write
            .format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .partitionBy("state")
            .saveAsTable(table)
        )


def write_quarantine(df: DataFrame, table: str = QUARANTINE_TABLE) -> None:
    """Append quarantined rows for manual review."""
    if df.count() > 0:
        (
            df.write
            .format("delta")
            .mode("append")
            .saveAsTable(table)
        )
        print(f"WARNING: {df.count()} borrower record(s) quarantined to {table}")
    else:
        print("No borrower records quarantined.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession, source_path: str = SOURCE_PATH) -> dict:
    """Execute the full borrower ingestion pipeline. Returns row-count stats."""
    raw = read_source(spark, source_path)
    source_count = raw.count()
    print(f"[borrowers] Source rows read: {source_count}")

    good, quarantine = transform(raw)
    good_count = good.count()
    quarantine_count = quarantine.count()

    print(f"[borrowers] Good rows:        {good_count}")
    print(f"[borrowers] Quarantined rows:  {quarantine_count}")

    write_target(good)
    write_quarantine(quarantine)

    return {
        "table": TARGET_TABLE,
        "source_count": source_count,
        "target_count": good_count,
        "quarantine_count": quarantine_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest CDW_BORR_MSTR → borrowers").getOrCreate()
    stats = run(spark)
    print(f"[borrowers] Ingestion complete: {stats}")
