"""
Ingestion script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads loan account data from the CSV/Parquet landing zone, drops
denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4),
applies type transformations, expands status and property type codes,
derives the origination_year partition key, adds lineage metadata, and
writes to the loan_accounts Delta table.
"""

import argparse

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from transform_utils import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
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

DEFAULT_INPUT = "/mnt/landing/cdw/CDW_LN_ACCT"
DEFAULT_OUTPUT = "loan_warehouse.loan_accounts"


def ingest_loan_accounts(
    spark: SparkSession,
    input_path: str = DEFAULT_INPUT,
    output_table: str = DEFAULT_OUTPUT,
) -> None:
    """Read, transform, and write loan account data."""

    raw = spark.read.format("csv").option("header", "true").load(input_path)

    # Denormalized borrower columns are explicitly dropped
    # (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)

    transformed = raw.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        # FK columns — use string-based natural keys for Delta Lake
        F.col("BORR_ID").alias("borrower_id"),
        F.col("PROD_CD").alias("product_code"),
        # Amounts
        parse_amount("LN_ORIG_AMT", 12, 2, "original_amount"),
        parse_amount_flag("LN_ORIG_AMT"),
        parse_amount("LN_CURR_BAL", 12, 2, "current_balance"),
        parse_amount_flag("LN_CURR_BAL"),
        # Rate
        F.col("LN_INT_RT").cast("decimal(5,3)").alias("interest_rate"),
        F.when(
            F.col("LN_INT_RT").isNotNull()
            & F.col("LN_INT_RT").cast("decimal(5,3)").isNull(),
            F.lit(True),
        )
        .otherwise(F.lit(False))
        .alias("_err_LN_INT_RT"),
        # Integer fields
        parse_integer("LN_TERM_MOS", "term_months"),
        parse_integer_flag("LN_TERM_MOS"),
        parse_amount("LN_PMT_AMT", 10, 2, "monthly_payment"),
        parse_amount_flag("LN_PMT_AMT"),
        # Date fields
        parse_date("LN_ORIG_DT", "origination_date"),
        parse_date_flag("LN_ORIG_DT"),
        parse_date("LN_MAT_DT", "maturity_date"),
        parse_date_flag("LN_MAT_DT"),
        parse_date("LN_1ST_PMT_DT", "first_payment_date"),
        parse_date_flag("LN_1ST_PMT_DT"),
        parse_date("LN_NXT_PMT_DT", "next_payment_date"),
        parse_date_flag("LN_NXT_PMT_DT"),
        # Status expansion
        expand_status("LN_STAT_CD", LOAN_STATUS_MAP, "status"),
        expand_status_flag("LN_STAT_CD", LOAN_STATUS_MAP),
        # Delinquency
        parse_integer("LN_DLQ_DAYS", "delinquency_days"),
        parse_integer_flag("LN_DLQ_DAYS"),
        # Escrow
        parse_amount("LN_ESCROW_BAL", 10, 2, "escrow_balance"),
        parse_amount_flag("LN_ESCROW_BAL"),
        # LTV
        F.col("LN_LTV_PCT").cast("decimal(5,2)").alias("ltv_percent"),
        F.when(
            F.col("LN_LTV_PCT").isNotNull()
            & F.col("LN_LTV_PCT").cast("decimal(5,2)").isNull(),
            F.lit(True),
        )
        .otherwise(F.lit(False))
        .alias("_err_LN_LTV_PCT"),
        # Property fields
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_status("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
        expand_status_flag("PROP_TYP_CD", PROPERTY_TYPE_MAP),
        # Appraised value
        parse_amount("PROP_APRS_VAL", 12, 2, "appraised_value"),
        parse_amount_flag("PROP_APRS_VAL"),
        # Timestamps
        parse_timestamp("LN_CRET_DT", "created_at"),
        parse_timestamp_flag("LN_CRET_DT"),
        parse_timestamp("LN_UPDT_DT", "updated_at"),
        parse_timestamp_flag("LN_UPDT_DT"),
    )

    # Derive partition key
    transformed = transformed.withColumn(
        "origination_year", F.year(F.col("origination_date"))
    )

    transformed = add_error_summary(transformed)
    log_parse_errors(transformed, "loan_accounts")
    transformed = add_lineage_columns(transformed)
    transformed = strip_error_columns(transformed)

    transformed.write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(output_table)

    print(
        f"[loan_accounts] Wrote {transformed.count()} rows to {output_table}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CDW_LN_ACCT")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input path")
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help="Output Delta table"
    )
    args = parser.parse_args()

    spark = SparkSession.builder.appName(
        "CDW_Migration_LoanAccounts"
    ).getOrCreate()
    ingest_loan_accounts(spark, args.input, args.output)
    spark.stop()
