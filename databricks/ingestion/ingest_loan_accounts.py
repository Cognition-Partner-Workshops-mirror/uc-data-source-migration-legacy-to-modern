"""
Ingest legacy CDW_LN_ACCT into the modern loan_accounts Delta Lake table.

Source : CSV or Parquet export of CDW_LN_ACCT
Target : loan_warehouse.loan_accounts (Delta)

Transformations applied (per column_mappings.md):
  - Denormalized borrower columns (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) dropped
  - BORR_ID resolved to borrower_id via lookup against borrowers.external_id
  - PROD_CD resolved to product_id via lookup against loan_products.code
  - Comma-formatted amount strings → DecimalType
  - Date strings (MM/DD/YYYY) → DateType / TimestampType
  - LN_STAT_CD expanded: ACT → ACTIVE, CLO → CLOSED, DFT → DEFAULT, FRB → FORBEARANCE
  - PROP_TYP_CD expanded: SFR → Single Family, CND → Condominium, etc.
  - Null / malformed values are logged, never silently dropped
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from transforms import (
    LOAN_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_code,
    parse_amount,
    parse_date,
    parse_int,
    parse_timestamp,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LEGACY_SOURCE_PATH = "dbfs:/mnt/legacy_exports/CDW_LN_ACCT"
LEGACY_SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"


def read_legacy_loan_accounts(spark: SparkSession, path: str = LEGACY_SOURCE_PATH,
                              fmt: str = LEGACY_SOURCE_FORMAT) -> DataFrame:
    """Read the legacy loan accounts source file."""
    reader = spark.read.format(fmt)
    if fmt == "csv":
        reader = reader.option("header", "true").option("inferSchema", "false")
    return reader.load(path)


def resolve_borrower_ids(spark: SparkSession) -> DataFrame:
    """Load the borrower lookup table (external_id → id) from the already-ingested
    modern borrowers Delta table."""
    return spark.table("loan_warehouse.borrowers").select(
        F.col("id").alias("borrower_id"),
        F.col("external_id").alias("_borr_external_id"),
    )


def resolve_product_ids(spark: SparkSession) -> DataFrame:
    """Load the product lookup table (code → id) from the already-ingested
    modern loan_products Delta table."""
    return spark.table("loan_warehouse.loan_products").select(
        F.col("id").alias("product_id"),
        F.col("code").alias("_prod_code"),
    )


def transform_loan_accounts(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Apply all column mappings, FK resolution, and type conversions.

    Adds a _parse_errors column for per-row warnings.  Records whose FK
    cannot be resolved are kept (with NULL FK) and flagged — they are NOT
    silently dropped.
    """
    # Step 1: Apply scalar transformations (drop denormalized borrower columns)
    transformed = df.select(
        F.col("LN_ACCT_NBR").alias("account_number"),
        F.col("BORR_ID").alias("_borr_external_id"),       # temporary; for FK join
        F.col("PROD_CD").alias("_prod_code"),               # temporary; for FK join
        parse_amount(F.col("LN_ORIG_AMT")).alias("original_amount"),
        parse_amount(F.col("LN_CURR_BAL")).alias("current_balance"),
        parse_amount(F.col("LN_INT_RT"), precision=5, scale=3).alias("interest_rate"),
        parse_int(F.col("LN_TERM_MOS")).alias("term_months"),
        parse_amount(F.col("LN_PMT_AMT"), precision=10, scale=2).alias("monthly_payment"),
        parse_date(F.col("LN_ORIG_DT")).alias("origination_date"),
        parse_date(F.col("LN_MAT_DT")).alias("maturity_date"),
        parse_date(F.col("LN_1ST_PMT_DT")).alias("first_payment_date"),
        parse_date(F.col("LN_NXT_PMT_DT")).alias("next_payment_date"),
        expand_code(F.col("LN_STAT_CD"), LOAN_STATUS_MAP).alias("status"),
        parse_int(F.col("LN_DLQ_DAYS")).alias("delinquency_days"),
        parse_amount(F.col("LN_ESCROW_BAL"), precision=10, scale=2).alias("escrow_balance"),
        parse_amount(F.col("LN_LTV_PCT"), precision=5, scale=2).alias("ltv_percent"),
        F.col("PROP_ADDR_LN1").alias("property_address"),
        F.col("PROP_CTY_NM").alias("property_city"),
        F.col("PROP_ST_CD").alias("property_state"),
        F.col("PROP_ZIP_CD").alias("property_zip"),
        expand_code(F.col("PROP_TYP_CD"), PROPERTY_TYPE_MAP).alias("property_type"),
        parse_amount(F.col("PROP_APRS_VAL")).alias("appraised_value"),
        parse_timestamp(F.col("LN_CRET_DT")).alias("created_at"),
        parse_timestamp(F.col("LN_UPDT_DT")).alias("updated_at"),
    )

    # Step 2: Resolve foreign keys via left joins (preserves unmatched rows)
    borrower_lookup = resolve_borrower_ids(spark)
    product_lookup = resolve_product_ids(spark)

    transformed = (
        transformed
        .join(borrower_lookup, on="_borr_external_id", how="left")
        .join(product_lookup, on="_prod_code", how="left")
    )

    # Step 3: Build per-row error log
    error_checks = F.array_remove(
        F.array(
            F.when(F.col("account_number").isNull(), F.lit("LN_ACCT_NBR is null")),
            F.when(F.col("borrower_id").isNull(),
                   F.concat(F.lit("BORR_ID lookup failed for "), F.col("_borr_external_id"))),
            F.when(F.col("product_id").isNull(),
                   F.concat(F.lit("PROD_CD lookup failed for "), F.col("_prod_code"))),
            F.when(F.col("original_amount").isNull(), F.lit("LN_ORIG_AMT failed decimal parse")),
            F.when(F.col("current_balance").isNull(), F.lit("LN_CURR_BAL failed decimal parse")),
            F.when(F.col("origination_date").isNull(), F.lit("LN_ORIG_DT failed date parse")),
        ),
        None,
    )

    transformed = (
        transformed
        .withColumn("_parse_errors", error_checks)
        .drop("_borr_external_id", "_prod_code")
    )

    return transformed


