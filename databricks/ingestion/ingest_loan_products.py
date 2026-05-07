"""
Ingestion script: CDW_LN_PROD -> loan_warehouse.loan_products

Reads loan product data from the CSV/Parquet landing zone, applies type
transformations, maps status to boolean, adds lineage metadata, and writes
to the loan_products Delta table.
"""

import argparse

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from transform_utils import (
    PRODUCT_STATUS_MAP,
    add_error_summary,
    add_lineage_columns,
    expand_status_flag,
    log_parse_errors,
    parse_amount,
    parse_amount_flag,
    parse_date,
    parse_date_flag,
    parse_integer,
    parse_integer_flag,
    strip_error_columns,
)

DEFAULT_INPUT = "/mnt/landing/cdw/CDW_LN_PROD"
DEFAULT_OUTPUT = "loan_warehouse.loan_products"


def ingest_loan_products(
    spark: SparkSession,
    input_path: str = DEFAULT_INPUT,
    output_table: str = DEFAULT_OUTPUT,
) -> None:
    """Read, transform, and write loan product data."""

    raw = spark.read.format("csv").option("header", "true").load(input_path)

    # Build is_active boolean from PROD_STAT_CD
    is_active_expr = (
        F.when(F.col("PROD_STAT_CD") == "ACT", F.lit(True))
        .when(F.col("PROD_STAT_CD") == "INA", F.lit(False))
        .otherwise(F.lit(None))
        .alias("is_active")
    )

    transformed = raw.select(
        F.col("PROD_CD").alias("code"),
        F.col("PROD_DESC_TXT").alias("name"),
        F.col("PROD_TYP_CD").alias("type"),
        parse_integer("PROD_TERM_MOS", "term_months"),
        parse_integer_flag("PROD_TERM_MOS"),
        F.col("PROD_RT_TYP").alias("rate_type"),
        parse_amount("PROD_MIN_AMT", 12, 2, "min_amount"),
        parse_amount_flag("PROD_MIN_AMT"),
        parse_amount("PROD_MAX_AMT", 12, 2, "max_amount"),
        parse_amount_flag("PROD_MAX_AMT"),
        is_active_expr,
        expand_status_flag("PROD_STAT_CD", PRODUCT_STATUS_MAP),
        parse_date("PROD_EFF_DT", "effective_date"),
        parse_date_flag("PROD_EFF_DT"),
        parse_date("PROD_EXP_DT", "expiration_date"),
        parse_date_flag("PROD_EXP_DT"),
    )

    transformed = add_error_summary(transformed)
    log_parse_errors(transformed, "loan_products")
    transformed = add_lineage_columns(transformed)
    transformed = strip_error_columns(transformed)

    transformed.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(output_table)

    print(
        f"[loan_products] Wrote {transformed.count()} rows to {output_table}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_PROD")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input path")
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help="Output Delta table"
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName(
        "CDW_Migration_LoanProducts"
    ).getOrCreate()
    ingest_loan_products(spark, args.input, args.output)
    spark.stop()
