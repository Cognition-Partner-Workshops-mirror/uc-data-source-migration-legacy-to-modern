"""
Unit tests for PySpark transformation functions.

Tests all shared transformation utilities used across the migration pipeline:
- Date parsing (legacy MM/DD/YYYY → DateType)
- Amount parsing (comma-separated strings → DecimalType)
- Integer/rate/percent parsing
- Status code expansion
- Boolean status conversion
"""

import pytest
from decimal import Decimal
from datetime import date

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DateType, DecimalType, IntegerType
)

import sys
sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from utils.transformations import (
    parse_legacy_date,
    parse_legacy_timestamp,
    parse_legacy_amount,
    parse_legacy_integer,
    parse_legacy_rate,
    parse_legacy_percent,
    expand_status_code,
    status_to_boolean,
)
from config.pipeline_config import (
    LOAN_STATUS_MAP,
    BORROWER_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
)

# Explicit schema to handle nullable columns properly
STR_SCHEMA = StructType([StructField("val", StringType(), True)])


@pytest.fixture(scope="session")
def spark():
    """Create a local Spark session for testing."""
    return (
        SparkSession.builder
        .master("local[*]")
        .appName("pipeline-tests")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.sql.ansi.enabled", "false")
        .getOrCreate()
    )


# =============================================================================
# Date Parsing Tests
# =============================================================================

