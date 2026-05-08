"""
Core feature test cases for the CDW-to-Delta-Lake migration pipeline.

Tests cover:
  TC-01: Status code expansion (abbreviation -> full label)
  TC-02: Date parsing (MM/DD/YYYY string -> DateType)
  TC-03: Amount parsing (comma-separated string -> DecimalType)
  TC-04: Integer and rate parsing (string -> IntegerType / DecimalType)
  TC-05: Borrower transformation (full column mapping and type conversion)
  TC-06: Loan product transformation (status-to-boolean mapping)
  TC-07: Loan account FK resolution (borrower_id and product_id lookup)
  TC-08: Payment transformation (FK resolution + type/status expansion)
  TC-09: Payment component sum validation (total = principal + interest + escrow + late_fee)
  TC-10: Row count preservation (no records dropped during transformation)

Executed in a local PySpark environment with delta-spark.
"""

import sys
import os
import unittest
from decimal import Decimal
from datetime import date, datetime

from pyspark.sql import SparkSession, Row
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType,
    DecimalType, DateType, TimestampType, BooleanType,
)
from delta import configure_spark_with_delta_pip

# Add ingestion module to path so we can import utils and transform functions
INGESTION_DIR = os.path.join(os.path.dirname(__file__), "..", "ingestion")
sys.path.insert(0, os.path.abspath(INGESTION_DIR))

from utils import (
    BORROWER_STATUS_MAP,
    LOAN_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    PAYMENT_STATUS_MAP,
    PRODUCT_STATUS_MAP,
    PROPERTY_TYPE_MAP,
    expand_status_expr,
    expand_status_with_fallback,
    parse_date_expr,
    parse_timestamp_expr,
    parse_amount_expr,
    parse_int_expr,
    parse_rate_expr,
)


class SparkTestBase(unittest.TestCase):
    """Base class that manages a shared SparkSession for all tests."""

    spark = None

    @classmethod
    def setUpClass(cls):
        # Create a local Spark session with Delta support using configure_spark_with_delta_pip
        # to properly resolve Delta Lake JARs on the classpath
        builder = (
            SparkSession.builder
            .master("local[*]")
            .appName("CDW_Migration_Tests")
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
            .config("spark.sql.warehouse.dir", "/tmp/spark-warehouse-test")
            .config("spark.driver.extraJavaOptions", "-Dderby.system.home=/tmp/derby-test")
            .config("spark.sql.shuffle.partitions", "2")
        )
        cls.spark = configure_spark_with_delta_pip(builder).getOrCreate()
        cls.spark.sparkContext.setLogLevel("WARN")

    @classmethod
    def tearDownClass(cls):
        if cls.spark:
            cls.spark.stop()


# ======================================================================
# TC-01: Status Code Expansion
# ======================================================================
class TC01_StatusCodeExpansion(SparkTestBase):
    """Verify that legacy abbreviation codes are expanded to full labels."""

    def test_borrower_status_expansion(self):
        """ACT -> Active, INA -> Inactive for borrower status codes."""
        # Create test data with known abbreviation codes
        data = [("ACT",), ("INA",), ("  ACT ",), ("UNKNOWN",)]
        df = self.spark.createDataFrame(data, ["BORR_STAT_CD"])

        # Apply the expand_status_with_fallback function used by the borrower pipeline
        result_df = df.select(
            expand_status_with_fallback("BORR_STAT_CD", BORROWER_STATUS_MAP, "status")
        )
        results = [row.status for row in result_df.collect()]

        # Verify known codes are expanded and unknown codes are kept as-is (trimmed)
        self.assertEqual(results[0], "Active", "ACT should expand to Active")
        self.assertEqual(results[1], "Inactive", "INA should expand to Inactive")
        self.assertEqual(results[2], "Active", "Whitespace-padded ACT should expand to Active")
        self.assertEqual(results[3], "UNKNOWN", "Unknown code should be kept as-is (trimmed)")

    def test_loan_status_expansion(self):
        """ACT/CLO/DFT/FRB loan status codes expand correctly."""
        data = [("ACT",), ("CLO",), ("DFT",), ("FRB",)]
        df = self.spark.createDataFrame(data, ["LN_STAT_CD"])

        result_df = df.select(
            expand_status_with_fallback("LN_STAT_CD", LOAN_STATUS_MAP, "status")
        )
        results = [row.status for row in result_df.collect()]

        self.assertEqual(results[0], "Active")
        self.assertEqual(results[1], "Closed")
        self.assertEqual(results[2], "Default")
        self.assertEqual(results[3], "Forbearance")

    def test_payment_type_and_status_expansion(self):
        """Payment type codes (REG/EXT/PRT/PRE) and status codes (PST/REV/NSF/PND) expand correctly."""
        # Payment types
        type_data = [("REG",), ("EXT",), ("PRT",), ("PRE",)]
        type_df = self.spark.createDataFrame(type_data, ["PMT_TYP_CD"])
        type_results = [
            row.type for row in type_df.select(
                expand_status_with_fallback("PMT_TYP_CD", PAYMENT_TYPE_MAP, "type")
            ).collect()
        ]
        self.assertEqual(type_results, ["Regular", "Extra", "Partial", "Prepayment"])

        # Payment statuses
        status_data = [("PST",), ("REV",), ("NSF",), ("PND",)]
        status_df = self.spark.createDataFrame(status_data, ["PMT_STAT_CD"])
        status_results = [
            row.status for row in status_df.select(
                expand_status_with_fallback("PMT_STAT_CD", PAYMENT_STATUS_MAP, "status")
            ).collect()
        ]
        self.assertEqual(status_results, ["Posted", "Reversed", "NSF", "Pending"])


