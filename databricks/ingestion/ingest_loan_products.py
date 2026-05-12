"""
PySpark ingestion script: CDW_LN_PROD → loan_warehouse.loan_products

Reads from a legacy CSV/Parquet extract of the CDW_LN_PROD table and transforms
all VARCHAR columns into proper Spark SQL types per column_mappings.md.
PROD_STAT_CD is converted to a boolean is_active flag (ACT→true, INA→false).

Usage (Databricks notebook cell):
    %run ./transform_utils
    %run ./ingest_loan_products

Or as a standalone script:
    spark-submit --master local[*] ingest_loan_products.py \
        --source-path /mnt/landing/cdw_ln_prod/ \
        --source-format csv \
        --target-table loan_warehouse.loan_products
"""

import argparse
import logging
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transform_utils import (
    parse_date_mmddyyyy,
    parse_decimal_amount,
    parse_integer,
    expand_status_code,
    log_unmapped_codes,
    PRODUCT_STATUS_MAP,
)

logger = logging.getLogger("cdw_migration.loan_products")
logger.setLevel(logging.INFO)


def read_legacy_loan_products(spark: SparkSession, source_path: str,
                              source_format: str = "csv") -> DataFrame:
    """
    Read the legacy CDW_LN_PROD extract from the landing zone.
    """
    if source_format == "csv":
        df = (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .option("nullValue", "")
            .csv(source_path)
        )
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source format: {source_format}")

    logger.info("Read %d rows from legacy CDW_LN_PROD at %s", df.count(), source_path)
    return df


def transform_loan_products(df: DataFrame) -> DataFrame:
    """
    Transform legacy CDW_LN_PROD columns to the modern loan_products schema.

    Transformations applied:
      - PROD_TERM_MOS:  VARCHAR → IntegerType
      - PROD_MIN_AMT:   comma-formatted string → DECIMAL(12,2)
      - PROD_MAX_AMT:   comma-formatted string → DECIMAL(12,2)
      - PROD_STAT_CD:   abbreviation → boolean (ACT→true, INA→false)
      - PROD_EFF_DT:    MM/DD/YYYY string → DateType
      - PROD_EXP_DT:    MM/DD/YYYY string → DateType
    """
    transformed = (
        df
        # Direct-copy string fields
        .withColumn("code", F.col("PROD_CD"))
        .withColumn("name", F.col("PROD_DESC_TXT"))
        .withColumn("type", F.col("PROD_TYP_CD"))
        .withColumn("rate_type", F.col("PROD_RT_TYP"))

        # Type conversions
        .withColumn("term_months", parse_integer("PROD_TERM_MOS"))
        .withColumn("min_amount", parse_decimal_amount("PROD_MIN_AMT"))
        .withColumn("max_amount", parse_decimal_amount("PROD_MAX_AMT"))

        # Boolean status conversion (ACT→true, INA→false)
        .withColumn("is_active",
                     F.when(F.upper(F.col("PROD_STAT_CD")) == "ACT", F.lit(True))
                      .when(F.upper(F.col("PROD_STAT_CD")) == "INA", F.lit(False))
                      .otherwise(F.lit(None)))

        # Date conversions
        .withColumn("effective_date", parse_date_mmddyyyy("PROD_EFF_DT"))
        .withColumn("expiration_date", parse_date_mmddyyyy("PROD_EXP_DT"))
    )

    modern_columns = [
        "code", "name", "type", "term_months", "rate_type",
        "min_amount", "max_amount", "is_active",
        "effective_date", "expiration_date",
    ]
    return transformed.select(modern_columns)


def write_loan_products(df: DataFrame,
                        target_table: str = "loan_warehouse.loan_products") -> None:
    """
    Write transformed loan product data to the Delta Lake target table.
    Uses merge (upsert) on product code for idempotent reruns.
    """
    row_count = df.count()
    logger.info("Writing %d loan product records to %s", row_count, target_table)

    df.createOrReplaceTempView("loan_products_staging")

    spark = df.sparkSession
    spark.sql(f"""
        MERGE INTO {target_table} AS target
        USING loan_products_staging AS source
        ON target.code = source.code
        WHEN MATCHED THEN UPDATE SET
            name            = source.name,
            type            = source.type,
            term_months     = source.term_months,
            rate_type       = source.rate_type,
            min_amount      = source.min_amount,
            max_amount      = source.max_amount,
            is_active       = source.is_active,
            effective_date  = source.effective_date,
            expiration_date = source.expiration_date,
            _migration_ts   = current_timestamp()
        WHEN NOT MATCHED THEN INSERT (
            code, name, type, term_months, rate_type,
            min_amount, max_amount, is_active,
            effective_date, expiration_date
        ) VALUES (
            source.code, source.name, source.type, source.term_months, source.rate_type,
            source.min_amount, source.max_amount, source.is_active,
            source.effective_date, source.expiration_date
        )
    """)
    logger.info("Loan product ingestion complete: %d records processed", row_count)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest CDW_LN_PROD to loan_warehouse.loan_products"
    )
    parser.add_argument("--source-path", required=True, help="Path to legacy CSV/Parquet extract")
    parser.add_argument("--source-format", default="csv", choices=["csv", "parquet"])
    parser.add_argument("--target-table", default="loan_warehouse.loan_products")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CDW_LoanProduct_Ingestion").getOrCreate()

    raw_df = read_legacy_loan_products(spark, args.source_path, args.source_format)
    transformed_df = transform_loan_products(raw_df)
    write_loan_products(transformed_df, args.target_table)

    spark.stop()
