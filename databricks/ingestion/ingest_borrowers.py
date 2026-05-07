"""
PySpark Ingestion Script: CDW_BORR_MSTR → loan_warehouse.borrowers

Reads from legacy borrower source (CSV/Parquet) and transforms into
the modern normalized borrowers table with proper types and validation.

Anomalies handled:
  - ANO-001: Numeric amounts stored as strings with commas
  - ANO-002: Dates in MM/DD/YYYY string format
  - ANO-004: Status code abbreviation expansion
  - ANO-006: Null values in required fields
  - ANO-007: Credit score range validation
  - ANO-012: Duplicate/near-duplicate detection
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DateType, DecimalType, IntegerType,
    TimestampType
)
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/legacy-cdw/CDW_BORR_MSTR"  # CSV or Parquet
SOURCE_FORMAT = "csv"  # Change to "parquet" if applicable
TARGET_TABLE = "loan_warehouse.borrowers"
DQ_LOG_TABLE = "loan_warehouse.data_quality_log"
RUN_ID = f"borrower_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# Legacy CSV schema (all VARCHAR → StringType)
LEGACY_SCHEMA = StructType([
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
])

# Status code expansion mapping
STATUS_MAP = {"ACT": "ACTIVE", "INA": "INACTIVE"}


def read_source(spark: SparkSession) -> DataFrame:
    """Read legacy CDW borrower data from source files."""
    if SOURCE_FORMAT == "csv":
        return (
            spark.read
            .schema(LEGACY_SCHEMA)
            .option("header", "true")
            .option("quote", '"')
            .csv(SOURCE_PATH)
        )
    else:
        return spark.read.parquet(SOURCE_PATH)


def parse_legacy_date(col_name: str, alias: str) -> F.Column:
    """
    ANO-002: Parse date strings with fallback.
    Tries MM/dd/yyyy first, then yyyy-MM-dd.
    Returns null (not dropped) on failure so the record is preserved.
    """
    return F.coalesce(
        F.to_date(F.col(col_name), "MM/dd/yyyy"),
        F.to_date(F.col(col_name), "yyyy-MM-dd"),
    ).alias(alias)


def parse_legacy_amount(col_name: str, alias: str) -> F.Column:
    """
    ANO-001: Parse amount strings like '92,500' → 92500.00.
    Strips $, commas, spaces before casting.
    """
    cleaned = F.regexp_replace(F.col(col_name), r"[$,\s]", "")
    return cleaned.cast(DecimalType(12, 2)).alias(alias)


def expand_status(col_name: str, mapping: dict, alias: str) -> F.Column:
    """ANO-004: Expand status code abbreviations."""
    mapping_expr = F.create_map(
        *[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    upper_col = F.upper(F.trim(F.col(col_name)))
    return F.coalesce(mapping_expr[upper_col], upper_col).alias(alias)


def validate_credit_score(col_name: str, alias: str) -> F.Column:
    """ANO-007: Parse and flag credit scores outside 300-850."""
    score = F.col(col_name).cast(IntegerType())
    return F.when(
        score.between(300, 850), score
    ).otherwise(score).alias(alias)  # Keep value but log anomaly separately


def transform(df: DataFrame) -> DataFrame:
    """Apply all transformations from legacy to modern schema."""
    return df.select(
        F.col("BORR_ID").alias("external_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.trim(F.col("BORR_MID_INIT")).alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_legacy_date("BORR_DOB_DT", "date_of_birth"),
        F.trim(F.col("BORR_ADDR_LN1")).alias("address_line1"),
        F.trim(F.col("BORR_ADDR_LN2")).alias("address_line2"),
        F.trim(F.col("BORR_CTY_NM")).alias("city"),
        F.trim(F.col("BORR_ST_CD")).alias("state"),
        F.trim(F.col("BORR_ZIP_CD")).alias("zip_code"),
        F.trim(F.col("BORR_PH_NBR")).alias("phone"),
        F.trim(F.col("BORR_EMAIL_ADDR")).alias("email"),
        validate_credit_score("BORR_CRDT_SCR", "credit_score"),
        F.trim(F.col("BORR_EMP_STAT")).alias("employment_status"),
        parse_legacy_amount("BORR_ANN_INCM", "annual_income"),
        expand_status("BORR_STAT_CD", STATUS_MAP, "status"),
        F.coalesce(
            F.to_timestamp(F.col("BORR_CRET_DT"), "MM/dd/yyyy"),
            F.to_timestamp(F.col("BORR_CRET_DT"), "yyyy-MM-dd"),
            F.current_timestamp()
        ).alias("created_at"),
        F.coalesce(
            F.to_timestamp(F.col("BORR_UPDT_DT"), "MM/dd/yyyy"),
            F.to_timestamp(F.col("BORR_UPDT_DT"), "yyyy-MM-dd"),
            F.current_timestamp()
        ).alias("updated_at"),
        F.current_timestamp().alias("_ingestion_ts"),
        F.lit("CDW").alias("_source_system"),
    )


def detect_anomalies(source_df: DataFrame, transformed_df: DataFrame,
                     spark: SparkSession) -> DataFrame:
    """
    Detect and log data quality anomalies to the DQ log table.
    Returns a DataFrame of anomaly records.
    """
    anomalies = []

    # ANO-006: Null required fields
    null_checks = {
        "BORR_ID": "external_id",
        "BORR_FST_NM": "first_name",
        "BORR_LST_NM": "last_name",
        "BORR_SSN_ENCR": "ssn_hash",
    }
    for legacy_col, modern_col in null_checks.items():
        null_records = source_df.filter(
            F.col(legacy_col).isNull() | (F.trim(F.col(legacy_col)) == "")
        ).select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_BORR_MSTR").alias("source_table"),
            F.coalesce(F.col("BORR_ID"), F.lit("UNKNOWN")).alias("source_record_id"),
            F.lit(legacy_col).alias("column_name"),
            F.lit("NULL_REQUIRED").alias("anomaly_type"),
            F.lit("CRITICAL").alias("severity"),
            F.lit(f"Required field {legacy_col} is null/blank").alias("description"),
            F.col(legacy_col).alias("original_value"),
            F.lit(None).cast(StringType()).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
        anomalies.append(null_records)

    # ANO-002: Unparseable dates
    date_cols = ["BORR_DOB_DT", "BORR_CRET_DT", "BORR_UPDT_DT"]
    for col_name in date_cols:
        bad_dates = source_df.filter(
            F.col(col_name).isNotNull()
            & F.to_date(F.col(col_name), "MM/dd/yyyy").isNull()
            & F.to_date(F.col(col_name), "yyyy-MM-dd").isNull()
        ).select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_BORR_MSTR").alias("source_table"),
            F.col("BORR_ID").alias("source_record_id"),
            F.lit(col_name).alias("column_name"),
            F.lit("PARSE_FAILURE").alias("anomaly_type"),
            F.lit("HIGH").alias("severity"),
            F.lit(f"Date value in {col_name} could not be parsed").alias("description"),
            F.col(col_name).alias("original_value"),
            F.lit(None).cast(StringType()).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
        anomalies.append(bad_dates)

    # ANO-007: Credit score out of range
    score_col = F.col("BORR_CRDT_SCR").cast(IntegerType())
    bad_scores = source_df.filter(
        F.col("BORR_CRDT_SCR").isNotNull()
        & (
            score_col.isNull()  # Non-numeric
            | ~score_col.between(300, 850)
        )
    ).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_BORR_MSTR").alias("source_table"),
        F.col("BORR_ID").alias("source_record_id"),
        F.lit("BORR_CRDT_SCR").alias("column_name"),
        F.lit("BUSINESS_RULE").alias("anomaly_type"),
        F.lit("HIGH").alias("severity"),
        F.lit("Credit score is non-numeric or outside 300-850 range").alias("description"),
        F.col("BORR_CRDT_SCR").alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(bad_scores)

    # ANO-001: Unparseable amounts
    cleaned_income = F.regexp_replace(F.col("BORR_ANN_INCM"), r"[$,\s]", "")
    bad_amounts = source_df.filter(
        F.col("BORR_ANN_INCM").isNotNull()
        & cleaned_income.cast(DecimalType(12, 2)).isNull()
    ).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_BORR_MSTR").alias("source_table"),
        F.col("BORR_ID").alias("source_record_id"),
        F.lit("BORR_ANN_INCM").alias("column_name"),
        F.lit("PARSE_FAILURE").alias("anomaly_type"),
        F.lit("CRITICAL").alias("severity"),
        F.lit("Annual income value could not be parsed to decimal").alias("description"),
        F.col("BORR_ANN_INCM").alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(bad_amounts)

    # ANO-012: Duplicate detection (same name + DOB)
    dupes = (
        source_df
        .groupBy(
            F.upper(F.trim(F.col("BORR_FST_NM"))),
            F.upper(F.trim(F.col("BORR_LST_NM"))),
            F.col("BORR_DOB_DT")
        )
        .agg(
            F.count("*").alias("cnt"),
            F.collect_list("BORR_ID").alias("ids")
        )
        .filter(F.col("cnt") > 1)
    )
    if dupes.count() > 0:
        dupe_records = dupes.select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_BORR_MSTR").alias("source_table"),
            F.concat_ws(",", F.col("ids")).alias("source_record_id"),
            F.lit("BORR_FST_NM+BORR_LST_NM+BORR_DOB_DT").alias("column_name"),
            F.lit("DUPLICATE").alias("anomaly_type"),
            F.lit("LOW").alias("severity"),
            F.lit("Potential duplicate borrowers detected").alias("description"),
            F.concat_ws(",", F.col("ids")).alias("original_value"),
            F.lit(None).cast(StringType()).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
        anomalies.append(dupe_records)

    if anomalies:
        from functools import reduce
        return reduce(DataFrame.unionByName, anomalies)
    else:
        return spark.createDataFrame([], schema=StructType([]))


def run(spark: SparkSession) -> dict:
    """Main ingestion entry point. Returns row count summary."""
    print(f"[{RUN_ID}] Starting borrower ingestion...")

    # Read
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"[{RUN_ID}] Source rows: {source_count}")

    # Detect anomalies
    transformed_df = transform(source_df)
    anomaly_df = detect_anomalies(source_df, transformed_df, spark)
    anomaly_count = anomaly_df.count()
    print(f"[{RUN_ID}] Anomalies detected: {anomaly_count}")

    # Write anomalies
    if anomaly_count > 0:
        anomaly_df.write.mode("append").saveAsTable(DQ_LOG_TABLE)

    # Write to target (merge for idempotency)
    transformed_df.createOrReplaceTempView("borrowers_staging")
    spark.sql(f"""
        MERGE INTO {TARGET_TABLE} AS target
        USING borrowers_staging AS source
        ON target.external_id = source.external_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[{RUN_ID}] Target rows after merge: {target_count}")

    return {
        "run_id": RUN_ID,
        "source_count": source_count,
        "target_count": target_count,
        "anomaly_count": anomaly_count,
    }


# ---------------------------------------------------------------------------
# Entry point (for Databricks notebook or job)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW Borrower Ingestion").getOrCreate()
    result = run(spark)
    print(f"Ingestion complete: {result}")