# ======================================================================
# TC-02: Date Parsing (MM/DD/YYYY -> DateType)
# ======================================================================
class TC02_DateParsing(SparkTestBase):
    """Verify MM/DD/YYYY strings are correctly parsed to DateType."""

    def test_valid_dates_parsed(self):
        """Standard MM/DD/YYYY dates should be parsed to DateType."""
        data = [("01/15/2023",), ("12/31/2020",), ("06/01/1999",)]
        df = self.spark.createDataFrame(data, ["BORR_DOB_DT"])

        result_df = df.select(parse_date_expr("BORR_DOB_DT", "date_of_birth"))
        results = [row.date_of_birth for row in result_df.collect()]

        self.assertEqual(results[0], date(2023, 1, 15))
        self.assertEqual(results[1], date(2020, 12, 31))
        self.assertEqual(results[2], date(1999, 6, 1))

    def test_invalid_dates_return_null(self):
        """Malformed date strings should return null instead of raising errors."""
        data = [("INVALID",), ("",), ("13/32/2023",)]
        df = self.spark.createDataFrame(data, ["BORR_DOB_DT"])

        result_df = df.select(parse_date_expr("BORR_DOB_DT", "date_of_birth"))
        results = [row.date_of_birth for row in result_df.collect()]

        # All invalid dates should produce null
        for i, result in enumerate(results):
            self.assertIsNone(result, f"Row {i} with invalid date should be None")

    def test_timestamp_parsing(self):
        """MM/DD/YYYY should also parse to TimestampType (midnight)."""
        data = [("03/25/2024",)]
        df = self.spark.createDataFrame(data, ["BORR_CRET_DT"])

        result_df = df.select(parse_timestamp_expr("BORR_CRET_DT", "created_at"))
        result = result_df.collect()[0].created_at

        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 3)
        self.assertEqual(result.day, 25)


# ======================================================================
# TC-03: Amount Parsing (comma-separated string -> DecimalType)
# ======================================================================
class TC03_AmountParsing(SparkTestBase):
    """Verify that comma-separated amount strings are parsed to DecimalType."""

    def test_amounts_with_commas(self):
        """Strings like '285,000.50' should be parsed to Decimal after stripping commas."""
        data = [("285,000.50",), ("1,234,567.89",), ("0.01",), ("1000",)]
        df = self.spark.createDataFrame(data, ["LN_ORIG_AMT"])

        result_df = df.select(parse_amount_expr("LN_ORIG_AMT", "original_amount"))
        results = [row.original_amount for row in result_df.collect()]

        self.assertEqual(results[0], Decimal("285000.50"))
        self.assertEqual(results[1], Decimal("1234567.89"))
        self.assertEqual(results[2], Decimal("0.01"))
        self.assertEqual(results[3], Decimal("1000.00"))

    def test_invalid_amounts_return_null(self):
        """Non-numeric strings should return null instead of raising errors."""
        data = [("NOT_A_NUMBER",), ("",)]
        df = self.spark.createDataFrame(data, ["LN_ORIG_AMT"])

        result_df = df.select(parse_amount_expr("LN_ORIG_AMT", "original_amount"))
        results = [row.original_amount for row in result_df.collect()]

        for i, result in enumerate(results):
            self.assertIsNone(result, f"Row {i} with invalid amount should be None")


