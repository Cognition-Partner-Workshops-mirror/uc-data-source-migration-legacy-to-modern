"""
Data quality checks for the legacy-to-modern migration pipeline.

Provides reusable validation functions that run between pipeline stages
to catch anomalies before they propagate. Each check returns a DataFrame
of quality issues that can be logged or quarantined.

Integrates with Databricks expectations / Delta Live Tables constraints
where available, but works standalone with standard PySpark.
"""

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType

import sys
sys.path.insert(0, "..")
from config.pipeline_config import (
    CREDIT_SCORE_MIN,
    CREDIT_SCORE_MAX,
    PAYMENT_RECONCILIATION_TOLERANCE,
    MAX_NULL_PERCENT_CRITICAL,
)

# Schema for quality issue records
QUALITY_ISSUE_SCHEMA = StructType([
    StructField("table_name", StringType(), False),
    StructField("record_id", StringType(), True),
    StructField("field", StringType(), False),
    StructField("severity", StringType(), False),       # CRITICAL, HIGH, MEDIUM, LOW
    StructField("issue_type", StringType(), False),     # NULL_REQUIRED, PARSE_FAILURE, INVALID_CODE, etc.
    StructField("message", StringType(), False),
    StructField("raw_value", StringType(), True),
])


def check_null_required_fields(
    df: DataFrame,
    table_name: str,
    id_col: str,
    required_fields: list[str],
    severity: str = "CRITICAL",
) -> DataFrame:
    """
    Check that required fields are not null or blank.
    Returns a DataFrame of quality issues for each violation.
    """
    spark = df.sparkSession
    issues = spark.createDataFrame([], QUALITY_ISSUE_SCHEMA)

    for field in required_fields:
        # Find rows where the field is null or blank
        violations = df.filter(
            F.col(field).isNull() | (F.trim(F.col(field)) == "")
        ).select(
            F.lit(table_name).alias("table_name"),
            F.col(id_col).cast("string").alias("record_id"),
            F.lit(field).alias("field"),
            F.lit(severity).alias("severity"),
            F.lit("NULL_REQUIRED").alias("issue_type"),
            F.lit(f"Required field '{field}' is null or blank").alias("message"),
            F.lit(None).cast("string").alias("raw_value"),
        )
        issues = issues.union(violations)

    return issues


def check_date_parseable(
    df: DataFrame,
    table_name: str,
    id_col: str,
    date_fields: list[str],
    date_format: str = "MM/dd/yyyy",
    severity: str = "HIGH",
) -> DataFrame:
    """
    Verify that string date fields can be parsed with the expected format.
    Returns issues for rows where parsing yields null (unparseable).
    """
    spark = df.sparkSession
    issues = spark.createDataFrame([], QUALITY_ISSUE_SCHEMA)

    for field in date_fields:
        # Attempt parse — null result means parse failure
        parsed = F.to_date(F.trim(F.col(field)), date_format)
        violations = df.filter(
            F.col(field).isNotNull() & (F.trim(F.col(field)) != "") & parsed.isNull()
        ).select(
            F.lit(table_name).alias("table_name"),
            F.col(id_col).cast("string").alias("record_id"),
            F.lit(field).alias("field"),
            F.lit(severity).alias("severity"),
            F.lit("PARSE_FAILURE").alias("issue_type"),
            F.concat(
                F.lit(f"Cannot parse '{field}' value '"),
                F.col(field),
                F.lit(f"' as date ({date_format})")
            ).alias("message"),
            F.col(field).alias("raw_value"),
        )
        issues = issues.union(violations)

    return issues


