"""
Ingest CDW_PMT_HIST → loan_warehouse.payments

Key transformations:
  - LN_ACCT_NBR is resolved to loan_warehouse.loan_accounts.loan_account_id.
  - All amount and date fields are parsed from VARCHAR strings.
  - Payment type and status codes are expanded to readable values.
  - A payment_year column is derived for Delta partitioning.
  - Legacy PMT_SEQ_NBR is preserved as legacy_sequence_nbr for audit trail.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

from transforms import (
    parse_date,
    parse_timestamp,
    parse_amount,
    expand_code,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SOURCE_PATH = "/mnt/landing/legacy/CDW_PMT_HIST"
TARGET_TABLE = "loan_warehouse.payments"
QUARANTINE_TABLE = "loan_warehouse._quarantine_payments"

LEGACY_SCHEMA = StructType([
    StructField("PMT_SEQ_NBR",    StringType(), True),
    StructField("LN_ACCT_NBR",    StringType(), True),
    StructField("PMT_DT",         StringType(), True),
    StructField("PMT_AMT",        StringType(), True),
    StructField("PMT_PRIN_AMT",   StringType(), True),
    StructField("PMT_INT_AMT",    StringType(), True),
    StructField("PMT_ESCROW_AMT", StringType(), True),
    StructField("PMT_LATE_FEE",   StringType(), True),
    StructField("PMT_TYP_CD",     StringType(), True),
    StructField("PMT_STAT_CD",    StringType(), True),
    StructField("PMT_RECV_DT",    StringType(), True),
    StructField("PMT_PROC_DT",    StringType(), True),
    StructField("PMT_CRET_DT",    StringType(), True),
    StructField("PMT_UPDT_DT",    StringType(), True),
])


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_source(spark: SparkSession, path: str = SOURCE_PATH) -> DataFrame:
    try:
        return spark.read.parquet(path)
    except Exception:
        return (
            spark.read
            .option("header", "true")
            .option("inferSchema", "false")
            .schema(LEGACY_SCHEMA)
            .csv(path)
        )


# ---------------------------------------------------------------------------
# FK resolution
# ---------------------------------------------------------------------------

def resolve_loan_account_fk(spark: SparkSession, df: DataFrame) -> DataFrame:
    """Join to loan_accounts to resolve LN_ACCT_NBR → loan_account_id."""
    loans = spark.table("loan_warehouse.loan_accounts").select(
        F.col("loan_account_id"),
        F.col("account_number").alias("_acct_number"),
    )
    return (
        df.join(loans, df["_acct_nbr_clean"] == loans["_acct_number"], "left")
          .drop("_acct_number", "_acct_nbr_clean")
    )


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform(spark: SparkSession, df: DataFrame) -> tuple[DataFrame, DataFrame]:
    transformed = (
        df
        .withColumn("legacy_sequence_nbr", F.trim(F.col("PMT_SEQ_NBR")))
        .withColumn("_acct_nbr_clean",     F.trim(F.col("LN_ACCT_NBR")))
        .withColumn("payment_date",        parse_date(F.col("PMT_DT")))
        .withColumn("total_amount",        parse_amount(F.col("PMT_AMT"), 10, 2))
        .withColumn("principal_amount",    parse_amount(F.col("PMT_PRIN_AMT"), 10, 2))
        .withColumn("interest_amount",     parse_amount(F.col("PMT_INT_AMT"), 10, 2))
        .withColumn("escrow_amount",       parse_amount(F.col("PMT_ESCROW_AMT"), 10, 2))
        .withColumn("late_fee",            parse_amount(F.col("PMT_LATE_FEE"), 10, 2))
        .withColumn("type",               expand_code(F.col("PMT_TYP_CD"), PAYMENT_TYPE_MAP, default="Regular"))
        .withColumn("status",             expand_code(F.col("PMT_STAT_CD"), PAYMENT_STATUS_MAP, default="Pending"))
        .withColumn("received_date",      parse_date(F.col("PMT_RECV_DT")))
        .withColumn("processed_date",     parse_date(F.col("PMT_PROC_DT")))
        .withColumn("payment_year",       F.year(parse_date(F.col("PMT_DT"))))
        .withColumn("created_at",         parse_timestamp(F.col("PMT_CRET_DT")))
        .withColumn("updated_at",         parse_timestamp(F.col("PMT_UPDT_DT")))
    )

    # Resolve loan_account FK
    transformed = resolve_loan_account_fk(spark, transformed)

    # Quarantine: unresolvable FK or missing required fields
    quarantine_condition = (
        F.col("loan_account_id").isNull()
        | F.col("payment_date").isNull()
        | F.col("total_amount").isNull()
        | F.col("type").isNull()
        | F.col("status").isNull()
    )

    quarantine_reasons = (
        F.when(F.col("loan_account_id").isNull(), F.lit("Unresolvable LN_ACCT_NBR"))
         .when(F.col("payment_date").isNull(), F.lit("Unparseable PMT_DT"))
         .when(F.col("total_amount").isNull(), F.lit("Unparseable PMT_AMT"))
         .otherwise(F.lit("Missing required field"))
    )

    quarantine = (
        transformed
        .filter(quarantine_condition)
        .withColumn("_quarantine_reason", quarantine_reasons)
        .withColumn("_quarantine_ts", F.current_timestamp())
    )

    good = transformed.filter(~quarantine_condition)

    target_columns = [
        "legacy_sequence_nbr", "loan_account_id", "payment_date",
        "total_amount", "principal_amount", "interest_amount",
        "escrow_amount", "late_fee", "type", "status",
        "received_date", "processed_date", "payment_year",
        "created_at", "updated_at",
    ]

    return good.select(target_columns), quarantine


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_target(df: DataFrame, table: str = TARGET_TABLE) -> None:
    from delta.tables import DeltaTable

    if DeltaTable.isDeltaTable(df.sparkSession, table):
        delta_table = DeltaTable.forName(df.sparkSession, table)
        (
            delta_table.alias("tgt")
            .merge(
                df.alias("src"),
                "tgt.legacy_sequence_nbr = src.legacy_sequence_nbr",
            )
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )
    else:
        (
            df.write
            .format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .partitionBy("payment_year")
            .saveAsTable(table)
        )


def write_quarantine(df: DataFrame, table: str = QUARANTINE_TABLE) -> None:
    if df.count() > 0:
        (
            df.write
            .format("delta")
            .mode("append")
            .saveAsTable(table)
        )
        print(f"WARNING: {df.count()} payment record(s) quarantined to {table}")
    else:
        print("No payment records quarantined.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(spark: SparkSession, source_path: str = SOURCE_PATH) -> dict:
    raw = read_source(spark, source_path)
    source_count = raw.count()
    print(f"[payments] Source rows read: {source_count}")

    good, quarantine = transform(spark, raw)
    good_count = good.count()
    quarantine_count = quarantine.count()

    print(f"[payments] Good rows:        {good_count}")
    print(f"[payments] Quarantined rows:  {quarantine_count}")

    write_target(good)
    write_quarantine(quarantine)

    return {
        "table": TARGET_TABLE,
        "source_count": source_count,
        "target_count": good_count,
        "quarantine_count": quarantine_count,
    }


if __name__ == "__main__":
    spark = SparkSession.builder.appName("Ingest CDW_PMT_HIST → payments").getOrCreate()
    stats = run(spark)
    print(f"[payments] Ingestion complete: {stats}")