# ======================================================================
# TC-04: Integer and Rate Parsing
# ======================================================================
class TC04_IntegerAndRateParsing(SparkTestBase):
    """Verify string-to-integer and string-to-rate conversions."""

    def test_integer_parsing(self):
        """String integers should cast to IntegerType correctly."""
        data = [("720",), ("0",), ("850",)]
        df = self.spark.createDataFrame(data, ["BORR_CRDT_SCR"])

        result_df = df.select(parse_int_expr("BORR_CRDT_SCR", "credit_score"))
        results = [row.credit_score for row in result_df.collect()]

        self.assertEqual(results[0], 720)
        self.assertEqual(results[1], 0)
        self.assertEqual(results[2], 850)

    def test_invalid_integer_returns_null(self):
        """Non-numeric strings should return null for integer parsing."""
        data = [("ABC",), ("",)]
        df = self.spark.createDataFrame(data, ["BORR_CRDT_SCR"])

        result_df = df.select(parse_int_expr("BORR_CRDT_SCR", "credit_score"))
        results = [row.credit_score for row in result_df.collect()]

        for result in results:
            self.assertIsNone(result)

    def test_rate_parsing(self):
        """Interest rate strings like '5.250' should parse to Decimal(5,3)."""
        data = [("5.250",), ("3.750",), ("0.000",)]
        df = self.spark.createDataFrame(data, ["LN_INT_RT"])

        result_df = df.select(parse_rate_expr("LN_INT_RT", "interest_rate"))
        results = [row.interest_rate for row in result_df.collect()]

        self.assertEqual(results[0], Decimal("5.250"))
        self.assertEqual(results[1], Decimal("3.750"))
        self.assertEqual(results[2], Decimal("0.000"))


# ======================================================================
# TC-05: Borrower Transformation (full column mapping)
# ======================================================================
class TC05_BorrowerTransformation(SparkTestBase):
    """Verify that the borrower transform function maps all columns correctly."""

    def test_full_borrower_transform(self):
        """All legacy CDW_BORR_MSTR columns should map to modern borrower schema."""
        from ingest_borrowers import transform

        # Create a sample legacy borrower record with all required columns
        data = [(
            "B001", "John", "Doe", "M", "HASH123",
            "05/20/1985", "123 Main St", "Apt 4", "Springfield",
            "IL", "62701", "555-0100", "john@example.com",
            "720", "EMPLOYED", "85,000.00", "ACT",
            "01/10/2020", "03/15/2024", "PRM"
        )]
        columns = [
            "BORR_ID", "BORR_FST_NM", "BORR_LST_NM", "BORR_MID_INIT",
            "BORR_SSN_ENCR", "BORR_DOB_DT", "BORR_ADDR_LN1", "BORR_ADDR_LN2",
            "BORR_CTY_NM", "BORR_ST_CD", "BORR_ZIP_CD", "BORR_PH_NBR",
            "BORR_EMAIL_ADDR", "BORR_CRDT_SCR", "BORR_EMP_STAT",
            "BORR_ANN_INCM", "BORR_STAT_CD", "BORR_CRET_DT",
            "BORR_UPDT_DT", "BORR_REC_TYP"
        ]
        df = self.spark.createDataFrame(data, columns)

        result = transform(df)
        row = result.collect()[0]

        # Verify column renames
        self.assertEqual(row.external_id, "B001")
        self.assertEqual(row.first_name, "John")
        self.assertEqual(row.last_name, "Doe")
        self.assertEqual(row.middle_initial, "M")

        # Verify type conversions
        self.assertEqual(row.date_of_birth, date(1985, 5, 20))
        self.assertEqual(row.credit_score, 720)
        self.assertEqual(row.annual_income, Decimal("85000.00"))

        # Verify status expansion
        self.assertEqual(row.status, "Active")

        # Verify _ingestion_ts is populated
        self.assertIsNotNone(row._ingestion_ts)


