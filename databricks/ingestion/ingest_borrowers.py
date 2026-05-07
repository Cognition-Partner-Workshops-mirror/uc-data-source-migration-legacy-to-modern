"""
Ingestion script: CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads borrower data from the CSV/Parquet landing zone, applies type
transformations, expands status codes, adds lineage metadata, and writes
to the borrowers Delta table.
"""

import argparse

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from transform_utils import (
    BORROWER_STATUS_MAP,
    add_error_summary,
    add_lineage_columns,
    expand_status,
    expand_status_flag,
    log_parse_errors,
    parse_amount,
    parse_amount_flag,
    parse_date,
    parse_date_flag,
    parse_integer,
    parse_integer_flag,
    parse_timestamp,
    parse_timestamp_flag,
    strip_error_columns,
)

DEFAULT_INPUT = "/mnt/landing/cdw/CDW_BORR_MSTR"
DEFAULT_OUTPUT = "loan_warehouse.borrowers"


def ingest_borrowers(
    spark: SparkSession,
    input_path: str = DEFAULT_INPUT,
    output_table: str = DEFAULT_OUTPUT,
) -> None:
    """Read, transform, and write borrower data."""

    raw = spark.read.format("csv").option("header", "true").load(input_path)

    transformed = raw.select(
        # Direct copy columns
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        # Parsed columns
        parse_date("BORR_DOB_DT", "date_of_birth"),
        parse_date_flag("BORR_DOB_DT"),
        # Address
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        # Contact
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        # Numeric conversions
        parse_integer("BORR_CRDT_SCR", "credit_score"),
        parse_integer_flag("BORR_CRDT_SCR"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount("BORR_ANN_INCM", 12, 2, "annual_income"),
        parse_amount_flag("BORR_ANN_INCM"),
        # Status expansion
        expand_status("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),
        expand_status_flag("BORR_STAT_CD", BORROWER_STATUS_MAP),
        # Timestamps
        parse_timestamp("BORR_CRET_DT", "created_at"),
        parse_timestamp_flag("BORR_CRET_DT"),
        parse_timestamp("BORR_UPDT_DT", "updated_at"),
        parse_timestamp_flag("BORR_UPDT_DT"),
    )

    # Drop BORR_REC_TYP (not needed in modern schema)

    transformed = add_error_summary(transformed)
    log_parse_errors(transformed, "borrowers")
    transformed = add_lineage_columns(transformed)
    transformed = strip_error_columns(transformed)

    transformed.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(output_table)

    print(f"[borrowers] Wrote {transformed.count()} rows to {output_table}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_BORR_MSTR")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input path")
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help="Output Delta table"
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName(
        "CDW_Migration_Borrowers"
    ).getOrCreate()
    ingest_borrowers(spark, args.input, args.output)
    spark.stop()
