"""
PySpark Ingestion Script: CDW_LN_ACCT -> loan_warehouse.loan_accounts

Reads legacy loan account data from CSV/Parquet source files, applies type
transformations, expands status codes, splits out denormalized borrower fields,
and writes to the modern Delta Lake loan_accounts table.

Key operations:
- Drops denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
- References borrower via BORR_ID (FK to borrowers table)
- Expands loan status codes (ACT, CLO, DFT, FRB)
- Expands property type codes (SFR, CND, MFR, TWN)
- Parses all date and amount strings to proper types

Usage:
    from databricks.ingestion.ingest_loan_accounts import ingest_loan_accounts
    ingest_loan_accounts(spark, source_path, target_table)
"""

import logging
from datetime import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from .transforms import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status,
    parse_amount,
    parse_date,
    parse_integer,
    parse_percent,
    parse_rate,
    parse_timestamp,
)

logger = logging.getLogger(__name__)


def read_legacy_loan_accounts(spark: SparkSession, source_path: str) -> DataFrame:
    """Read legacy CDW_LN_ACCT data from CSV or Parquet source."""
    if source_path.endswith(".parquet") or source_path.endswith(".parquet/"):
        df = spark.read.parquet(source_path)
    else:
        df = spark.read.option("header", "true").option("inferSchema", "false").csv(source_path)

    logger.info(f"Read {df.count()} rows from legacy loan accounts source: {source_path}")
    return df


def transform_loan_accounts(df: DataFrame) -> DataFrame:
    """
    Transform legacy CDW_LN_ACCT DataFrame to modern loan_accounts schema.

    Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) are
    intentionally dropped. The borrower relationship is maintained via BORR_ID
    which maps to the borrowers.external_id in the modern schema.

    Transformations:
    - LN_ACCT_NBR -> account_number (direct copy)
    - BORR_ID -> borrower_id (FK reference via external_id lookup)
    - PROD_CD -> product_code (direct copy, FK reference)
    - LN_ORIG_AMT -> original_amount (remove commas, parse -> DECIMAL(12,2))
    - LN_CURR_BAL -> current_balance (remove commas, parse -> DECIMAL(12,2))
    - LN_INT_RT -> interest_rate (parse -> DECIMAL(5,3))
    - LN_TERM_MOS -> term_months (parse -> INT)
    - LN_PMT_AMT -> monthly_payment (remove commas, parse -> DECIMAL(10,2))
    - LN_ORIG_DT -> origination_date (parse MM/DD/YYYY -> DATE)
    - LN_MAT_DT -> maturity_date (parse MM/DD/YYYY -> DATE)
    - LN_1ST_PMT_DT -> first_payment_date (parse MM/DD/YYYY -> DATE)
    - LN_NXT_PMT_DT -> next_payment_date (parse MM/DD/YYYY -> DATE)
    - LN_STAT_CD -> status (expand: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE)
    - LN_DLQ_DAYS -> delinquency_days (parse -> INT)
    - LN_ESCROW_BAL -> escrow_balance (remove commas, parse -> DECIMAL(10,2))
    - LN_LTV_PCT -> ltv_percent (parse -> DECIMAL(5,2))
    - PROP_ADDR_LN1 -> property_address (direct copy)
    - PROP_CTY_NM -> property_city (direct copy)
    - PROP_ST_CD -> property_state (direct copy)
    - PROP_ZIP_CD -> property_zip (direct copy)
    - PROP_TYP_CD -> property_type (expand: SFR->Single Family, etc.)
    - PROP_APRS_VAL -> appraised_value (remove commas, parse -> DECIMAL(12,2))
    - LN_CRET_DT -> created_at (parse MM/DD/YYYY -> TIMESTAMP)
    - LN_UPDT_DT -> updated_at (parse MM/DD/YYYY -> TIMESTAMP)
    """
    transformed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("borrower_id"),
        F.col("PROD_CD").alias("product_code"),
        parse_amount("LN_ORIG_AMT", 12, 2).alias("original_amount"),
        parse_amount("LN_CURR_BAL", 12, 2).alias("current_balance"),
        parse_rate("LN_INT_RT").alias("interest_rate"),
        parse_integer("LN_TERM_MOS").alias("term_months"),
        parse_amount("LN_PMT_AMT", 10, 2).alias("monthly_payment"),
        parse_date("LN_ORIG_DT").alias("origination_date"),
        parse_date("LN_MAT_DT").alias("maturity_date"),
        parse_date("LN_1ST_PMT_DT").alias("first_payment_date"),
        parse_date("LN_NXT_PMT_DT").alias("next_payment_date"),
        expand_status("LN_STAT_CD", LOAN_STATUS_MAP).alias("status"),
        parse_integer("LN_DLQ_DAYS").alias("delinquency_days"),
        parse_amount("LN_ESCROW_BAL", 10, 2).alias("escrow_balance"),
        parse_percent("LN_LTV_PCT").alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_status("PROP_TYP_CD", PROPERTY_TYPE_MAP).alias("property_type"),
        parse_amount("PROP_APRS_VAL", 12, 2).alias("appraised_value"),
        parse_timestamp("LN_CRET_DT").alias("created_at"),
        parse_timestamp("LN_UPDT_DT").alias("updated_at"),
    )

    return transformed