# ======================================================================
# TC-06: Loan Product Transformation (status-to-boolean)
# ======================================================================
class TC06_LoanProductTransformation(SparkTestBase):
    """Verify loan product transform maps status code to boolean is_active."""

    def test_product_status_to_boolean(self):
        """PROD_STAT_CD ACT -> True, INA -> False."""
        from ingest_loan_products import transform

        data = [
            ("FXD30", "30-Year Fixed", "FIXED", "360", "FIXED", "100,000.00", "999,999.00", "ACT", "01/01/2020", "12/31/2030"),
            ("ARM5", "5/1 ARM", "ARM", "60", "ADJUSTABLE", "50,000.00", "500,000.00", "INA", "06/15/2018", "06/15/2025"),
        ]
        columns = [
            "PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD", "PROD_TERM_MOS",
            "PROD_RT_TYP", "PROD_MIN_AMT", "PROD_MAX_AMT", "PROD_STAT_CD",
            "PROD_EFF_DT", "PROD_EXP_DT"
        ]
        df = self.spark.createDataFrame(data, columns)

        result = transform(df)
        rows = result.collect()

        # ACT should map to True
        self.assertTrue(rows[0].is_active, "ACT product status should map to True")
        # INA should map to False
        self.assertFalse(rows[1].is_active, "INA product status should map to False")

        # Verify other fields are transformed correctly
        self.assertEqual(rows[0].code, "FXD30")
        self.assertEqual(rows[0].term_months, 360)
        self.assertEqual(rows[0].min_amount, Decimal("100000.00"))


