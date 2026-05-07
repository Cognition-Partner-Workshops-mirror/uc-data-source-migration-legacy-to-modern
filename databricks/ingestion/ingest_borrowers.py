"""
Ingest borrowers from legacy CDW_BORR_MSTR into the modern ``borrowers`` Delta table.

Expected source: CSV or Parquet export of the CDW_BORR_MSTR table.

Usage (Databricks notebook or job):
    %run ./transforms
    # -- or --
    from ingestion.ingest_borrowers import run
    run(spark, source_path="dbfs:/mnt/legacy/cdw_borr_mstr/", source_format="csv")
"""

import logging

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DecimalType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from .transforms import (
    BORROWER_STATUS_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_timestamp,
    parse_int,
)

logger = logging.getLogger("ingestion.borrowers")

TARGET_TABLE = "loan_warehouse.borrowers"

# Explicit schema prevents Spark from guessing types on the all-VARCHAR source.
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


def read_source(spark: SparkSession, path: str, fmt: str = "csv") -> DataFrame:
    """Read the legacy CDW_BORR_MSTR export."""
    reader = spark.read.schema(LEGACY_SCHEMA)
    if fmt == "csv":
        return reader.option("header", "true").csv(path)
    elif fmt == "parquet":
        return reader.parquet(path)
    else:
        raise ValueError(f"Unsupported source format: {fmt}")


def transform(df: DataFrame) -> DataFrame:
    """Apply column mappings and type transformations.

    Rows with null BORR_ID or BORR_FST_NM are flagged but NOT dropped — they
    are written with ``_is_valid = false`` so the quality framework can report
    them.
    """
    transformed = df.select(
        F.col("BORR_ID").alias("external_id"),
        F.trim(F.col("BORR_FST_NM")).alias("first_name"),
        F.trim(F.col("BORR_LST_NM")).alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        parse_date("BORR_DOB_DT").alias("date_of_birth"),
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        parse_int("BORR_CRDT_SCR").alias("credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount("BORR_ANN_INCM").alias("annual_income"),
        parse_timestamp("BORR_CRET_DT").alias("created_at"),
        parse_timestamp("BORR_UPDT_DT").alias("updated_at"),
        expand_status("BORR_STAT_CD", BORROWER_STATUS_MAP, alias="status"),
    )

    # Add validation flag — do NOT drop bad rows
    transformed = transformed.withColumn(
        "_is_valid",
        F.col("external_id").isNotNull() & F.col("first_name").isNotNull(),
    )

    invalid_count = transformed.filter(~F.col("_is_valid")).count()
    if invalid_count > 0:
        logger.warning(
            "Borrower ingestion: %d rows have null external_id or first_name",
            invalid_count,
        )

    return transformed


def write_target(df: DataFrame, mode: str = "overwrite") -> None:
    """Write transformed borrowers to the Delta target table."""
    output = df.drop("_is_valid")
    (
        output.write
        .format("delta")
        .mode(mode)
        .option("mergeSchema", "true")
        .saveAsTable(TARGET_TABLE)
    )
    logger.info(
        "Wrote %d rows to %s (mode=%s)", output.count(), TARGET_TABLE, mode
    )


def run(
    spark: SparkSession,
    source_path: str,
    source_format: str = "csv",
    write_mode: str = "overwrite",
) -> DataFrame:
    """End-to-end ingestion pipeline for borrowers.

    Returns the transformed DataFrame for downstream validation.
    """
    logger.info("Starting borrower ingestion from %s (%s)", source_path, source_format)
    raw = read_source(spark, source_path, source_format)
    logger.info("Read %d raw borrower records", raw.count())

    result = transform(raw)
    write_target(result, mode=write_mode)
    return result
