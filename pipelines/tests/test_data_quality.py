"""
Unit tests for data quality check functions.

Verifies that each quality check correctly identifies anomalies in the
legacy CDW data, matching the documented anomalies in DATA_ANOMALY_REPORT.md.
"""

import pytest
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

import sys
sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from utils.data_quality import (
    check_null_required_fields,
    check_date_parseable,
    check_numeric_parseable,
    check_valid_status_codes,
    check_credit_score_range,
    check_payment_reconciliation,
    check_delinquency_status_consistency,
    check_referential_integrity,
    QUALITY_ISSUE_SCHEMA,
)
from config.pipeline_config import LOAN_STATUS_MAP, BORROWER_STATUS_MAP


@pytest.fixture(scope="session")
def spark():
    """Create a local Spark session for testing."""
    return (
        SparkSession.builder
        .master("local[*]")
        .appName("dq-tests")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.sql.ansi.enabled", "false")
        .getOrCreate()
    )


# Helper: schema for borrower-like test DataFrames
BORR_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_FST_NM", StringType(), True),
    StructField("BORR_LST_NM", StringType(), True),
])

BORR_DATE_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_DOB_DT", StringType(), True),
])

BORR_NUMERIC_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_ANN_INCM", StringType(), True),
])

BORR_SCORE_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), True),
    StructField("BORR_CRDT_SCR", StringType(), True),
])

LOAN_STATUS_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("LN_STAT_CD", StringType(), True),
])

LOAN_NUMERIC_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("LN_ORIG_AMT", StringType(), True),
])

PAYMENT_SCHEMA = StructType([
    StructField("PMT_SEQ_NBR", StringType(), True),
    StructField("PMT_AMT", StringType(), True),
    StructField("PMT_PRIN_AMT", StringType(), True),
    StructField("PMT_INT_AMT", StringType(), True),
    StructField("PMT_ESCROW_AMT", StringType(), True),
    StructField("PMT_LATE_FEE", StringType(), True),
])

DLQ_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("LN_DLQ_DAYS", StringType(), True),
    StructField("LN_STAT_CD", StringType(), True),
])

FK_CHILD_SCHEMA = StructType([
    StructField("LN_ACCT_NBR", StringType(), True),
    StructField("BORR_ID", StringType(), True),
])

FK_PARENT_SCHEMA = StructType([
    StructField("BORR_ID", StringType(), True),
])


# =============================================================================
# Null Required Fields
# =============================================================================

class TestNullRequiredFields:
    """ANO-008: Detect null values in required fields."""

    def test_detects_null_field(self, spark):
        """Should flag a record with null in a required field."""
        df = spark.createDataFrame(
            [("B-001", None, "Smith")], schema=BORR_SCHEMA
        )
        issues = check_null_required_fields(
            df, "CDW_BORR_MSTR", "BORR_ID", ["BORR_FST_NM"]
        )
        assert issues.count() == 1
        row = issues.first()
        assert row["issue_type"] == "NULL_REQUIRED"
        assert row["record_id"] == "B-001"

    def test_detects_blank_field(self, spark):
        """Should flag empty-string (blank) as null equivalent."""
        df = spark.createDataFrame(
            [("B-002", "  ", "Jones")], schema=BORR_SCHEMA
        )
        issues = check_null_required_fields(
            df, "CDW_BORR_MSTR", "BORR_ID", ["BORR_FST_NM"]
        )
        assert issues.count() == 1

    def test_no_issues_when_valid(self, spark):
        """Should return empty DataFrame when all required fields present."""
        df = spark.createDataFrame(
            [("B-003", "John", "Doe")], schema=BORR_SCHEMA
        )
        issues = check_null_required_fields(
            df, "CDW_BORR_MSTR", "BORR_ID", ["BORR_FST_NM", "BORR_LST_NM"]
        )
        assert issues.count() == 0


# =============================================================================
# Date Parsing Validation
# =============================================================================

class TestDateParseable:
    """ANO-006: Detect unparseable date values."""

    def test_detects_invalid_date(self, spark):
        """Should flag dates that don't match MM/dd/yyyy format."""
        df = spark.createDataFrame(
            [("B-001", "1978-03-15")], schema=BORR_DATE_SCHEMA
        )
        issues = check_date_parseable(
            df, "CDW_BORR_MSTR", "BORR_ID", ["BORR_DOB_DT"]
        )
        assert issues.count() == 1
        assert issues.first()["issue_type"] == "PARSE_FAILURE"

    def test_detects_impossible_date(self, spark):
        """Should flag impossible dates like Feb 30."""
        df = spark.createDataFrame(
            [("B-002", "02/30/1978")], schema=BORR_DATE_SCHEMA
        )
        issues = check_date_parseable(
            df, "CDW_BORR_MSTR", "BORR_ID", ["BORR_DOB_DT"]
        )
        assert issues.count() == 1

    def test_valid_date_no_issue(self, spark):
        """Valid MM/dd/yyyy should not be flagged."""
        df = spark.createDataFrame(
            [("B-003", "03/15/1978")], schema=BORR_DATE_SCHEMA
        )
        issues = check_date_parseable(
            df, "CDW_BORR_MSTR", "BORR_ID", ["BORR_DOB_DT"]
        )
        assert issues.count() == 0

    def test_null_date_not_flagged(self, spark):
        """Null dates are not parse failures (they're a separate check)."""
        df = spark.createDataFrame(
            [("B-004", None)], schema=BORR_DATE_SCHEMA
        )
        issues = check_date_parseable(
            df, "CDW_BORR_MSTR", "BORR_ID", ["BORR_DOB_DT"]
        )
        assert issues.count() == 0


