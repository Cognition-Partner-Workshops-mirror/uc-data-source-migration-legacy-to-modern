"""
Ingest CDW_LN_PROD → loan_warehouse.loan_products

Reads the legacy loan product catalog, applies type conversions and status
mapping (ACT→true, INA→false), and writes to the modern Delta Lake table.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

from transforms import (
    parse_date,
    parse_amount,
    parse_int,
    expand_to_boolean,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "/mnt/landing/legacy/CDW_LN_PROD"
TARGET_TABLE = "loan_warehouse.loan_products"
QUARANTINE_TABLE = "loan_warehouse._quarantine_loan_products"

LEGACY_SCHEMA = StructType([
    StructField("PROD_CD",        StringType(), True),
    StructField("PROD_DESC_TXT",  StringType(), True),
    StructField("PROD_TYP_CD",    StringType(), True),
    StructField("PROD_TERM_MOS",  StringType(), True),
    StructField("PROD_RT_TYP",    StringType(), True),
    StructField("PROD_MIN_AMT",   StringType(), True),
    StructField("PROD_MAX_AMT",   StringType(), True),
    StructField("PROD_STAT_CD",   StringType(), True),
    StructField("PROD_EFF_DT",    StringType(), True),
    StructField("PROD_EXP_DT",    StringType(), True),
])


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH) -> DataFrame:
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
    transformed = (
        df
        .withColumn("code",            F.trim(F.col("PROD_CD")))
        .withColumn("name",            F.trim(F.col("PROD_DESC_TXT")))
        .withColumn("type",            F.trim(F.col("PROD_TYP_CD")))
        .withColumn("term_months",     parse_int(F.col("PROD_TERM_MOS")))
        .withColumn("rate_type",       F.trim(F.col("PROD_RT_TYP")))
        .withColumn("min_amount",      parse_amount(F.col("PROD_MIN_AMT")))
        .withColumn("max_amount",      parse_amount(F.col("PROD_MAX_AMT")))
        .withColumn("is_active",       expand_to_boolean(F.col("PROD_STAT_CD"), true_code="ACT"))
        .withColumn("effective_date",  parse_date(F.col("PROD_EFF_DT")))
        .withColumn("expiration_date", parse_date(F.col("PROD_EXP_DT")))
    )

    quarantine_condition = (
        F.col("code").isNull()
        | F.col("name").isNull()
        | F.col("type").isNull()
        | F.col("rate_type").isNull()
        | (F.col("code") == F.lit(""))
        | (F.col("name") == F.lit(""))
    )

    quarantine = (
        transformed
        .filter(quarantine_condition)
        .withColumn("_quarantine_reason", F.lit("Missing required field (code, name, type, or rate_type)"))
        .withColumn("_quarantine_ts", F.current_timestamp())
    )

    good = transformed.filter(~quarantine_condition)

    target_columns = [
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "is_active",
        "effective_date", "expiration_date",
    ]

    return good.select(target_columns), quarantine


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(df: DataFrame, table: str = TARGET_TABLE) -> None:
    from delta.tables import DeltaTable

    if DeltaTable.isDeltaTable(df.sparkSession, table):
        delta_table = DeltaTable.forName(df.sparkSession, table)
        (
            delta_table.alias("tgt")
            .merge(df.alias("src"), "tgt.code = src.code")
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
            .saveAsTable(table)
        )


def write_quarantine(df: DataFrame, table: str = QUARANTINE_TABLE) -> None:
    if df.count() > 0:
        (
            df.write
            .format("delta")
            .mode("append")
            .saveAsTable(table)
        )
        print(f"WARNING: {df.count()} loan product record(s) quarantined to {table}")
    else:
        print("No loan product records quarantined.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession, source_path: str = SOURCE_PATH) -> dict:
    raw = read_source(spark, source_path)
    source_count = raw.count()
    print(f"[loan_products] Source rows read: {source_count}")

    good, quarantine = transform(raw)
    good_count = good.count()
    quarantine_count = quarantine.count()

    print(f"[loan_products] Good rows:        {good_count}")
    print(f"[loan_products] Quarantined rows:  {quarantine_count}")

    write_target(good)
    write_quarantine(quarantine)

    return {
        "table": TARGET_TABLE,
        "source_count": source_count,
        "target_count": good_count,
        "quarantine_count": quarantine_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest CDW_LN_PROD → loan_products").getOrCreate()
    stats = run(spark)
    print(f"[loan_products] Ingestion complete: {stats}")