def log_errors(df: DataFrame, spark: SparkSession) -> None:
    """Print and persist rows that had parse warnings."""
    error_rows = df.filter(F.size("_parse_errors") > 0)
    error_count = error_rows.count()
    if error_count > 0:
        print(f"[WARN] {error_count} loan account row(s) had parse warnings:")
        error_rows.select("account_number", "_parse_errors").show(truncate=False)
        error_rows.write.format("delta").mode("overwrite").saveAsTable(
            "loan_warehouse._loan_account_ingestion_errors"
        )
    else:
        print("[INFO] All loan account rows parsed successfully — no warnings.")


def write_loan_accounts(df: DataFrame) -> None:
    """Write clean loan account records to the target Delta table."""
    clean = df.drop("_parse_errors")
    clean.write.format("delta").mode("overwrite").saveAsTable(TARGET_TABLE)
    print(f"[INFO] Wrote {clean.count()} loan account records to {TARGET_TABLE}.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    spark = SparkSession.builder.appName("Ingest_LoanAccounts").getOrCreate()

    print("[INFO] Reading legacy CDW_LN_ACCT …")
    raw = read_legacy_loan_accounts(spark)
    source_count = raw.count()
    print(f"[INFO] Source row count: {source_count}")

    print("[INFO] Transforming loan account records …")
    transformed = transform_loan_accounts(raw, spark)

    log_errors(transformed, spark)
    write_loan_accounts(transformed)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[INFO] Target row count: {target_count}")
    if source_count != target_count:
        print(f"[ERROR] Row count mismatch! Source={source_count}, Target={target_count}")
    else:
        print("[INFO] Row count reconciliation passed.")


if __name__ == "__main__":
    main()