# =============================================================================
# Numeric Parsing Validation
# =============================================================================

class TestNumericParseable:
    """ANO-005: Detect non-numeric values in amount/numeric fields."""

    def test_detects_non_numeric(self, spark):
        """Should flag values that can't be parsed after comma removal."""
        df = spark.createDataFrame(
            [("B-001", "N/A")], schema=BORR_NUMERIC_SCHEMA
        )
        issues = check_numeric_parseable(
            df, "CDW_BORR_MSTR", "BORR_ID", ["BORR_ANN_INCM"]
        )
        assert issues.count() == 1
        assert issues.first()["issue_type"] == "PARSE_FAILURE"

    def test_valid_comma_amount(self, spark):
        """Amount with commas should parse fine."""
        df = spark.createDataFrame(
            [("B-002", "92,500")], schema=BORR_NUMERIC_SCHEMA
        )
        issues = check_numeric_parseable(
            df, "CDW_BORR_MSTR", "BORR_ID", ["BORR_ANN_INCM"]
        )
        assert issues.count() == 0

    def test_dollar_sign_amount(self, spark):
        """Amount with $ prefix should parse fine ($ is stripped)."""
        df = spark.createDataFrame(
            [("LN-001", "$285,000")], schema=LOAN_NUMERIC_SCHEMA
        )
        issues = check_numeric_parseable(
            df, "CDW_LN_ACCT", "LN_ACCT_NBR", ["LN_ORIG_AMT"]
        )
        assert issues.count() == 0


# =============================================================================
# Status Code Validation
# =============================================================================

class TestValidStatusCodes:
    """ANO-004: Detect invalid/unrecognized status codes."""

    def test_detects_invalid_code(self, spark):
        """Should flag status codes not in the valid set."""
        df = spark.createDataFrame(
            [("LN-001", "XYZ")], schema=LOAN_STATUS_SCHEMA
        )
        valid = set(LOAN_STATUS_MAP.keys())
        issues = check_valid_status_codes(
            df, "CDW_LN_ACCT", "LN_ACCT_NBR", "LN_STAT_CD", valid
        )
        assert issues.count() == 1
        assert issues.first()["issue_type"] == "INVALID_CODE"

    def test_valid_code_no_issue(self, spark):
        """Valid status codes should not be flagged."""
        df = spark.createDataFrame(
            [("LN-001", "ACT"), ("LN-002", "DLQ"), ("LN-003", "CLO")],
            schema=LOAN_STATUS_SCHEMA
        )
        valid = set(LOAN_STATUS_MAP.keys())
        issues = check_valid_status_codes(
            df, "CDW_LN_ACCT", "LN_ACCT_NBR", "LN_STAT_CD", valid
        )
        assert issues.count() == 0


# =============================================================================
# Credit Score Range
# =============================================================================

class TestCreditScoreRange:
    """Detect credit scores outside valid FICO range [300, 850]."""

    def test_detects_out_of_range_high(self, spark):
        """Score > 850 should be flagged."""
        df = spark.createDataFrame(
            [("B-001", "999")], schema=BORR_SCORE_SCHEMA
        )
        issues = check_credit_score_range(df, "CDW_BORR_MSTR", "BORR_ID", "BORR_CRDT_SCR")
        assert issues.count() == 1
        assert issues.first()["issue_type"] == "OUT_OF_RANGE"

    def test_detects_out_of_range_low(self, spark):
        """Score < 300 should be flagged."""
        df = spark.createDataFrame(
            [("B-002", "100")], schema=BORR_SCORE_SCHEMA
        )
        issues = check_credit_score_range(df, "CDW_BORR_MSTR", "BORR_ID", "BORR_CRDT_SCR")
        assert issues.count() == 1

    def test_valid_score_not_flagged(self, spark):
        """Score within [300, 850] should pass."""
        df = spark.createDataFrame(
            [("B-003", "745")], schema=BORR_SCORE_SCHEMA
        )
        issues = check_credit_score_range(df, "CDW_BORR_MSTR", "BORR_ID", "BORR_CRDT_SCR")
        assert issues.count() == 0


# =============================================================================
# Payment Reconciliation
# =============================================================================