# ======================================================================
# TC-07: Loan Account FK Resolution
# ======================================================================
class TC07_LoanAccountFKResolution(SparkTestBase):
    """Verify loan account transform resolves borrower_id and product_id FKs."""

    def test_fk_resolution_with_matching_records(self):
        """Loan accounts should resolve BORR_ID -> borrower_id and PROD_CD -> product_id via lookup tables."""
        from ingest_loan_accounts import transform

        # Set up mock borrowers table
        borrower_data = [(1, "B001"), (2, "B002")]
        borrower_schema = StructType([
            StructField("borrower_id", IntegerType(), False),
            StructField("external_id", StringType(), False),
        ])
        borrowers_df = self.spark.createDataFrame(borrower_data, borrower_schema)
        borrowers_df.createOrReplaceTempView("test_borrowers")

        # Set up mock loan products table
        product_data = [(10, "FXD30"), (20, "ARM5")]
        product_schema = StructType([
            StructField("product_id", IntegerType(), False),
            StructField("code", StringType(), False),
        ])
        products_df = self.spark.createDataFrame(product_data, product_schema)
        products_df.createOrReplaceTempView("test_products")

        # Create a legacy loan account record
        loan_data = [(
            "LN001", "B001", "FXD30",
            "250,000.00", "245,000.00", "5.250", "360", "1,500.00",
            "01/15/2020", "01/15/2050", "02/15/2020", "06/15/2024",
            "ACT", "0", "3,500.00", "78.50",
            "123 Oak St", "Chicago", "IL", "60601", "SFR",
            "320,000.00", "01/15/2020", "05/01/2024"
        )]
        loan_columns = [
            "LN_ACCT_NBR", "BORR_ID", "PROD_CD",
            "LN_ORIG_AMT", "LN_CURR_BAL", "LN_INT_RT", "LN_TERM_MOS", "LN_PMT_AMT",
            "LN_ORIG_DT", "LN_MAT_DT", "LN_1ST_PMT_DT", "LN_NXT_PMT_DT",
            "LN_STAT_CD", "LN_DLQ_DAYS", "LN_ESCROW_BAL", "LN_LTV_PCT",
            "PROP_ADDR_LN1", "PROP_CTY_NM", "PROP_ST_CD", "PROP_ZIP_CD", "PROP_TYP_CD",
            "PROP_APRS_VAL", "LN_CRET_DT", "LN_UPDT_DT"
        ]
        loan_df = self.spark.createDataFrame(loan_data, loan_columns)

        # Run the transform with mock lookup tables
        result = transform(loan_df, self.spark, "test_borrowers", "test_products")
        row = result.collect()[0]

        # Verify FK resolution succeeded
        self.assertEqual(row.borrower_id, 1, "BORR_ID B001 should resolve to borrower_id 1")
        self.assertEqual(row.product_id, 10, "PROD_CD FXD30 should resolve to product_id 10")
        self.assertEqual(row.account_number, "LN001")
        self.assertEqual(row.status, "Active")
        self.assertEqual(row.property_type, "Single Family")

    def test_fk_resolution_with_orphan_records(self):
        """Loan accounts with unresolvable BORR_ID/PROD_CD should have null FK values (retained for review)."""
        from ingest_loan_accounts import transform

        # Empty lookup tables -> all FKs will be orphans
        empty_borrowers = self.spark.createDataFrame([], StructType([
            StructField("borrower_id", IntegerType(), False),
            StructField("external_id", StringType(), False),
        ]))
        empty_borrowers.createOrReplaceTempView("empty_borrowers")

        empty_products = self.spark.createDataFrame([], StructType([
            StructField("product_id", IntegerType(), False),
            StructField("code", StringType(), False),
        ]))
        empty_products.createOrReplaceTempView("empty_products")

        loan_data = [(
            "LN999", "B_MISSING", "PROD_MISSING",
            "100,000.00", "95,000.00", "4.500", "240", "900.00",
            "03/01/2021", "03/01/2041", "04/01/2021", "07/01/2024",
            "ACT", "0", "1,200.00", "65.00",
            "456 Elm St", "Denver", "CO", "80201", "CND",
            "155,000.00", "03/01/2021", "06/01/2024"
        )]
        loan_columns = [
            "LN_ACCT_NBR", "BORR_ID", "PROD_CD",
            "LN_ORIG_AMT", "LN_CURR_BAL", "LN_INT_RT", "LN_TERM_MOS", "LN_PMT_AMT",
            "LN_ORIG_DT", "LN_MAT_DT", "LN_1ST_PMT_DT", "LN_NXT_PMT_DT",
            "LN_STAT_CD", "LN_DLQ_DAYS", "LN_ESCROW_BAL", "LN_LTV_PCT",
            "PROP_ADDR_LN1", "PROP_CTY_NM", "PROP_ST_CD", "PROP_ZIP_CD", "PROP_TYP_CD",
            "PROP_APRS_VAL", "LN_CRET_DT", "LN_UPDT_DT"
        ]
        loan_df = self.spark.createDataFrame(loan_data, loan_columns)

        result = transform(loan_df, self.spark, "empty_borrowers", "empty_products")
        row = result.collect()[0]

        # Orphan records should be retained with null FKs (not dropped)
        self.assertIsNone(row.borrower_id, "Unresolvable BORR_ID should produce null borrower_id")
        self.assertIsNone(row.product_id, "Unresolvable PROD_CD should produce null product_id")
        self.assertEqual(row.account_number, "LN999", "Row should still be retained")


# ======================================================================
# TC-08: Payment Transformation (FK + type/status expansion)
# ======================================================================
class TC08_PaymentTransformation(SparkTestBase):
    """Verify payment transform resolves loan_account FK and expands type/status codes."""

    def test_payment_transform_with_fk_resolution(self):
        """Payment records should resolve LN_ACCT_NBR -> loan_account_id and expand type/status."""
        from ingest_payments import transform

        # Mock loan_accounts lookup table
        loan_data = [(100, "LN001"), (200, "LN002")]
        loan_schema = StructType([
            StructField("loan_account_id", IntegerType(), False),
            StructField("account_number", StringType(), False),
        ])
        loans_df = self.spark.createDataFrame(loan_data, loan_schema)
        loans_df.createOrReplaceTempView("test_loans")

        # Create a legacy payment record
        pmt_data = [(
            "PMT001", "LN001",
            "06/01/2024", "1,500.00", "800.00", "500.00", "150.00", "50.00",
            "REG", "PST",
            "05/28/2024", "06/01/2024",
            "06/01/2024", "06/01/2024"
        )]
        pmt_columns = [
            "PMT_SEQ_NBR", "LN_ACCT_NBR",
            "PMT_DT", "PMT_AMT", "PMT_PRIN_AMT", "PMT_INT_AMT",
            "PMT_ESCROW_AMT", "PMT_LATE_FEE",
            "PMT_TYP_CD", "PMT_STAT_CD",
            "PMT_RECV_DT", "PMT_PROC_DT",
            "PMT_CRET_DT", "PMT_UPDT_DT"
        ]
        pmt_df = self.spark.createDataFrame(pmt_data, pmt_columns)

        result = transform(pmt_df, self.spark, "test_loans")
        row = result.collect()[0]

        # Verify FK resolution
        self.assertEqual(row.loan_account_id, 100, "LN_ACCT_NBR LN001 should resolve to loan_account_id 100")

        # Verify type and status expansion
        self.assertEqual(row.type, "Regular", "REG should expand to Regular")
        self.assertEqual(row.status, "Posted", "PST should expand to Posted")

        # Verify amount parsing
        self.assertEqual(row.total_amount, Decimal("1500.00"))
        self.assertEqual(row.principal_amount, Decimal("800.00"))