def check_numeric_parseable(
    df: DataFrame,
    table_name: str,
    id_col: str,
    numeric_fields: list[str],
    severity: str = "HIGH",
) -> DataFrame:
    """
    Verify that string numeric fields (amounts, rates) can be cast to decimal
    after removing commas and dollar signs. Returns issues for parse failures.
    """
    spark = df.sparkSession
    issues = spark.createDataFrame([], QUALITY_ISSUE_SCHEMA)

    for field in numeric_fields:
        # Clean then attempt cast
        cleaned = F.regexp_replace(F.trim(F.coalesce(F.col(field), F.lit(""))), r"[$,]", "")
        parsed = cleaned.cast("decimal(12,2)")
        violations = df.filter(
            F.col(field).isNotNull()
            & (F.trim(F.col(field)) != "")
            & parsed.isNull()
        ).select(
            F.lit(table_name).alias("table_name"),
            F.col(id_col).cast("string").alias("record_id"),
            F.lit(field).alias("field"),
            F.lit(severity).alias("severity"),
            F.lit("PARSE_FAILURE").alias("issue_type"),
            F.concat(
                F.lit(f"Cannot parse '{field}' value '"),
                F.col(field),
                F.lit("' as numeric")
            ).alias("message"),
            F.col(field).alias("raw_value"),
        )
        issues = issues.union(violations)

    return issues


def check_valid_status_codes(
    df: DataFrame,
    table_name: str,
    id_col: str,
    status_col: str,
    valid_codes: set[str],
    severity: str = "MEDIUM",
) -> DataFrame:
    """
    Verify that status code values are in the allowed set.
    Returns issues for any unrecognized codes.
    """
    violations = df.filter(
        F.col(status_col).isNotNull()
        & ~F.upper(F.trim(F.col(status_col))).isin(list(valid_codes))
    ).select(
        F.lit(table_name).alias("table_name"),
        F.col(id_col).cast("string").alias("record_id"),
        F.lit(status_col).alias("field"),
        F.lit(severity).alias("severity"),
        F.lit("INVALID_CODE").alias("issue_type"),
        F.concat(
            F.lit(f"Invalid status code '"),
            F.col(status_col),
            F.lit(f"' in {status_col}. Valid: {sorted(valid_codes)}")
        ).alias("message"),
        F.col(status_col).alias("raw_value"),
    )
    return violations


def check_credit_score_range(
    df: DataFrame,
    table_name: str,
    id_col: str,
    score_col: str,
    min_score: int = CREDIT_SCORE_MIN,
    max_score: int = CREDIT_SCORE_MAX,
) -> DataFrame:
    """
    Verify credit scores fall within the valid FICO range [300, 850].
    Only checks rows where the score is parseable as integer.
    """
    parsed = F.trim(F.col(score_col)).cast("integer")
    violations = df.filter(
        parsed.isNotNull()
        & ((parsed < min_score) | (parsed > max_score))
    ).select(
        F.lit(table_name).alias("table_name"),
        F.col(id_col).cast("string").alias("record_id"),
        F.lit(score_col).alias("field"),
        F.lit("MEDIUM").alias("severity"),
        F.lit("OUT_OF_RANGE").alias("issue_type"),
        F.concat(
            F.lit(f"Credit score "),
            F.col(score_col),
            F.lit(f" outside valid range [{min_score}-{max_score}]")
        ).alias("message"),
        F.col(score_col).alias("raw_value"),
    )
    return violations