class TestPaymentReconciliation:
    """ANO-001: Detect payment component sum mismatches."""

    def test_detects_mismatch(self, spark):
        """Should flag when components don't sum to total."""
        # total=1487.02 but principal+interest+escrow+late = 456.78+1074.69+355.55+0 = 1887.02
        df = spark.createDataFrame(
            [("PMT-001", "1,487.02", "456.78", "1,074.69", "355.55", "0.00")],
            schema=PAYMENT_SCHEMA,
        )
        issues = check_payment_reconciliation(
            df, "CDW_PMT_HIST", "PMT_SEQ_NBR", "PMT_AMT",
            ["PMT_PRIN_AMT", "PMT_INT_AMT", "PMT_ESCROW_AMT", "PMT_LATE_FEE"]
        )
        assert issues.count() == 1
        assert issues.first()["issue_type"] == "RECONCILIATION_MISMATCH"

    def test_valid_reconciliation(self, spark):
        """Should not flag when components sum correctly."""
        # total=2924.18, components: 1842.56+815.50+266.12+0.00 = 2924.18
        df = spark.createDataFrame(
            [("PMT-002", "2,924.18", "1,842.56", "815.50", "266.12", "0.00")],
            schema=PAYMENT_SCHEMA,
        )
        issues = check_payment_reconciliation(
            df, "CDW_PMT_HIST", "PMT_SEQ_NBR", "PMT_AMT",
            ["PMT_PRIN_AMT", "PMT_INT_AMT", "PMT_ESCROW_AMT", "PMT_LATE_FEE"]
        )
        assert issues.count() == 0

    def test_tolerance_respected(self, spark):
        """Should not flag discrepancies within tolerance ($0.02)."""
        # total=100.00, components sum to 100.01 (within $0.02 tolerance)
        df = spark.createDataFrame(
            [("PMT-003", "100.00", "50.01", "40.00", "10.00", "0.00")],
            schema=PAYMENT_SCHEMA,
        )
        issues = check_payment_reconciliation(
            df, "CDW_PMT_HIST", "PMT_SEQ_NBR", "PMT_AMT",
            ["PMT_PRIN_AMT", "PMT_INT_AMT", "PMT_ESCROW_AMT", "PMT_LATE_FEE"]
        )
        assert issues.count() == 0


# =============================================================================
# Delinquency / Status Consistency
# =============================================================================

class TestDelinquencyStatusConsistency:
    """ANO-003: Detect delinquent loans incorrectly marked as Active."""

    def test_detects_inconsistency(self, spark):
        """Loan with delinquency > 0 and status ACT should be flagged."""
        df = spark.createDataFrame(
            [("LN-001", "15", "ACT")], schema=DLQ_SCHEMA
        )
        issues = check_delinquency_status_consistency(
            df, "CDW_LN_ACCT", "LN_ACCT_NBR", "LN_DLQ_DAYS", "LN_STAT_CD"
        )
        assert issues.count() == 1
        assert issues.first()["issue_type"] == "STATUS_INCONSISTENCY"

    def test_valid_delinquent_default(self, spark):
        """Loan with delinquency > 0 and status DFT should pass."""
        df = spark.createDataFrame(
            [("LN-002", "30", "DFT")], schema=DLQ_SCHEMA
        )
        issues = check_delinquency_status_consistency(
            df, "CDW_LN_ACCT", "LN_ACCT_NBR", "LN_DLQ_DAYS", "LN_STAT_CD"
        )
        assert issues.count() == 0

    def test_zero_delinquency_active_ok(self, spark):
        """Loan with 0 delinquency days and ACT status is valid."""
        df = spark.createDataFrame(
            [("LN-003", "0", "ACT")], schema=DLQ_SCHEMA
        )
        issues = check_delinquency_status_consistency(
            df, "CDW_LN_ACCT", "LN_ACCT_NBR", "LN_DLQ_DAYS", "LN_STAT_CD"
        )
        assert issues.count() == 0


# =============================================================================
# Referential Integrity
# =============================================================================

class TestReferentialIntegrity:
    """ANO-004/009: Detect orphaned records (FK violations)."""

    def test_detects_orphan(self, spark):
        """Should flag child record with no matching parent."""
        child = spark.createDataFrame(
            [("LN-001", "B-999")], schema=FK_CHILD_SCHEMA
        )
        parent = spark.createDataFrame(
            [("B-001",), ("B-002",)], schema=FK_PARENT_SCHEMA
        )
        issues = check_referential_integrity(
            child, parent, "CDW_LN_ACCT", "LN_ACCT_NBR", "BORR_ID", "BORR_ID"
        )
        assert issues.count() == 1
        assert issues.first()["issue_type"] == "ORPHANED_RECORD"

    def test_valid_reference_no_issue(self, spark):
        """Should not flag when all FK references resolve."""
        child = spark.createDataFrame(
            [("LN-001", "B-001"), ("LN-002", "B-002")], schema=FK_CHILD_SCHEMA
        )
        parent = spark.createDataFrame(
            [("B-001",), ("B-002",)], schema=FK_PARENT_SCHEMA
        )
        issues = check_referential_integrity(
            child, parent, "CDW_LN_ACCT", "LN_ACCT_NBR", "BORR_ID", "BORR_ID"
        )
        assert issues.count() == 0