# ======================================================================
# TC-09: Payment Component Sum Validation
# ======================================================================
class TC09_PaymentComponentSum(SparkTestBase):
    """Verify payment total equals sum of components (principal + interest + escrow + late_fee)."""

    def test_payment_components_sum_to_total(self):
        """Business rule: total_amount should equal principal + interest + escrow + late_fee."""
        from ingest_payments import transform

        # Mock loan_accounts for FK resolution
        loan_data = [(100, "LN001")]
        loan_schema = StructType([
            StructField("loan_account_id", IntegerType(), False),
            StructField("account_number", StringType(), False),
        ])
        loans_df = self.spark.createDataFrame(loan_data, loan_schema)
        loans_df.createOrReplaceTempView("test_loans_sum")

        # Payment where total = 800 + 500 + 150 + 50 = 1500
        pmt_data = [(
            "PMT_SUM1", "LN001",
            "07/01/2024", "1,500.00", "800.00", "500.00", "150.00", "50.00",
            "REG", "PST", "06/28/2024", "07/01/2024",
            "07/01/2024", "07/01/2024"
        )]
        pmt_columns = [
            "PMT_SEQ_NBR", "LN_ACCT_NBR",
            "PMT_DT", "PMT_AMT", "PMT_PRIN_AMT", "PMT_INT_AMT",
            "PMT_ESCROW_AMT", "PMT_LATE_FEE",
            "PMT_TYP_CD", "PMT_STAT_CD",
            "PMT_RECV_DT", "PMT_PROC_DT",
            "PMT_CRET_DT", "PMT_UPDT_DT"
        ]
        pmt_df = self.spark.createDataFrame(pmt_data, pmt_columns)

        result = transform(pmt_df, self.spark, "test_loans_sum")
        row = result.collect()[0]

        # Validate the business rule: total = principal + interest + escrow + late_fee
        component_sum = (
            (row.principal_amount or Decimal("0"))
            + (row.interest_amount or Decimal("0"))
            + (row.escrow_amount or Decimal("0"))
            + (row.late_fee or Decimal("0"))
        )
        tolerance = Decimal("0.01")
        diff = abs(row.total_amount - component_sum)
        self.assertLessEqual(
            diff, tolerance,
            f"Payment total ({row.total_amount}) should equal sum of components ({component_sum}), diff={diff}"
        )

    def test_payment_with_zero_components(self):
        """Payments with zero/null sub-amounts should still have a valid total."""
        from ingest_payments import transform

        # Re-use the same temp view for FK resolution
        loan_data = [(100, "LN001")]
        loan_schema = StructType([
            StructField("loan_account_id", IntegerType(), False),
            StructField("account_number", StringType(), False),
        ])
        loans_df = self.spark.createDataFrame(loan_data, loan_schema)
        loans_df.createOrReplaceTempView("test_loans_zero")

        # Payment with only principal, no interest/escrow/late_fee
        pmt_data = [(
            "PMT_ZERO", "LN001",
            "08/01/2024", "500.00", "500.00", "0.00", "0.00", "0.00",
            "PRT", "PST", "07/28/2024", "08/01/2024",
            "08/01/2024", "08/01/2024"
        )]
        pmt_columns = [
            "PMT_SEQ_NBR", "LN_ACCT_NBR",
            "PMT_DT", "PMT_AMT", "PMT_PRIN_AMT", "PMT_INT_AMT",
            "PMT_ESCROW_AMT", "PMT_LATE_FEE",
            "PMT_TYP_CD", "PMT_STAT_CD",
            "PMT_RECV_DT", "PMT_PROC_DT",
            "PMT_CRET_DT", "PMT_UPDT_DT"
        ]
        pmt_df = self.spark.createDataFrame(pmt_data, pmt_columns)

        result = transform(pmt_df, self.spark, "test_loans_zero")
        row = result.collect()[0]

        self.assertEqual(row.total_amount, Decimal("500.00"))
        self.assertEqual(row.principal_amount, Decimal("500.00"))
        self.assertEqual(row.interest_amount, Decimal("0.00"))


