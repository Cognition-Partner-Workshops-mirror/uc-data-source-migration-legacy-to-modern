"""
Ingestion script for CDW_LN_PROD -> loan_warehouse.loan_products

Reads legacy loan product data from CSV/Parquet source, applies transformations:
- Date parsing (MM/DD/YYYY -> DATE)
- Amount parsing (comma-formatted -> DECIMAL)
- Integer parsing (term months)
- Status to boolean conversion (ACT -> true, INA -> false)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructField,
    StructType,
    StringType,
)

from transformations import (
    add_ingestion_metadata,
    expand_boolean_status,
    flag_parse_errors,
    log_rejected_records,
    parse_amount_column,
    parse_date_column,
    parse_integer_column,
)


LEGACY_LOAN_PRODUCT_SCHEMA = StructType([
    StructField("PROD_CD", StringType(), False),
    StructField("PROD_DESC_TXT", StringType(), True),
    StructField("PROD_TYP_CD", StringType(), True),
    StructField("PROD_TERM_MOS", StringType(), True),
    StructField("PROD_RT_TYP", StringType(), True),
    StructField("PROD_MIN_AMT", StringType(), True),
    StructField("PROD_MAX_AMT", StringType(), True),
    StructField("PROD_STAT_CD", StringType(), True),
    StructField("PROD_EFF_DT", StringType(), True),
    StructField("PROD_EXP_DT", StringType(), True),
])


def read_legacy_loan_products(spark: SparkSession, source_path: str) -> DataFrame:
    """Read legacy loan product data from CSV or Parquet source."""
    if source_path.endswith(".parquet") or source_path.endswith("/parquet"):
        return spark.read.schema(LEGACY_LOAN_PRODUCT_SCHEMA).parquet(source_path)

    return (
        spark.read
        .schema(LEGACY_LOAN_PRODUCT_SCHEMA)
        .option("header", "true")
        .option("quote", '"')
        .option("escape", '"')
        .csv(source_path)
    )


def transform_loan_products(df: DataFrame) -> DataFrame:
    """
    Transform legacy loan product data to modern schema.

    Transformations:
    1. Rename cryptic columns to meaningful names
    2. Parse term months to integer
    3. Parse min/max amounts to decimal
    4. Convert status code to boolean is_active
    5. Parse effective/expiration dates
    """
    transformed = df.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_integer_column("PROD_TERM_MOS", "term_months"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount_column("PROD_MIN_AMT", 12, 2, "min_amount"),
        parse_amount_column("PROD_MAX_AMT", 12, 2, "max_amount"),
        expand_boolean_status("PROD_STAT_CD", "is_active"),
        parse_date_column("PROD_EFF_DT", "effective_date"),
        parse_date_column("PROD_EXP_DT", "expiration_date"),
        # Keep raw values for error detection
        F.col("PROD_TERM_MOS").alias("_raw_term"),
        F.col("PROD_MIN_AMT").alias("_raw_min_amt"),
        F.col("PROD_MAX_AMT").alias("_raw_max_amt"),
        F.col("PROD_EFF_DT").alias("_raw_eff_dt"),
    )

    transformed = flag_parse_errors(transformed, "_raw_term", "term_months", "_term_error")
    transformed = flag_parse_errors(transformed, "_raw_min_amt", "min_amount", "_min_amt_error")
    transformed = flag_parse_errors(transformed, "_raw_max_amt", "max_amount", "_max_amt_error")
    transformed = flag_parse_errors(transformed, "_raw_eff_dt", "effective_date", "_eff_dt_error")

    return transformed


def write_loan_products(
    df: DataFrame,
    target_table: str,
    rejection_path: str,
    mode: str = "overwrite",
) -> dict:
    """Write transformed loan product data to Delta Lake."""
    error_columns = ["_term_error", "_min_amt_error", "_max_amt_error", "_eff_dt_error"]
    total_count = df.count()
    rejected_count = log_rejected_records(df, error_columns, "loan_products", rejection_path)

    clean_df = df.drop(
        "_raw_term", "_raw_min_amt", "_raw_max_amt", "_raw_eff_dt",
        "_term_error", "_min_amt_error", "_max_amt_error", "_eff_dt_error",
    )
    clean_df = add_ingestion_metadata(clean_df, "CDW_LN_PROD")

    clean_df.write.mode(mode).format("delta").saveAsTable(target_table)

    stats = {
        "table": target_table,
        "source_count": total_count,
        "loaded_count": total_count,
        "rejected_count": rejected_count,
        "rejection_rate": f"{(rejected_count / max(total_count, 1)) * 100:.2f}%",
    }
    print(f"[INFO] Loan products ingestion complete: {stats}")
    return stats


def run(spark: SparkSession, config: dict) -> dict:
    """Main entry point for loan product ingestion."""
    source_path = config["source_path"]
    target_table = config.get("target_table", "loan_warehouse.loan_products")
    rejection_path = config.get("rejection_path", "/mnt/data/rejections")
    mode = config.get("mode", "overwrite")

    print(f"[INFO] Starting loan products ingestion from: {source_path}")
    raw_df = read_legacy_loan_products(spark, source_path)
    print(f"[INFO] Read {raw_df.count()} records from source")

    transformed_df = transform_loan_products(raw_df)
    return write_loan_products(transformed_df, target_table, rejection_path, mode)
