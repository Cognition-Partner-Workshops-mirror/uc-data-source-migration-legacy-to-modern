"""
Ingestion script for CDW_BORR_MSTR -> loan_warehouse.borrowers

Reads legacy borrower data from CSV/Parquet source, applies transformations:
- Date parsing (MM/DD/YYYY -> DATE/TIMESTAMP)
- Amount parsing (comma-formatted -> DECIMAL)
- Status code expansion (ACT -> ACTIVE, INA -> INACTIVE)
- Credit score parsing (string -> INT)
- Drops BORR_REC_TYP column (not needed in modern schema)
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructField,
    StructType,
    StringType,
)

from transformations import (
    BORROWER_STATUS_MAP,
    add_ingestion_metadata,
    expand_status_column,
    flag_parse_errors,
    log_rejected_records,
    parse_amount_column,
    parse_date_column,
    parse_integer_column,
    parse_timestamp_column,
)


# Schema for reading legacy CSV (all strings as in the legacy VARCHAR schema)
LEGACY_BORROWER_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), False),
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


def read_legacy_borrowers(spark: SparkSession, source_path: str) -> DataFrame:
    """
    Read legacy borrower data from CSV or Parquet source files.

    Args:
        spark: Active SparkSession
        source_path: Path to source files (supports CSV and Parquet)

    Returns:
        Raw DataFrame with legacy column names and string types
    """
    if source_path.endswith(".parquet") or source_path.endswith("/parquet"):
        return spark.read.schema(LEGACY_BORROWER_SCHEMA).parquet(source_path)

    return (
        spark.read
        .schema(LEGACY_BORROWER_SCHEMA)
        .option("header", "true")
        .option("quote", '"')
        .option("escape", '"')
        .csv(source_path)
    )


def transform_borrowers(df: DataFrame) -> DataFrame:
    """
    Apply all transformations to convert legacy borrower data to modern schema.

    Transformations applied:
    1. Rename columns from cryptic to meaningful names
    2. Parse date strings to DATE/TIMESTAMP types
    3. Parse credit score and income strings to numeric types
    4. Expand status code abbreviations
    5. Drop unused columns (BORR_REC_TYP)
    6. Add ingestion metadata
    """
    transformed = df.select(
        # Direct copies with rename
        F.col("BORR_ID").alias("external_id"),
        F.col("BORR_FST_NM").alias("first_name"),
        F.col("BORR_LST_NM").alias("last_name"),
        F.col("BORR_MID_INIT").alias("middle_initial"),
        F.col("BORR_SSN_ENCR").alias("ssn_hash"),
        # Date parsing
        parse_date_column("BORR_DOB_DT", "date_of_birth"),
        # Address fields
        F.col("BORR_ADDR_LN1").alias("address_line1"),
        F.col("BORR_ADDR_LN2").alias("address_line2"),
        F.col("BORR_CTY_NM").alias("city"),
        F.col("BORR_ST_CD").alias("state"),
        F.col("BORR_ZIP_CD").alias("zip_code"),
        # Contact
        F.col("BORR_PH_NBR").alias("phone"),
        F.col("BORR_EMAIL_ADDR").alias("email"),
        # Numeric parsing
        parse_integer_column("BORR_CRDT_SCR", "credit_score"),
        F.col("BORR_EMP_STAT").alias("employment_status"),
        parse_amount_column("BORR_ANN_INCM", 12, 2, "annual_income"),
        # Status expansion
        expand_status_column("BORR_STAT_CD", BORROWER_STATUS_MAP, "status"),
        # Timestamps
        parse_timestamp_column("BORR_CRET_DT", "created_at"),
        parse_timestamp_column("BORR_UPDT_DT", "updated_at"),
        # Keep original columns for error detection
        F.col("BORR_DOB_DT").alias("_raw_dob"),
        F.col("BORR_CRDT_SCR").alias("_raw_credit_score"),
        F.col("BORR_ANN_INCM").alias("_raw_annual_income"),
    )

    # Flag parse errors
    transformed = flag_parse_errors(transformed, "_raw_dob", "date_of_birth", "_dob_error")
    transformed = flag_parse_errors(transformed, "_raw_credit_score", "credit_score", "_credit_score_error")
    transformed = flag_parse_errors(transformed, "_raw_annual_income", "annual_income", "_income_error")

    return transformed


def write_borrowers(
    df: DataFrame,
    target_table: str,
    rejection_path: str,
    mode: str = "overwrite",
) -> dict:
    """
    Write transformed borrower data to Delta Lake table.

    Records with parse errors are logged to the rejection path but NOT dropped
    from the target table (partial data is better than lost records).

    Args:
        df: Transformed DataFrame
        target_table: Full table name (e.g., loan_warehouse.borrowers)
        rejection_path: Base path for rejection logs
        mode: Write mode (overwrite for initial load, append for incremental)

    Returns:
        Dictionary with ingestion statistics
    """
    error_columns = ["_dob_error", "_credit_score_error", "_income_error"]
    total_count = df.count()
    rejected_count = log_rejected_records(df, error_columns, "borrowers", rejection_path)

    # Drop raw/error columns before writing to target
    clean_df = df.drop("_raw_dob", "_raw_credit_score", "_raw_annual_income",
                       "_dob_error", "_credit_score_error", "_income_error")
    clean_df = add_ingestion_metadata(clean_df, "CDW_BORR_MSTR")

    clean_df.write.mode(mode).format("delta").saveAsTable(target_table)

    stats = {
        "table": target_table,
        "source_count": total_count,
        "loaded_count": total_count,
        "rejected_count": rejected_count,
        "rejection_rate": f"{(rejected_count / max(total_count, 1)) * 100:.2f}%",
    }
    print(f"[INFO] Borrower ingestion complete: {stats}")
    return stats


def run(spark: SparkSession, config: dict) -> dict:
    """
    Main entry point for borrower ingestion.

    Args:
        spark: Active SparkSession
        config: Dictionary with keys:
            - source_path: Path to legacy borrower CSV/Parquet
            - target_table: Target Delta table name
            - rejection_path: Path for rejection logs
            - mode: Write mode (default: overwrite)
    """
    source_path = config["source_path"]
    target_table = config.get("target_table", "loan_warehouse.borrowers")
    rejection_path = config.get("rejection_path", "/mnt/data/rejections")
    mode = config.get("mode", "overwrite")

    print(f"[INFO] Starting borrower ingestion from: {source_path}")
    raw_df = read_legacy_borrowers(spark, source_path)
    print(f"[INFO] Read {raw_df.count()} records from source")

    transformed_df = transform_borrowers(raw_df)
    return write_borrowers(transformed_df, target_table, rejection_path, mode)