def check_payment_reconciliation(
    df: DataFrame,
    table_name: str,
    id_col: str,
    total_col: str,
    component_cols: list[str],
    tolerance: float = PAYMENT_RECONCILIATION_TOLERANCE,
) -> DataFrame:
    """
    Verify that payment component amounts sum to the total.
    Flags discrepancies beyond the configured tolerance.

    ANO-001: Payment components should reconcile with total payment amount.
    """
    # Parse all amount columns (remove commas)
    def clean_amt(c):
        return F.coalesce(
            F.regexp_replace(F.trim(F.coalesce(F.col(c), F.lit("0"))), r"[$,]", "").cast("decimal(10,2)"),
            F.lit(0).cast("decimal(10,2)")
        )

    total_parsed = clean_amt(total_col)
    component_sum = sum(clean_amt(c) for c in component_cols)

    discrepancy = F.abs(total_parsed - component_sum)

    violations = df.filter(discrepancy > tolerance).select(
        F.lit(table_name).alias("table_name"),
        F.col(id_col).cast("string").alias("record_id"),
        F.lit(total_col).alias("field"),
        F.lit("CRITICAL").alias("severity"),
        F.lit("RECONCILIATION_MISMATCH").alias("issue_type"),
        F.concat(
            F.lit("Payment components sum ("),
            component_sum.cast("string"),
            F.lit(") != total ("),
            total_parsed.cast("string"),
            F.lit("). Discrepancy: $"),
            discrepancy.cast("string"),
        ).alias("message"),
        F.col(total_col).alias("raw_value"),
    )
    return violations


def check_delinquency_status_consistency(
    df: DataFrame,
    table_name: str,
    id_col: str,
    delinquency_col: str,
    status_col: str,
) -> DataFrame:
    """
    ANO-003: Verify that loans with delinquency_days > 0 do not have
    status 'ACT'. Delinquent loans should be DFT, DLQ, or FRB.
    """
    dlq_days = F.trim(F.col(delinquency_col)).cast("integer")
    violations = df.filter(
        dlq_days.isNotNull()
        & (dlq_days > 0)
        & (F.upper(F.trim(F.col(status_col))) == "ACT")
    ).select(
        F.lit(table_name).alias("table_name"),
        F.col(id_col).cast("string").alias("record_id"),
        F.lit(f"{delinquency_col}/{status_col}").alias("field"),
        F.lit("CRITICAL").alias("severity"),
        F.lit("STATUS_INCONSISTENCY").alias("issue_type"),
        F.concat(
            F.lit("Loan has "),
            F.col(delinquency_col),
            F.lit(" delinquency days but status is 'ACT'. Expected DFT, DLQ, or FRB."),
        ).alias("message"),
        F.col(status_col).alias("raw_value"),
    )
    return violations


def check_referential_integrity(
    child_df: DataFrame,
    parent_df: DataFrame,
    child_table: str,
    child_id_col: str,
    child_fk_col: str,
    parent_key_col: str,
) -> DataFrame:
    """
    Check for orphaned records — child FK references that don't exist in parent.
    """
    # Left anti join to find child rows with no parent match
    orphans = child_df.join(
        parent_df.select(F.col(parent_key_col).alias("_parent_key")),
        F.col(child_fk_col) == F.col("_parent_key"),
        "left_anti"
    ).filter(F.col(child_fk_col).isNotNull())

    violations = orphans.select(
        F.lit(child_table).alias("table_name"),
        F.col(child_id_col).cast("string").alias("record_id"),
        F.lit(child_fk_col).alias("field"),
        F.lit("HIGH").alias("severity"),
        F.lit("ORPHANED_RECORD").alias("issue_type"),
        F.concat(
            F.lit(f"No matching parent record found for {child_fk_col}='"),
            F.col(child_fk_col),
            F.lit("'"),
        ).alias("message"),
        F.col(child_fk_col).alias("raw_value"),
    )
    return violations


def log_quality_summary(issues_df: DataFrame, pipeline_stage: str) -> None:
    """
    Print a summary of data quality issues by severity and type.
    In production, this would write to a monitoring table or alert system.
    """
    if issues_df.count() == 0:
        print(f"[{pipeline_stage}] ✓ No data quality issues found.")
        return

    print(f"\n[{pipeline_stage}] Data Quality Issues Summary:")
    print("=" * 60)
    issues_df.groupBy("severity", "issue_type").agg(
        F.count("*").alias("count")
    ).orderBy("severity", "issue_type").show(truncate=False)

    # Show sample issues
    print(f"\nSample issues (top 10):")
    issues_df.select("table_name", "record_id", "field", "severity", "message").show(
        10, truncate=80
    )
