"""
Ingest CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads the legacy borrower master extract (CSV or Parquet), applies type
conversions and status code expansion, then writes to the borrowers Delta table.

Usage (Databricks notebook cell):
    %run ./transforms
    %run ./ingest_borrowers
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
)

from transforms import (
    BORROWER_STATUS_MAP,
    expand_status,
    parse_amount,
    parse_date_mmddyyyy,
    parse_int,
    parse_timestamp_mmddyyyy,
    tag_load_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/landing/legacy/CDW_BORR_MSTR/"
TARGET_TABLE = "loan_warehouse.borrowers"
QUARANTINE_PATH = "dbfs:/mnt/landing/quarantine/CDW_BORR_MSTR/"

# Schema for CSV source (all STRING to mirror legacy VARCHAR-everything)
LEGACY_SCHEMA = StructType(
    [
        StructField("BORR_ID", StringType(), True),
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
    ]
)


def read_legacy_borrowers(spark: SparkSession):
    """Read from CSV with header, falling back to Parquet if CSV is unavailable."""
    try:
        df = (
            spark.read.format("csv")
            .option("header", "true")
            .option("mode", "PERMISSIVE")
            .option("columnNameOfCorruptRecord", "_corrupt_record")
            .schema(LEGACY_SCHEMA)
            .load(SOURCE_PATH)
        )
    except Exception:
        df = spark.read.format("parquet").load(SOURCE_PATH)
    return df


def transform_borrowers(df):
    """
    Apply all column mappings and type conversions from CDW_BORR_MSTR
    to the modern borrowers schema.
    """
    transformed = df.select(
        F.trim(F.col("BORR_ID")).alias("external_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
        F.trim(F.col("BORR_SSN_ENCR")).alias("ssn_hash"),
        parse_date_mmddyyyy(F.col("BORR_DOB_DT")).alias("date_of_birth"),
        F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
        F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
        F.trim(F.col("BORR_CTY_NM")).alias("city"),
        F.trim(F.col("BORR_ST_CD")).alias("state"),
        F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),
        F.trim(F.col("BORR_PH_NBR")).alias("phone"),
        F.trim(F.col("BORR_EMAIL_ADDR")).alias("email"),
        parse_int(F.col("BORR_CRDT_SCR")).alias("credit_score"),
        F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),
        parse_amount(F.col("BORR_ANN_INCM")).alias("annual_income"),
        expand_status(F.col("BORR_STAT_CD"), BORROWER_STATUS_MAP, "UNKNOWN").alias(
            "status"
        ),
        parse_timestamp_mmddyyyy(F.col("BORR_CRET_DT")).alias("created_at"),
        parse_timestamp_mmddyyyy(F.col("BORR_UPDT_DT")).alias("updated_at"),
        *tag_load_metadata("CDW_BORR_MSTR"),
    )
    return transformed


def quarantine_bad_records(df):
    """
    Identify rows missing required fields (external_id, first_name, last_name)
    and write them to a quarantine location for manual review.
    Returns the clean DataFrame.
    """
    bad_mask = (
        F.col("external_id").isNull()
        | (F.trim(F.col("external_id")) == "")
        | F.col("first_name").isNull()
        | (F.trim(F.col("first_name")) == "")
        | F.col("last_name").isNull()
        | (F.trim(F.col("last_name")) == "")
    )

    bad_records = df.filter(bad_mask)
    clean_records = df.filter(~bad_mask)

    bad_count = bad_records.count()
    if bad_count > 0:
        print(f"[WARN] Quarantining {bad_count} borrower records with missing required fields")
        bad_records.write.format("delta").mode("append").save(QUARANTINE_PATH)
    else:
        print("[INFO] No bad borrower records found")

    return clean_records


def write_borrowers(df):
    """Merge into the target Delta table using external_id as the business key."""
    df.createOrReplaceTempView("borrowers_staged")

    merge_sql = f"""
    MERGE INTO {TARGET_TABLE} AS target
    USING borrowers_staged AS source
    ON target.external_id = source.external_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """
    spark = df.sparkSession
    spark.sql(merge_sql)
    print(f"[INFO] Borrowers merged into {TARGET_TABLE}")


def run(spark: SparkSession):
    """Main entry point for borrower ingestion."""
    print("=" * 60)
    print("Starting borrower ingestion: CDW_BORR_MSTR -> borrowers")
    print("=" * 60)

    raw_df = read_legacy_borrowers(spark)
    raw_count = raw_df.count()
    print(f"[INFO] Read {raw_count} raw borrower records from source")

    transformed_df = transform_borrowers(raw_df)
    clean_df = quarantine_bad_records(transformed_df)
    clean_count = clean_df.count()
    print(f"[INFO] {clean_count} clean borrower records after validation")

    write_borrowers(clean_df)

    final_count = spark.table(TARGET_TABLE).count()
    print(f"[INFO] Target table {TARGET_TABLE} now has {final_count} rows")
    print(f"[INFO] Source: {raw_count} | Quarantined: {raw_count - clean_count} | Loaded: {clean_count}")
    print("=" * 60)
    return {"source_count": raw_count, "clean_count": clean_count, "target_count": final_count}


# Allow direct execution in a Databricks notebook
# spark = SparkSession.builder.getOrCreate()
# run(spark)
