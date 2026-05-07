"""
PySpark Ingestion Script: CDW_LN_ACCT → loan_warehouse.loan_accounts

Reads from legacy loan account source and transforms into the modern
normalized loan_accounts table. Denormalized borrower fields are dropped
and replaced with FK lookups.

Anomalies handled:
  - ANO-001: Numeric amounts as strings with commas
  - ANO-002: Dates in MM/DD/YYYY string format
  - ANO-003: Orphaned FK references (borrower, product)
  - ANO-004: Status code expansion
  - ANO-005: Denormalized borrower data inconsistency
  - ANO-009: Delinquency-status inconsistency
  - ANO-010: LTV percent mismatch
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DecimalType, IntegerType
)
from functools import reduce
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SOURCE_PATH = "/mnt/legacy-cdw/CDW_LN_ACCT"
SOURCE_FORMAT = "csv"
TARGET_TABLE = "loan_warehouse.loan_accounts"
BORROWER_TABLE = "loan_warehouse.borrowers"
PRODUCT_TABLE = "loan_warehouse.loan_products"
DQ_LOG_TABLE = "loan_warehouse.data_quality_log"
RUN_ID = f"loan_acct_ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

LEGACY_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
    StructField("BORR_SSN_LST4", StringType(), True),
    StructField("PROD_CD", StringType(), True),
    StructField("LN_ORIG_AMT", StringType(), True),
    StructField("LN_CURR_BAL", StringType(), True),
    StructField("LN_INT_RT", StringType(), True),
    StructField("LN_TERM_MOS", StringType(), True),
    StructField("LN_PMT_AMT", StringType(), True),
    StructField("LN_ORIG_DT", StringType(), True),
    StructField("LN_MAT_DT", StringType(), True),
    StructField("LN_1ST_PMT_DT", StringType(), True),
    StructField("LN_NXT_PMT_DT", StringType(), True),
    StructField("LN_STAT_CD", StringType(), True),
    StructField("LN_DLQ_DAYS", StringType(), True),
    StructField("LN_ESCROW_BAL", StringType(), True),
    StructField("LN_LTV_PCT", StringType(), True),
    StructField("PROP_ADDR_LN1", StringType(), True),
    StructField("PROP_CTY_NM", StringType(), True),
    StructField("PROP_ST_CD", StringType(), True),
    StructField("PROP_ZIP_CD", StringType(), True),
    StructField("PROP_TYP_CD", StringType(), True),
    StructField("PROP_APRS_VAL", StringType(), True),
    StructField("LN_CRET_DT", StringType(), True),
    StructField("LN_UPDT_DT", StringType(), True),
])

STATUS_MAP = {"ACT": "ACTIVE", "CLO": "CLOSED", "DFT": "DEFAULT", "FRB": "FORBEARANCE"}
PROPERTY_TYPE_MAP = {
    "SFR": "Single Family", "CND": "Condominium",
    "MFR": "Multi-Family", "TWN": "Townhouse",
}


def read_source(spark: SparkSession) -> DataFrame:
    if SOURCE_FORMAT == "csv":
        return (
            spark.read.schema(LEGACY_SCHEMA)
            .option("header", "true").csv(SOURCE_PATH)
        )
    return spark.read.parquet(SOURCE_PATH)


def parse_legacy_date(col_name: str, alias: str) -> F.Column:
    return F.coalesce(
        F.to_date(F.col(col_name), "MM/dd/yyyy"),
        F.to_date(F.col(col_name), "yyyy-MM-dd"),
    ).alias(alias)


def parse_legacy_amount(col_name: str, alias: str) -> F.Column:
    cleaned = F.regexp_replace(F.col(col_name), r"[$,\s]", "")
    return cleaned.cast(DecimalType(12, 2)).alias(alias)


def expand_status(col_name: str, mapping: dict, alias: str) -> F.Column:
    mapping_expr = F.create_map(
        *[item for kv in mapping.items() for item in (F.lit(kv[0]), F.lit(kv[1]))]
    )
    upper_col = F.upper(F.trim(F.col(col_name)))
    return F.coalesce(mapping_expr[upper_col], upper_col).alias(alias)


def transform(df: DataFrame, spark: SparkSession) -> DataFrame:
    """Transform legacy loan accounts with FK resolution."""
    borrowers = spark.table(BORROWER_TABLE).select(
        F.col("borrower_id"), F.col("external_id").alias("borr_ext_id")
    )
    products = spark.table(PRODUCT_TABLE).select(
        F.col("product_id"), F.col("code").alias("prod_code")
    )

    return (
        df
        .join(borrowers, df["BORR_ID"] == borrowers["borr_ext_id"], "left")
        .join(products, df["PROD_CD"] == products["prod_code"], "left")
        .select(
            F.col("LN_ACCT_NBR").alias("account_number"),
            F.col("borrower_id"),
            F.col("product_id"),
            parse_legacy_amount("LN_ORIG_AMT", "original_amount"),
            parse_legacy_amount("LN_CURR_BAL", "current_balance"),
            F.col("LN_INT_RT").cast(DecimalType(5, 3)).alias("interest_rate"),
            F.col("LN_TERM_MOS").cast(IntegerType()).alias("term_months"),
            parse_legacy_amount("LN_PMT_AMT", "monthly_payment"),
            parse_legacy_date("LN_ORIG_DT", "origination_date"),
            parse_legacy_date("LN_MAT_DT", "maturity_date"),
            parse_legacy_date("LN_1ST_PMT_DT", "first_payment_date"),
            parse_legacy_date("LN_NXT_PMT_DT", "next_payment_date"),
            expand_status("LN_STAT_CD", STATUS_MAP, "status"),
            F.col("LN_DLQ_DAYS").cast(IntegerType()).alias("delinquency_days"),
            parse_legacy_amount("LN_ESCROW_BAL", "escrow_balance"),
            F.col("LN_LTV_PCT").cast(DecimalType(5, 2)).alias("ltv_percent"),
            F.trim(F.col("PROP_ADDR_LN1")).alias("property_address"),
            F.trim(F.col("PROP_CTY_NM")).alias("property_city"),
            F.trim(F.col("PROP_ST_CD")).alias("property_state"),
            F.trim(F.col("PROP_ZIP_CD")).alias("property_zip"),
            expand_status("PROP_TYP_CD", PROPERTY_TYPE_MAP, "property_type"),
            parse_legacy_amount("PROP_APRS_VAL", "appraised_value"),
            F.coalesce(
                F.to_timestamp(F.col("LN_CRET_DT"), "MM/dd/yyyy"),
                F.to_timestamp(F.col("LN_CRET_DT"), "yyyy-MM-dd"),
                F.current_timestamp()
            ).alias("created_at"),
            F.coalesce(
                F.to_timestamp(F.col("LN_UPDT_DT"), "MM/dd/yyyy"),
                F.to_timestamp(F.col("LN_UPDT_DT"), "yyyy-MM-dd"),
                F.current_timestamp()
            ).alias("updated_at"),
            F.current_timestamp().alias("_ingestion_ts"),
            F.lit("CDW").alias("_source_system"),
        )
    )


def detect_anomalies(source_df: DataFrame, spark: SparkSession) -> DataFrame:
    anomalies = []

    # ANO-003: Orphaned borrower references
    borrower_ids = (
        spark.table(BORROWER_TABLE)
        .select(F.col("external_id").alias("valid_borr_id"))
    )
    orphan_borrowers = (
        source_df
        .join(borrower_ids, source_df["BORR_ID"] == borrower_ids["valid_borr_id"], "left_anti")
        .filter(F.col("BORR_ID").isNotNull())
        .select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_LN_ACCT").alias("source_table"),
            F.col("LN_ACCT_NBR").alias("source_record_id"),
            F.lit("BORR_ID").alias("column_name"),
            F.lit("FK_VIOLATION").alias("anomaly_type"),
            F.lit("CRITICAL").alias("severity"),
            F.concat(F.lit("Borrower "), F.col("BORR_ID"),
                     F.lit(" not found in borrowers table")).alias("description"),
            F.col("BORR_ID").alias("original_value"),
            F.lit(None).cast(StringType()).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
    )
    anomalies.append(orphan_borrowers)

    # ANO-003: Orphaned product references
    product_codes = (
        spark.table(PRODUCT_TABLE)
        .select(F.col("code").alias("valid_prod_cd"))
    )
    orphan_products = (
        source_df
        .join(product_codes, source_df["PROD_CD"] == product_codes["valid_prod_cd"], "left_anti")
        .filter(F.col("PROD_CD").isNotNull())
        .select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_LN_ACCT").alias("source_table"),
            F.col("LN_ACCT_NBR").alias("source_record_id"),
            F.lit("PROD_CD").alias("column_name"),
            F.lit("FK_VIOLATION").alias("anomaly_type"),
            F.lit("CRITICAL").alias("severity"),
            F.concat(F.lit("Product "), F.col("PROD_CD"),
                     F.lit(" not found in products table")).alias("description"),
            F.col("PROD_CD").alias("original_value"),
            F.lit(None).cast(StringType()).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
    )
    anomalies.append(orphan_products)

    # ANO-005: Denormalized borrower name mismatch
    borrowers_full = spark.table(BORROWER_TABLE).select(
        F.col("external_id"),
        F.col("first_name").alias("master_first"),
        F.col("last_name").alias("master_last"),
    )
    name_mismatches = (
        source_df
        .join(borrowers_full, source_df["BORR_ID"] == borrowers_full["external_id"], "inner")
        .filter(
            (F.upper(F.trim(F.col("BORR_FST_NM"))) != F.upper(F.col("master_first")))
            | (F.upper(F.trim(F.col("BORR_LST_NM"))) != F.upper(F.col("master_last")))
        )
        .select(
            F.lit(RUN_ID).alias("run_id"),
            F.lit("CDW_LN_ACCT").alias("source_table"),
            F.col("LN_ACCT_NBR").alias("source_record_id"),
            F.lit("BORR_FST_NM/BORR_LST_NM").alias("column_name"),
            F.lit("DATA_DRIFT").alias("anomaly_type"),
            F.lit("HIGH").alias("severity"),
            F.concat(
                F.lit("Denormalized name '"),
                F.col("BORR_FST_NM"), F.lit(" "), F.col("BORR_LST_NM"),
                F.lit("' differs from master '"),
                F.col("master_first"), F.lit(" "), F.col("master_last"),
                F.lit("'")
            ).alias("description"),
            F.concat(F.col("BORR_FST_NM"), F.lit(" "),
                     F.col("BORR_LST_NM")).alias("original_value"),
            F.concat(F.col("master_first"), F.lit(" "),
                     F.col("master_last")).alias("corrected_value"),
            F.current_timestamp().alias("detected_at"),
        )
    )
    anomalies.append(name_mismatches)

    # ANO-009: Delinquency > 0 but status = ACT
    delinquency_issues = source_df.filter(
        (F.col("LN_DLQ_DAYS").cast(IntegerType()) > 0)
        & (F.upper(F.trim(F.col("LN_STAT_CD"))) == "ACT")
    ).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_LN_ACCT").alias("source_table"),
        F.col("LN_ACCT_NBR").alias("source_record_id"),
        F.lit("LN_DLQ_DAYS/LN_STAT_CD").alias("column_name"),
        F.lit("BUSINESS_RULE").alias("anomaly_type"),
        F.lit("MEDIUM").alias("severity"),
        F.concat(
            F.lit("Delinquency days="), F.col("LN_DLQ_DAYS"),
            F.lit(" but status="), F.col("LN_STAT_CD")
        ).alias("description"),
        F.col("LN_DLQ_DAYS").alias("original_value"),
        F.lit(None).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(delinquency_issues)

    # ANO-010: LTV mismatch (stored vs computed from current balance / appraised value)
    amt_clean = lambda c: F.regexp_replace(F.col(c), r"[$,\s]", "").cast(DecimalType(12, 2))
    ltv_df = source_df.filter(
        F.col("PROP_APRS_VAL").isNotNull()
        & (amt_clean("PROP_APRS_VAL") > 0)
        & F.col("LN_LTV_PCT").isNotNull()
    ).withColumn("computed_ltv",
        amt_clean("LN_CURR_BAL") * 100 / amt_clean("PROP_APRS_VAL")
    ).withColumn("stored_ltv", F.col("LN_LTV_PCT").cast(DecimalType(5, 2)))

    ltv_mismatches = ltv_df.filter(
        F.abs(F.col("stored_ltv") - F.col("computed_ltv")) > 5.0
    ).select(
        F.lit(RUN_ID).alias("run_id"),
        F.lit("CDW_LN_ACCT").alias("source_table"),
        F.col("LN_ACCT_NBR").alias("source_record_id"),
        F.lit("LN_LTV_PCT").alias("column_name"),
        F.lit("BUSINESS_RULE").alias("anomaly_type"),
        F.lit("MEDIUM").alias("severity"),
        F.concat(
            F.lit("Stored LTV="), F.col("stored_ltv"),
            F.lit(" vs computed="), F.round(F.col("computed_ltv"), 1)
        ).alias("description"),
        F.col("LN_LTV_PCT").alias("original_value"),
        F.round(F.col("computed_ltv"), 1).cast(StringType()).alias("corrected_value"),
        F.current_timestamp().alias("detected_at"),
    )
    anomalies.append(ltv_mismatches)

    return reduce(DataFrame.unionByName, anomalies)


def run(spark: SparkSession) -> dict:
    print(f"[{RUN_ID}] Starting loan account ingestion...")
    source_df = read_source(spark)
    source_count = source_df.count()
    print(f"[{RUN_ID}] Source rows: {source_count}")

    anomaly_df = detect_anomalies(source_df, spark)
    anomaly_count = anomaly_df.count()
    print(f"[{RUN_ID}] Anomalies detected: {anomaly_count}")
    if anomaly_count > 0:
        anomaly_df.write.mode("append").saveAsTable(DQ_LOG_TABLE)

    transformed_df = transform(source_df, spark)
    transformed_df.createOrReplaceTempView("loans_staging")
    spark.sql(f"""
        MERGE INTO {TARGET_TABLE} AS target
        USING loans_staging AS source
        ON target.account_number = source.account_number
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)

    target_count = spark.table(TARGET_TABLE).count()
    print(f"[{RUN_ID}] Target rows: {target_count}")
    return {
        "run_id": RUN_ID,
        "source_count": source_count,
        "target_count": target_count,
        "anomaly_count": anomaly_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW Loan Account Ingestion").getOrCreate()
    result = run(spark)
    print(f"Ingestion complete: {result}")