# ======================================================================
# TC-10: Row Count Preservation
# ======================================================================
class TC10_RowCountPreservation(SparkTestBase):
    """Verify that no records are dropped during transformation (row count in == row count out)."""

    def test_borrower_row_count_preserved(self):
        """Borrower transform should output exactly the same number of rows as input."""
        from ingest_borrowers import transform

        # Create multiple borrower records including edge cases
        data = [
            ("B001", "John", "Doe", "M", "H1", "05/20/1985", "Addr1", "", "City1", "IL", "62701", "555-0100", "a@b.com", "720", "EMP", "85,000.00", "ACT", "01/10/2020", "03/15/2024", "PRM"),
            ("B002", "Jane", "Smith", None, "H2", "INVALID_DATE", "Addr2", None, "City2", "CA", "90210", "555-0200", "c@d.com", "NOT_A_NUM", "UNEMP", "INVALID", "INA", "02/20/2021", "04/10/2024", "SEC"),
            ("B003", "Bob", "Wilson", "R", "H3", "12/01/2000", "Addr3", "Suite 5", "City3", "TX", "75001", "555-0300", "e@f.com", "650", "SELF", "120,500.75", "ACT", "06/05/2019", "01/20/2024", "PRM"),
        ]
        columns = [
            "BORR_ID", "BORR_FST_NM", "BORR_LST_NM", "BORR_MID_INIT",
            "BORR_SSN_ENCR", "BORR_DOB_DT", "BORR_ADDR_LN1", "BORR_ADDR_LN2",
            "BORR_CTY_NM", "BORR_ST_CD", "BORR_ZIP_CD", "BORR_PH_NBR",
            "BORR_EMAIL_ADDR", "BORR_CRDT_SCR", "BORR_EMP_STAT",
            "BORR_ANN_INCM", "BORR_STAT_CD", "BORR_CRET_DT",
            "BORR_UPDT_DT", "BORR_REC_TYP"
        ]
        df = self.spark.createDataFrame(data, columns)
        source_count = df.count()

        result = transform(df)
        target_count = result.count()

        # Row count must be preserved even when some fields have parse failures
        self.assertEqual(
            source_count, target_count,
            f"Row count mismatch: source={source_count}, target={target_count}. "
            "No records should be dropped during transformation."
        )

    def test_loan_product_row_count_preserved(self):
        """Loan product transform should preserve row count."""
        from ingest_loan_products import transform

        data = [
            ("FXD30", "30-Year Fixed", "FIXED", "360", "FIXED", "100,000.00", "999,999.00", "ACT", "01/01/2020", "12/31/2030"),
            ("ARM5", "5/1 ARM", "ARM", "BAD_INT", "ADJ", "INVALID", "500,000.00", "INA", "INVALID_DATE", "06/15/2025"),
            ("FXD15", "15-Year Fixed", "FIXED", "180", "FIXED", "75,000.00", "750,000.00", "ACT", "03/01/2019", "03/01/2035"),
        ]
        columns = [
            "PROD_CD", "PROD_DESC_TXT", "PROD_TYP_CD", "PROD_TERM_MOS",
            "PROD_RT_TYP", "PROD_MIN_AMT", "PROD_MAX_AMT", "PROD_STAT_CD",
            "PROD_EFF_DT", "PROD_EXP_DT"
        ]
        df = self.spark.createDataFrame(data, columns)
        source_count = df.count()

        result = transform(df)
        target_count = result.count()

        self.assertEqual(
            source_count, target_count,
            f"Row count mismatch: source={source_count}, target={target_count}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
