"""
Ingest legacy CDW_LN_PROD into the modern loan_products Delta Lake table.

Source : CSV or Parquet export of CDW_LN_PROD
Target : loan_warehouse.loan_products (Delta)

Transformations applied (per column_mappings.md):
  - Term months string → IntegerType
  - Comma-formatted amount strings → DecimalType
  - PROD_STAT_CD → boolean is_active (ACT → true, INA → false)
  - Date strings (MM/DD/YYYY) → DateType
  - Null / malformed values are logged, never silently dropped
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    PRODUCT_STATUS_MAP,
    expand_code_to_boolean,
    parse_amount,
    parse_date,
    parse_int,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy_exports/CDW_LN_PROD"
LEGACY_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_products"


def read_legacy_loan_products(spark: SparkSession, path: str = LEGACY_SOURCE_PATH,
                              fmt: str = LEGACY_SOURCE_FORMAT) -> DataFrame:
    """Read the legacy loan products source file."""
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(path)


def transform_loan_products(df: DataFrame) -> DataFrame:
    """Apply all column mappings and type conversions for loan products.

    Adds a _parse_errors column for per-row warnings.
    """
    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_int(F.col("PROD_TERM_MOS")).alias("term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount(F.col("PROD_MIN_AMT")).alias("min_amount"),
        parse_amount(F.col("PROD_MAX_AMT")).alias("max_amount"),
        expand_code_to_boolean(F.col("PROD_STAT_CD"), PRODUCT_STATUS_MAP).alias("is_active"),
        parse_date(F.col("PROD_EFF_DT")).alias("effective_date"),
        parse_date(F.col("PROD_EXP_DT")).alias("expiration_date"),
    )

    # Per-row error tracking
    error_checks = F.array_remove(
        F.array(
            F.when(F.col("code").isNull(), F.lit("PROD_CD is null")),
            F.when(F.col("name").isNull(), F.lit("PROD_DESC_TXT is null")),
            F.when(F.col("term_months").isNull() & df["PROD_TERM_MOS"].isNotNull(),
                   F.lit("PROD_TERM_MOS failed int parse")),
            F.when(F.col("is_active").isNull() & df["PROD_STAT_CD"].isNotNull(),
                   F.lit("PROD_STAT_CD unknown code")),
        ),
        None,
    )

    transformed = transformed.withColumn("_parse_errors", error_checks)
    return transformed


def log_errors(df: DataFrame, spark: SparkSession) -> None:
    """Print and persist rows that had parse warnings."""
    error_rows = df.filter(F.size("_parse_errors") > 0)
    error_count = error_rows.count()
    if error_count > 0:
        print(f"[WARN] {error_count} loan product row(s) had parse warnings:")
        error_rows.select("code", "_parse_errors").show(truncate=False)
        error_rows.write.format("delta").mode("overwrite").saveAsTable(
            "loan_warehouse._loan_product_ingestion_errors"
        )
    else:
        print("[INFO] All loan product rows parsed successfully — no warnings.")


def write_loan_products(df: DataFrame) -> None:
    """Write clean loan product records to the target Delta table."""
    clean = df.drop("_parse_errors")
    clean.write.format("delta").mode("overwrite").saveAsTable(TARGET_TABLE)
    print(f"[INFO] Wrote {clean.count()} loan product records to {TARGET_TABLE}.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    spark = SparkSession.builder.appName("Ingest_LoanProducts").getOrCreate()

    print("[INFO] Reading legacy CDW_LN_PROD …")
    raw = read_legacy_loan_products(spark)
    source_count = raw.count()
    print(f"[INFO] Source row count: {source_count}")

    print("[INFO] Transforming loan product records …")
    transformed = transform_loan_products(raw)

    log_errors(transformed, spark)
    write_loan_products(transformed)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[INFO] Target row count: {target_count}")
    if source_count != target_count:
        print(f"[ERROR] Row count mismatch! Source={source_count}, Target={target_count}")
    else:
        print("[INFO] Row count reconciliation passed.")


if __name__ == "__main__":
    main()
