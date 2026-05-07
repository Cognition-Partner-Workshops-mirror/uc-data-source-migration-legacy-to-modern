"""
Ingest CDW_LN_PROD -> loan_warehouse.loan_products

Reads the legacy loan product extract, applies type conversions and
status-to-boolean mapping, then writes to the loan_products Delta table.

Usage (Databricks notebook cell):
    %run ./transforms
    %run ./ingest_loan_products
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
)

from transforms import (
    PRODUCT_STATUS_MAP,
    expand_status_bool,
    parse_amount,
    parse_date_mmddyyyy,
    parse_int,
    tag_load_metadata,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "dbfs:/mnt/landing/legacy/CDW_LN_PROD/"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_PATH = "dbfs:/mnt/landing/quarantine/CDW_LN_PROD/"

LEGACY_SCHEMA = StructType(
    [
        StructField("PROD_CD", StringType(), True),
        StructField("PROD_DESC_TXT", StringType(), True),
        StructField("PROD_TYP_CD", StringType(), True),
        StructField("PROD_TERM_MOS", StringType(), True),
        StructField("PROD_RT_TYP", StringType(), True),
        StructField("PROD_MIN_AMT", StringType(), True),
        StructField("PROD_MAX_AMT", StringType(), True),
        StructField("PROD_STAT_CD", StringType(), True),
        StructField("PROD_EFF_DT", StringType(), True),
        StructField("PROD_EXP_DT", StringType(), True),
    ]
)


def read_legacy_products(spark: SparkSession):
    """Read from CSV with header, falling back to Parquet."""
    try:
        df = (
            spark.read.format("csv")
            .option("header", "true")
            .option("mode", "PERMISSIVE")
            .schema(LEGACY_SCHEMA)
            .load(SOURCE_PATH)
        )
    except Exception:
        df = spark.read.format("parquet").load(SOURCE_PATH)
    return df


def transform_products(df):
    """Apply column mappings and type conversions for loan products."""
    transformed = df.select(
        F.trim(F.col("PROD_CD")).alias("code"),
        F.trim(F.col("PROD_DESC_TXT")).alias("name"),
        F.trim(F.col("PROD_TYP_CD")).alias("type"),
        parse_int(F.col("PROD_TERM_MOS")).alias("term_months"),
        F.trim(F.col("PROD_RT_TYP")).alias("rate_type"),
        parse_amount(F.col("PROD_MIN_AMT")).alias("min_amount"),
        parse_amount(F.col("PROD_MAX_AMT")).alias("max_amount"),
        expand_status_bool(F.col("PROD_STAT_CD"), PRODUCT_STATUS_MAP, False).alias(
            "is_active"
        ),
        parse_date_mmddyyyy(F.col("PROD_EFF_DT")).alias("effective_date"),
        parse_date_mmddyyyy(F.col("PROD_EXP_DT")).alias("expiration_date"),
        *tag_load_metadata("CDW_LN_PROD"),
    )
    return transformed


def quarantine_bad_records(df):
    """Quarantine products missing code or name."""
    bad_mask = (
        F.col("code").isNull()
        | (F.trim(F.col("code")) == "")
        | F.col("name").isNull()
        | (F.trim(F.col("name")) == "")
    )

    bad_records = df.filter(bad_mask)
    clean_records = df.filter(~bad_mask)

    bad_count = bad_records.count()
    if bad_count > 0:
        print(f"[WARN] Quarantining {bad_count} product records with missing required fields")
        bad_records.write.format("delta").mode("append").save(QUARANTINE_PATH)
    else:
        print("[INFO] No bad product records found")

    return clean_records


def write_products(df):
    """Merge into the target Delta table using code as the business key."""
    df.createOrReplaceTempView("products_staged")

    merge_sql = f"""
    MERGE INTO {TARGET_TABLE} AS target
    USING products_staged AS source
    ON target.code = source.code
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """
    spark = df.sparkSession
    spark.sql(merge_sql)
    print(f"[INFO] Loan products merged into {TARGET_TABLE}")


def run(spark: SparkSession):
    """Main entry point for loan product ingestion."""
    print("=" * 60)
    print("Starting loan product ingestion: CDW_LN_PROD -> loan_products")
    print("=" * 60)

    raw_df = read_legacy_products(spark)
    raw_count = raw_df.count()
    print(f"[INFO] Read {raw_count} raw product records from source")

    transformed_df = transform_products(raw_df)
    clean_df = quarantine_bad_records(transformed_df)
    clean_count = clean_df.count()
    print(f"[INFO] {clean_count} clean product records after validation")

    write_products(clean_df)

    final_count = spark.table(TARGET_TABLE).count()
    print(f"[INFO] Target table {TARGET_TABLE} now has {final_count} rows")
    print(f"[INFO] Source: {raw_count} | Quarantined: {raw_count - clean_count} | Loaded: {clean_count}")
    print("=" * 60)
    return {"source_count": raw_count, "clean_count": clean_count, "target_count": final_count}


# Allow direct execution in a Databricks notebook
# spark = SparkSession.builder.getOrCreate()
# run(spark)