class TestDateParsing:
    """Verify MM/DD/YYYY → DateType conversion handles valid and edge cases."""

    def test_valid_date(self, spark):
        """Standard date should parse correctly."""
        df = spark.createDataFrame([("03/15/1978",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_date(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == date(1978, 3, 15)

    def test_null_date(self, spark):
        """Null input should return null, not crash."""
        df = spark.createDataFrame([(None,)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_date(F.col("val")).alias("parsed")).first()
        assert result["parsed"] is None

    def test_invalid_date_format(self, spark):
        """YYYY-MM-DD (wrong format) should return null."""
        df = spark.createDataFrame([("1978-03-15",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_date(F.col("val")).alias("parsed")).first()
        assert result["parsed"] is None

    def test_invalid_date_feb_30(self, spark):
        """Impossible date 02/30/1978 should return null."""
        df = spark.createDataFrame([("02/30/1978",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_date(F.col("val")).alias("parsed")).first()
        assert result["parsed"] is None

    def test_date_with_whitespace(self, spark):
        """Leading/trailing whitespace should be handled."""
        df = spark.createDataFrame([("  07/22/1985  ",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_date(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == date(1985, 7, 22)

    def test_empty_string_date(self, spark):
        """Empty string should return null."""
        df = spark.createDataFrame([("",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_date(F.col("val")).alias("parsed")).first()
        assert result["parsed"] is None


# =============================================================================
# Amount Parsing Tests
# =============================================================================

class TestAmountParsing:
    """Verify comma-separated amount strings parse to proper decimals."""

    def test_amount_with_commas(self, spark):
        """Standard comma-separated amount should parse."""
        df = spark.createDataFrame([("285,000",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_amount(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == Decimal("285000.00")

    def test_amount_with_decimals(self, spark):
        """Amount with cents should preserve precision."""
        df = spark.createDataFrame([("1,487.02",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_amount(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == Decimal("1487.02")

    def test_amount_with_dollar_sign(self, spark):
        """Dollar sign prefix should be stripped."""
        df = spark.createDataFrame([("$285,000",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_amount(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == Decimal("285000.00")

    def test_null_amount(self, spark):
        """Null amount should default to 0.00."""
        df = spark.createDataFrame([(None,)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_amount(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == Decimal("0.00")

    def test_zero_amount(self, spark):
        """Explicit zero string should parse to 0.00."""
        df = spark.createDataFrame([("0.00",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_amount(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == Decimal("0.00")

    def test_plain_integer_amount(self, spark):
        """Integer without commas should parse."""
        df = spark.createDataFrame([("50000",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_amount(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == Decimal("50000.00")

    def test_non_numeric_amount(self, spark):
        """Non-numeric value should fallback to 0.00."""
        df = spark.createDataFrame([("N/A",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_amount(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == Decimal("0.00")


# =============================================================================
# Integer Parsing Tests
# =============================================================================

class TestIntegerParsing:
    """Verify string → integer parsing for fields like term_months, credit_score."""

    def test_valid_integer(self, spark):
        """Normal integer string should parse."""
        df = spark.createDataFrame([("360",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_integer(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == 360

    def test_null_integer(self, spark):
        """Null should return null."""
        df = spark.createDataFrame([(None,)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_integer(F.col("val")).alias("parsed")).first()
        assert result["parsed"] is None

    def test_non_numeric_integer(self, spark):
        """Non-numeric string should return null."""
        df = spark.createDataFrame([("N/A",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_integer(F.col("val")).alias("parsed")).first()
        assert result["parsed"] is None

    def test_integer_with_whitespace(self, spark):
        """Whitespace should be trimmed before parsing."""
        df = spark.createDataFrame([(" 180 ",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_integer(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == 180


# =============================================================================
# Rate / Percent Parsing Tests
# =============================================================================

class TestRateParsing:
    """Verify interest rate and percentage parsing."""

    def test_valid_rate(self, spark):
        """Standard rate string should parse to decimal(5,3)."""
        df = spark.createDataFrame([("4.750",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_rate(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == Decimal("4.750")

    def test_valid_percent(self, spark):
        """Percentage string should parse to decimal(5,2)."""
        df = spark.createDataFrame([("82.5",)], schema=STR_SCHEMA)
        result = df.select(parse_legacy_percent(F.col("val")).alias("parsed")).first()
        assert result["parsed"] == Decimal("82.50")


# =============================================================================
# Status Code Expansion Tests
# =============================================================================

class TestStatusCodeExpansion:
    """Verify status code mapping for all entity types."""

    def test_loan_status_active(self, spark):
        """ACT should expand to ACTIVE for loans."""
        df = spark.createDataFrame([("ACT",)], schema=STR_SCHEMA)
        result = df.select(
            expand_status_code(F.col("val"), LOAN_STATUS_MAP).alias("expanded")
        ).first()
        assert result["expanded"] == "ACTIVE"

    def test_loan_status_delinquent(self, spark):
        """DLQ should expand to DELINQUENT."""
        df = spark.createDataFrame([("DLQ",)], schema=STR_SCHEMA)
        result = df.select(
            expand_status_code(F.col("val"), LOAN_STATUS_MAP).alias("expanded")
        ).first()
        assert result["expanded"] == "DELINQUENT"

    def test_unknown_status_passthrough(self, spark):
        """Unknown code should pass through as-is."""
        df = spark.createDataFrame([("XYZ",)], schema=STR_SCHEMA)
        result = df.select(
            expand_status_code(F.col("val"), LOAN_STATUS_MAP).alias("expanded")
        ).first()
        assert result["expanded"] == "XYZ"

    def test_borrower_status_inactive(self, spark):
        """INA should expand to INACTIVE for borrowers."""
        df = spark.createDataFrame([("INA",)], schema=STR_SCHEMA)
        result = df.select(
            expand_status_code(F.col("val"), BORROWER_STATUS_MAP).alias("expanded")
        ).first()
        assert result["expanded"] == "INACTIVE"

    def test_payment_type_regular(self, spark):
        """REG should expand to REGULAR."""
        df = spark.createDataFrame([("REG",)], schema=STR_SCHEMA)
        result = df.select(
            expand_status_code(F.col("val"), PAYMENT_TYPE_MAP).alias("expanded")
        ).first()
        assert result["expanded"] == "REGULAR"

    def test_payment_status_posted(self, spark):
        """PST should expand to POSTED."""
        df = spark.createDataFrame([("PST",)], schema=STR_SCHEMA)
        result = df.select(
            expand_status_code(F.col("val"), PAYMENT_STATUS_MAP).alias("expanded")
        ).first()
        assert result["expanded"] == "POSTED"

    def test_status_with_whitespace(self, spark):
        """Status codes with whitespace should still map correctly."""
        df = spark.createDataFrame([(" ACT ",)], schema=STR_SCHEMA)
        result = df.select(
            expand_status_code(F.col("val"), LOAN_STATUS_MAP).alias("expanded")
        ).first()
        assert result["expanded"] == "ACTIVE"


# =============================================================================
# Boolean Status Tests
# =============================================================================

class TestStatusToBoolean:
    """Verify ACT → true, others → false conversion for is_active."""

    def test_active_true(self, spark):
        """ACT should map to True."""
        df = spark.createDataFrame([("ACT",)], schema=STR_SCHEMA)
        result = df.select(status_to_boolean(F.col("val")).alias("active")).first()
        assert result["active"] is True

    def test_inactive_false(self, spark):
        """INA should map to False."""
        df = spark.createDataFrame([("INA",)], schema=STR_SCHEMA)
        result = df.select(status_to_boolean(F.col("val")).alias("active")).first()
        assert result["active"] is False

    def test_null_status_false(self, spark):
        """Null status should map to False."""
        df = spark.createDataFrame([(None,)], schema=STR_SCHEMA)
        result = df.select(status_to_boolean(F.col("val")).alias("active")).first()
        assert result["active"] is False