def validate_loan_accounts(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Validate transformed loan account records.
    Returns (valid_df, rejected_df) tuple.

    Rejection criteria:
    - account_number is NULL
    - borrower_id is NULL
    - original_amount is NULL or <= 0
    - current_balance is NULL
    - interest_rate is NULL
    - origination_date is NULL
    - maturity_date is NULL
    """
    required_conditions = (
        F.col("account_number").isNotNull()
        & F.col("borrower_id").isNotNull()
        & F.col("original_amount").isNotNull()
        & (F.col("original_amount") > 0)
        & F.col("current_balance").isNotNull()
        & F.col("interest_rate").isNotNull()
        & F.col("origination_date").isNotNull()
        & F.col("maturity_date").isNotNull()
    )

    valid = df.filter(required_conditions)

    rejected = df.filter(~required_conditions).withColumn(
        "_rejection_reason",
        F.when(F.col("account_number").isNull(), F.lit("Missing account_number"))
        .when(F.col("borrower_id").isNull(), F.lit("Missing borrower_id"))
        .when(F.col("original_amount").isNull(), F.lit("Missing original_amount"))
        .when(F.col("original_amount") <= 0, F.lit("Invalid original_amount (<=0)"))
        .when(F.col("current_balance").isNull(), F.lit("Missing current_balance"))
        .when(F.col("interest_rate").isNull(), F.lit("Missing interest_rate"))
        .when(F.col("origination_date").isNull(), F.lit("Missing origination_date"))
        .when(F.col("maturity_date").isNull(), F.lit("Missing maturity_date"))
        .otherwise(F.lit("Unknown validation failure")),
    )

    rejected_count = rejected.count()
    if rejected_count > 0:
        logger.warning(f"Rejected {rejected_count} loan account records due to validation failures")

    return valid, rejected


def ingest_loan_accounts(
    spark: SparkSession,
    source_path: str,
    target_table: str = "loan_warehouse.loan_accounts",
    rejected_path: str = None,
    mode: str = "append",
) -> dict:
    """
    End-to-end ingestion pipeline for loan accounts.

    Args:
        spark: Active SparkSession
        source_path: Path to legacy CSV/Parquet source files
        target_table: Target Delta Lake table name
        rejected_path: Optional path to write rejected records
        mode: Write mode ('append' or 'overwrite')

    Returns:
        Dictionary with ingestion metrics
    """
    start_time = datetime.now()
    metrics = {
        "table": target_table,
        "source_path": source_path,
        "start_time": start_time.isoformat(),
    }

    # Read
    raw_df = read_legacy_loan_accounts(spark, source_path)
    metrics["source_count"] = raw_df.count()

    # Transform
    transformed_df = transform_loan_accounts(raw_df)

    # Validate
    valid_df, rejected_df = validate_loan_accounts(transformed_df)
    metrics["valid_count"] = valid_df.count()
    metrics["rejected_count"] = rejected_df.count()

    # Write valid records to Delta Lake
    valid_df.write.format("delta").mode(mode).saveAsTable(target_table)
    logger.info(f"Wrote {metrics['valid_count']} records to {target_table}")

    # Write rejected records if path provided
    if rejected_path and metrics["rejected_count"] > 0:
        rejected_df.write.format("delta").mode("append").save(rejected_path)
        logger.info(f"Wrote {metrics['rejected_count']} rejected records to {rejected_path}")

    metrics["end_time"] = datetime.now().isoformat()
    metrics["status"] = "SUCCESS" if metrics["rejected_count"] == 0 else "COMPLETED_WITH_REJECTS"

    logger.info(f"Loan accounts ingestion complete: {metrics}")
    return metrics


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("CDW_LoanAccounts_Ingestion").getOrCreate()

    SOURCE_PATH = spark.conf.get("migration.loan_accounts.source_path", "/mnt/legacy/cdw_ln_acct/")
    TARGET_TABLE = spark.conf.get("migration.loan_accounts.target_table", "loan_warehouse.loan_accounts")
    REJECTED_PATH = spark.conf.get("migration.loan_accounts.rejected_path", "/mnt/migration/rejected/loan_accounts/")
    WRITE_MODE = spark.conf.get("migration.write_mode", "overwrite")

    result = ingest_loan_accounts(spark, SOURCE_PATH, TARGET_TABLE, REJECTED_PATH, WRITE_MODE)
    print(f"Ingestion Result: {result}")
