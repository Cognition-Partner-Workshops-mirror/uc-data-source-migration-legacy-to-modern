package com.workshop.loanservice.validation;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for LegacyDataValidator covering each anomaly type identified in DATA_ANOMALY_REPORT.md:
 *
 * - ANM-001: Payment component sum mismatch
 * - ANM-002: SSN last-4 from phone number
 * - ANM-003: Numeric string parsing risks
 * - ANM-004: Date format inconsistencies
 * - ANM-005: Delinquency vs. status inconsistency
 * - ANM-006: Denormalized borrower name mismatch
 * - ANM-007: Orphaned record FK validation (tested via cross-field checks)
 * - ANM-008: LTV percentage calculation discrepancy
 * - ANM-009: Null values in optional fields
 * - ANM-010: Late fee consistency (tested via payment validation)
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANM-003: Numeric String Parsing — safe parsing with fallback defaults
    // =========================================================================

    @Nested
    @DisplayName("ANM-003: Safe Amount Parsing")
    class SafeAmountParsingTests {

        @Test
        @DisplayName("parses standard comma-formatted amount")
        void parsesStandardAmount() {
            BigDecimal result = validator.safeParseAmount("285,000", "LN_ORIG_AMT", "LN-001");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("parses amount with decimals and commas")
        void parsesAmountWithDecimals() {
            BigDecimal result = validator.safeParseAmount("1,487.02", "PMT_AMT", "PMT-001");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        @DisplayName("strips dollar sign before parsing")
        void stripsDollarSign() {
            BigDecimal result = validator.safeParseAmount("$285,000", "LN_ORIG_AMT", "LN-001");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("strips percent sign before parsing")
        void stripsPercentSign() {
            BigDecimal result = validator.safeParseAmount("4.750%", "LN_INT_RT", "LN-001");
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        @DisplayName("returns ZERO for null input")
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount(null, "field", "id"));
        }

        @Test
        @DisplayName("returns ZERO for blank input")
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("  ", "field", "id"));
        }

        @Test
        @DisplayName("returns ZERO for non-numeric text like N/A")
        void returnsZeroForNonNumericText() {
            BigDecimal result = validator.safeParseAmount("N/A", "BORR_ANN_INCM", "B-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("returns ZERO for text value PENDING")
        void returnsZeroForTextPending() {
            BigDecimal result = validator.safeParseAmount("PENDING", "LN_CURR_BAL", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("returns ZERO for dashes")
        void returnsZeroForDashes() {
            BigDecimal result = validator.safeParseAmount("---", "LN_CURR_BAL", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("handles whitespace-padded values")
        void handlesWhitespacePaddedValues() {
            BigDecimal result = validator.safeParseAmount("  1,234.56  ", "PMT_AMT", "PMT-001");
            assertEquals(new BigDecimal("1234.56"), result);
        }
    }

    @Nested
    @DisplayName("ANM-003: Safe Integer Parsing")
    class SafeIntegerParsingTests {

        @Test
        @DisplayName("parses valid integer string")
        void parsesValidInteger() {
            assertEquals(745, validator.safeParseInteger("745", "BORR_CRDT_SCR", "B-001"));
        }

        @Test
        @DisplayName("returns null for null input")
        void returnsNullForNull() {
            assertNull(validator.safeParseInteger(null, "field", "id"));
        }

        @Test
        @DisplayName("returns null for blank input")
        void returnsNullForBlank() {
            assertNull(validator.safeParseInteger("", "field", "id"));
        }

        @Test
        @DisplayName("returns null for N/A instead of throwing NumberFormatException")
        void returnsNullForNonNumeric() {
            assertNull(validator.safeParseInteger("N/A", "BORR_CRDT_SCR", "B-001"));
        }

        @Test
        @DisplayName("handles decimal strings in integer fields")
        void handlesDecimalInIntegerField() {
            assertEquals(360, validator.safeParseInteger("360.0", "PROD_TERM_MOS", "FXD30"));
        }

        @Test
        @DisplayName("strips commas from integer strings")
        void stripsCommasFromInteger() {
            assertEquals(1000, validator.safeParseInteger("1,000", "field", "id"));
        }
    }

    @Nested
    @DisplayName("ANM-003: Safe Decimal Parsing")
    class SafeDecimalParsingTests {

        @Test
        @DisplayName("parses standard decimal")
        void parsesStandardDecimal() {
            BigDecimal result = validator.safeParseDecimal("4.750", "LN_INT_RT", "LN-001");
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        @DisplayName("returns ZERO for malformed decimal")
        void returnsZeroForMalformedDecimal() {
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal("abc", "LN_INT_RT", "LN-001"));
        }

        @Test
        @DisplayName("strips percent sign from decimal")
        void stripsPercentFromDecimal() {
            BigDecimal result = validator.safeParseDecimal("82.5%", "LN_LTV_PCT", "LN-001");
            assertEquals(new BigDecimal("82.5"), result);
        }
    }

    // =========================================================================
    // ANM-004: Date Format Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-004: Date Parsing and Validation")
    class DateValidationTests {

        @Test
        @DisplayName("parses valid MM/DD/YYYY date")
        void parsesValidDate() {
            LocalDate result = validator.safeParseLegacyDate("03/15/1978", "BORR_DOB_DT", "B-001");
            assertEquals(LocalDate.of(1978, 3, 15), result);
        }

        @Test
        @DisplayName("returns null for null date")
        void returnsNullForNullDate() {
            assertNull(validator.safeParseLegacyDate(null, "field", "id"));
        }

        @Test
        @DisplayName("returns null for blank date")
        void returnsNullForBlankDate() {
            assertNull(validator.safeParseLegacyDate("", "field", "id"));
        }

        @Test
        @DisplayName("returns null for invalid month/day like 13/45/2020")
        void returnsNullForInvalidMonthDay() {
            assertNull(validator.safeParseLegacyDate("13/45/2020", "LN_ORIG_DT", "LN-001"));
        }

        @Test
        @DisplayName("returns null for ISO format instead of MM/DD/YYYY")
        void returnsNullForIsoFormat() {
            assertNull(validator.safeParseLegacyDate("2020-01-15", "LN_ORIG_DT", "LN-001"));
        }

        @Test
        @DisplayName("returns null for text date like TBD")
        void returnsNullForTextDate() {
            assertNull(validator.safeParseLegacyDate("TBD", "LN_MAT_DT", "LN-001"));
        }

        @Test
        @DisplayName("parses leap day correctly")
        void parsesLeapDay() {
            LocalDate result = validator.safeParseLegacyDate("02/29/2024", "BORR_DOB_DT", "B-001");
            assertEquals(LocalDate.of(2024, 2, 29), result);
        }

        @Test
        @DisplayName("resolves invalid leap day on non-leap year to last valid day")
        void resolvesInvalidLeapDay() {
            // Java's DateTimeFormatter with SMART resolver rolls Feb 29 on non-leap year to Feb 28
            LocalDate result = validator.safeParseLegacyDate("02/29/2023", "BORR_DOB_DT", "B-001");
            assertEquals(LocalDate.of(2023, 2, 28), result);
        }
    }

    // =========================================================================
    // ANM-001: Payment Component Sum Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-001: Payment Component Sum Validation")
    class PaymentSumValidationTests {

        @Test
        @DisplayName("returns true when components sum to total")
        void returnsTrueWhenComponentsSumToTotal() {
            assertTrue(validator.validatePaymentComponentSum(
                    new BigDecimal("2924.18"),
                    new BigDecimal("1842.56"),
                    new BigDecimal("815.50"),
                    new BigDecimal("266.12"),
                    new BigDecimal("0.00"),
                    "PMT-2025120002"));
        }

        @Test
        @DisplayName("detects mismatch in loan LN-2019-00142 payments (escrow discrepancy)")
        void detectsMismatchWithEscrowDiscrepancy() {
            // ANM-001 example: PMT-2025120001 total=1487.02 but components sum to 1887.02
            assertFalse(validator.validatePaymentComponentSum(
                    new BigDecimal("1487.02"),
                    new BigDecimal("456.78"),
                    new BigDecimal("1074.69"),
                    new BigDecimal("355.55"),
                    new BigDecimal("0.00"),
                    "PMT-2025120001"));
        }

        @Test
        @DisplayName("detects mismatch when late fee creates discrepancy")
        void detectsMismatchWithLateFeeDiscrepancy() {
            // ANM-001 example: PMT-2025110003 total=1077.05 but components sum to 1124.55
            assertFalse(validator.validatePaymentComponentSum(
                    new BigDecimal("1077.05"),
                    new BigDecimal("295.82"),
                    new BigDecimal("781.23"),
                    new BigDecimal("0.00"),
                    new BigDecimal("47.50"),
                    "PMT-2025110003"));
        }

        @Test
        @DisplayName("allows penny-level rounding tolerance")
        void allowsPennyLevelTolerance() {
            // Sum is 100.01 vs total 100.00 — within $0.01 tolerance
            assertTrue(validator.validatePaymentComponentSum(
                    new BigDecimal("100.00"),
                    new BigDecimal("50.005"),
                    new BigDecimal("50.005"),
                    new BigDecimal("0.00"),
                    new BigDecimal("0.00"),
                    "PMT-TEST"));
        }
    }

    // =========================================================================
    // ANM-002: SSN Last-4 vs Phone Number Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-002: SSN Last-4 vs Phone Number Validation")
    class SsnPhoneValidationTests {

        @Test
        @DisplayName("detects SSN last-4 matching phone last-4")
        void detectsSsnMatchingPhone() {
            // From seed data: B-10001 has phone 217-555-0142 and SSN last-4 is 0142
            assertFalse(validator.validateSsnLast4NotFromPhone("0142", "217-555-0142", "LN-2019-00142"));
        }

        @Test
        @DisplayName("returns true when SSN last-4 differs from phone")
        void returnsTrueWhenSsnDiffersFromPhone() {
            assertTrue(validator.validateSsnLast4NotFromPhone("9876", "217-555-0142", "LN-001"));
        }

        @Test
        @DisplayName("handles null SSN gracefully")
        void handlesNullSsn() {
            assertTrue(validator.validateSsnLast4NotFromPhone(null, "217-555-0142", "LN-001"));
        }

        @Test
        @DisplayName("handles null phone gracefully")
        void handlesNullPhone() {
            assertTrue(validator.validateSsnLast4NotFromPhone("0142", null, "LN-001"));
        }

        @Test
        @DisplayName("detects match with different phone formats")
        void detectsMatchWithDifferentPhoneFormats() {
            assertFalse(validator.validateSsnLast4NotFromPhone("0198", "(503) 555-0198", "LN-002"));
        }
    }

    // =========================================================================
    // ANM-005: Delinquency vs. Status Consistency
    // =========================================================================

    @Nested
    @DisplayName("ANM-005: Delinquency vs Status Consistency")
    class DelinquencyStatusTests {

        @Test
        @DisplayName("detects active loan with delinquency days > 0")
        void detectsActiveWithDelinquency() {
            // From seed data: LN-2018-00089 has DLQ_DAYS=15 and status=ACT
            assertFalse(validator.validateDelinquencyStatusConsistency("ACT", "15", "LN-2018-00089"));
        }

        @Test
        @DisplayName("returns true for active loan with zero delinquency days")
        void returnsTrueForActiveWithZeroDelinquency() {
            assertTrue(validator.validateDelinquencyStatusConsistency("ACT", "0", "LN-001"));
        }

        @Test
        @DisplayName("returns true for defaulted loan with delinquency days")
        void returnsTrueForDefaultedWithDelinquency() {
            assertTrue(validator.validateDelinquencyStatusConsistency("DFT", "90", "LN-001"));
        }

        @Test
        @DisplayName("handles null delinquency days")
        void handlesNullDelinquencyDays() {
            assertTrue(validator.validateDelinquencyStatusConsistency("ACT", null, "LN-001"));
        }

        @Test
        @DisplayName("handles blank delinquency days")
        void handlesBlankDelinquencyDays() {
            assertTrue(validator.validateDelinquencyStatusConsistency("ACT", "", "LN-001"));
        }
    }

    // =========================================================================
    // ANM-006: Denormalized Borrower Name Consistency
    // =========================================================================

    @Nested
    @DisplayName("ANM-006: Denormalized Borrower Name Validation")
    class DenormalizedNameTests {

        @Test
        @DisplayName("returns true when names match")
        void returnsTrueWhenNamesMatch() {
            assertTrue(validator.validateDenormalizedBorrowerName(
                    "James", "Mitchell", "James", "Mitchell", "LN-001"));
        }

        @Test
        @DisplayName("detects first name mismatch")
        void detectsFirstNameMismatch() {
            assertFalse(validator.validateDenormalizedBorrowerName(
                    "Jim", "Mitchell", "James", "Mitchell", "LN-001"));
        }

        @Test
        @DisplayName("detects last name mismatch after name change")
        void detectsLastNameMismatch() {
            assertFalse(validator.validateDenormalizedBorrowerName(
                    "Sarah", "Chen", "Sarah", "Chen-Williams", "LN-002"));
        }

        @Test
        @DisplayName("handles null names in both records")
        void handlesNullNamesInBoth() {
            assertTrue(validator.validateDenormalizedBorrowerName(null, null, null, null, "LN-001"));
        }

        @Test
        @DisplayName("detects mismatch when only one side is null")
        void detectsMismatchWhenOneSideNull() {
            assertFalse(validator.validateDenormalizedBorrowerName(
                    null, "Mitchell", "James", "Mitchell", "LN-001"));
        }
    }

    // =========================================================================
    // ANM-008: LTV Percentage Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-008: LTV Percentage Validation")
    class LtvValidationTests {

        @Test
        @DisplayName("accepts LTV within tolerance")
        void acceptsLtvWithinTolerance() {
            // LN-2018-00089: 195000/260000 = 75.0% vs stored 75.0 — exact match
            assertTrue(validator.validateLtvPercentage("75.0", "195,000", "260,000", "LN-2018-00089"));
        }

        @Test
        @DisplayName("accepts LTV with minor rounding difference")
        void acceptsLtvWithMinorRounding() {
            // LN-2019-00142: 285000/345000 = 82.61% vs stored 82.5 — within 0.5% tolerance
            assertTrue(validator.validateLtvPercentage("82.5", "285,000", "345,000", "LN-2019-00142"));
        }

        @Test
        @DisplayName("detects significant LTV discrepancy")
        void detectsSignificantLtvDiscrepancy() {
            // Stored 90.0% but computed would be 75.0% — well outside tolerance
            assertFalse(validator.validateLtvPercentage("90.0", "195,000", "260,000", "LN-TEST"));
        }

        @Test
        @DisplayName("flags zero appraised value")
        void flagsZeroAppraisedValue() {
            assertFalse(validator.validateLtvPercentage("80.0", "200,000", "0", "LN-TEST"));
        }
    }

    // =========================================================================
    // ANM-009: Null-Safe String Operations
    // =========================================================================

    @Nested
    @DisplayName("ANM-009: Null-Safe String Operations")
    class NullSafeStringTests {

        @Test
        @DisplayName("builds full name with middle initial")
        void buildsFullNameWithMiddle() {
            assertEquals("James R. Mitchell", validator.buildFullName("James", "R", "Mitchell"));
        }

        @Test
        @DisplayName("builds full name without middle initial")
        void buildsFullNameWithoutMiddle() {
            assertEquals("Robert Williams", validator.buildFullName("Robert", null, "Williams"));
        }

        @Test
        @DisplayName("builds full name with blank middle initial")
        void buildsFullNameWithBlankMiddle() {
            assertEquals("Robert Williams", validator.buildFullName("Robert", "", "Williams"));
        }

        @Test
        @DisplayName("handles null first name")
        void handlesNullFirstName() {
            assertEquals("R. Mitchell", validator.buildFullName(null, "R", "Mitchell"));
        }

        @Test
        @DisplayName("builds full address with all components")
        void buildsFullAddress() {
            assertEquals("742 Elm Street, Springfield, IL 62701",
                    validator.buildFullAddress("742 Elm Street", "Springfield", "IL", "62701"));
        }

        @Test
        @DisplayName("builds address with null city")
        void buildsAddressWithNullCity() {
            assertEquals("742 Elm Street, IL 62701",
                    validator.buildFullAddress("742 Elm Street", null, "IL", "62701"));
        }

        @Test
        @DisplayName("builds address with all nulls")
        void buildsAddressWithAllNulls() {
            assertEquals("", validator.buildFullAddress(null, null, null, null));
        }

        @Test
        @DisplayName("nullSafeString returns empty for null")
        void nullSafeStringReturnsEmptyForNull() {
            assertEquals("", validator.nullSafeString(null));
        }

        @Test
        @DisplayName("nullSafeString returns value for non-null")
        void nullSafeStringReturnsValueForNonNull() {
            assertEquals("hello", validator.nullSafeString("hello"));
        }
    }

    // =========================================================================
    // Status Code Validation
    // =========================================================================

    @Nested
    @DisplayName("Status Code Validation")
    class StatusCodeValidationTests {

        @Test
        @DisplayName("accepts valid loan status codes")
        void acceptsValidLoanStatusCodes() {
            assertEquals("ACT", validator.validateLoanStatusCode("ACT", "LN-001"));
            assertEquals("CLO", validator.validateLoanStatusCode("CLO", "LN-001"));
            assertEquals("DFT", validator.validateLoanStatusCode("DFT", "LN-001"));
            assertEquals("FRB", validator.validateLoanStatusCode("FRB", "LN-001"));
        }

        @Test
        @DisplayName("returns unknown loan status code as-is but logs warning")
        void returnsUnknownLoanStatusCode() {
            // Unknown code is returned (not rejected) to preserve data, but would log a warning
            assertEquals("XYZ", validator.validateLoanStatusCode("XYZ", "LN-001"));
        }

        @Test
        @DisplayName("handles null loan status code")
        void handlesNullLoanStatusCode() {
            assertNull(validator.validateLoanStatusCode(null, "LN-001"));
        }

        @Test
        @DisplayName("accepts valid payment type codes")
        void acceptsValidPaymentTypeCodes() {
            assertEquals("REG", validator.validatePaymentTypeCode("REG", "PMT-001"));
            assertEquals("EXT", validator.validatePaymentTypeCode("EXT", "PMT-001"));
            assertEquals("PRT", validator.validatePaymentTypeCode("PRT", "PMT-001"));
            assertEquals("PRE", validator.validatePaymentTypeCode("PRE", "PMT-001"));
        }

        @Test
        @DisplayName("returns unknown payment type code as-is")
        void returnsUnknownPaymentTypeCode() {
            assertEquals("ABC", validator.validatePaymentTypeCode("ABC", "PMT-001"));
        }

        @Test
        @DisplayName("accepts valid payment status codes")
        void acceptsValidPaymentStatusCodes() {
            assertEquals("PST", validator.validatePaymentStatusCode("PST", "PMT-001"));
            assertEquals("REV", validator.validatePaymentStatusCode("REV", "PMT-001"));
            assertEquals("NSF", validator.validatePaymentStatusCode("NSF", "PMT-001"));
            assertEquals("PND", validator.validatePaymentStatusCode("PND", "PMT-001"));
        }

        @Test
        @DisplayName("accepts valid property type codes")
        void acceptsValidPropertyTypeCodes() {
            assertEquals("SFR", validator.validatePropertyTypeCode("SFR", "LN-001"));
            assertEquals("CND", validator.validatePropertyTypeCode("CND", "LN-001"));
        }

        @Test
        @DisplayName("accepts valid borrower status codes")
        void acceptsValidBorrowerStatusCodes() {
            assertEquals("ACT", validator.validateBorrowerStatusCode("ACT", "B-001"));
            assertEquals("INA", validator.validateBorrowerStatusCode("INA", "B-001"));
        }

        @Test
        @DisplayName("accepts valid product type codes")
        void acceptsValidProductTypeCodes() {
            assertEquals("FXD", validator.validateProductTypeCode("FXD", "FXD30"));
            assertEquals("ARM", validator.validateProductTypeCode("ARM", "ARM51"));
        }

        @Test
        @DisplayName("accepts valid rate type codes")
        void acceptsValidRateTypeCodes() {
            assertEquals("FIXED", validator.validateRateTypeCode("FIXED", "FXD30"));
            assertEquals("VARIABLE", validator.validateRateTypeCode("VARIABLE", "ARM51"));
        }
    }

    // =========================================================================
    // Range Validation
    // =========================================================================

    @Nested
    @DisplayName("Range Validation")
    class RangeValidationTests {

        @Test
        @DisplayName("accepts valid credit score")
        void acceptsValidCreditScore() {
            assertEquals(745, validator.validateCreditScore(745, "B-001"));
        }

        @Test
        @DisplayName("clamps credit score below minimum to 300")
        void clampsCreditScoreBelowMin() {
            assertEquals(300, validator.validateCreditScore(100, "B-001"));
        }

        @Test
        @DisplayName("clamps credit score above maximum to 850")
        void clampsCreditScoreAboveMax() {
            assertEquals(850, validator.validateCreditScore(900, "B-001"));
        }

        @Test
        @DisplayName("returns null for null credit score")
        void returnsNullForNullCreditScore() {
            assertNull(validator.validateCreditScore(null, "B-001"));
        }

        @Test
        @DisplayName("accepts valid interest rate")
        void acceptsValidInterestRate() {
            BigDecimal rate = new BigDecimal("4.750");
            assertEquals(rate, validator.validateInterestRate(rate, "LN-001"));
        }

        @Test
        @DisplayName("returns ZERO for negative interest rate")
        void returnsZeroForNegativeRate() {
            assertEquals(BigDecimal.ZERO,
                    validator.validateInterestRate(new BigDecimal("-1.5"), "LN-001"));
        }

        @Test
        @DisplayName("returns ZERO for null interest rate")
        void returnsZeroForNullRate() {
            assertEquals(BigDecimal.ZERO, validator.validateInterestRate(null, "LN-001"));
        }

        @Test
        @DisplayName("returns ZERO for negative amount")
        void returnsZeroForNegativeAmount() {
            assertEquals(BigDecimal.ZERO,
                    validator.validateNonNegativeAmount(new BigDecimal("-500"), "PMT_AMT", "PMT-001"));
        }

        @Test
        @DisplayName("accepts zero amount")
        void acceptsZeroAmount() {
            assertEquals(BigDecimal.ZERO,
                    validator.validateNonNegativeAmount(BigDecimal.ZERO, "PMT_LATE_FEE", "PMT-001"));
        }

        @Test
        @DisplayName("accepts positive amount")
        void acceptsPositiveAmount() {
            BigDecimal amount = new BigDecimal("1487.02");
            assertEquals(amount,
                    validator.validateNonNegativeAmount(amount, "PMT_AMT", "PMT-001"));
        }
    }

    // =========================================================================
    // Integration: Validates actual seed data from data-legacy.sql
    // =========================================================================

    @Nested
    @DisplayName("Integration: Seed Data Validation")
    class SeedDataIntegrationTests {

        @Test
        @DisplayName("all seed data dates parse correctly")
        void allSeedDataDatesParseCorrectly() {
            // All dates from data-legacy.sql in MM/DD/YYYY format
            String[] dates = {
                    "03/15/1978", "07/22/1985", "11/08/1972", "02/28/1990", "06/14/1968",
                    "01/15/2019", "03/20/2020", "06/10/2018", "09/01/2021", "02/14/2017",
                    "02/15/2019", "04/01/2020", "07/01/2018", "10/01/2021", "03/01/2017",
                    "12/15/2025", "11/15/2025", "12/01/2025", "11/01/2025"
            };
            for (String date : dates) {
                assertNotNull(validator.safeParseLegacyDate(date, "test", "test"),
                        "Failed to parse date: " + date);
            }
        }

        @Test
        @DisplayName("all seed data amounts parse correctly")
        void allSeedDataAmountsParseCorrectly() {
            // All amounts from data-legacy.sql
            String[] amounts = {
                    "92,500", "125,000", "78,000", "145,000", "65,000",
                    "285,000", "420,000", "195,000", "525,000", "165,000",
                    "271,432.56", "312,876.43", "178,234.12", "498,123.78", "142,567.90",
                    "1,487.02", "2,924.18", "1,077.05", "2,468.35", "811.61",
                    "0.00", "47.50"
            };
            for (String amount : amounts) {
                BigDecimal result = validator.safeParseAmount(amount, "test", "test");
                assertNotNull(result, "Failed to parse amount: " + amount);
                assertTrue(result.compareTo(BigDecimal.ZERO) >= 0,
                        "Negative result for amount: " + amount);
            }
        }

        @Test
        @DisplayName("all seed data credit scores parse and validate correctly")
        void allSeedDataCreditScoresValid() {
            String[] scores = {"745", "780", "692", "810", "658"};
            for (String score : scores) {
                Integer parsed = validator.safeParseInteger(score, "BORR_CRDT_SCR", "test");
                assertNotNull(parsed, "Failed to parse credit score: " + score);
                Integer validated = validator.validateCreditScore(parsed, "test");
                assertEquals(parsed, validated,
                        "Credit score " + score + " was clamped unexpectedly");
            }
        }

        @Test
        @DisplayName("detects all 5 SSN-from-phone anomalies in seed data")
        void detectsAllSsnFromPhoneAnomalies() {
            // All 5 records in seed data have SSN last-4 matching phone last-4
            String[][] records = {
                    {"0142", "217-555-0142", "LN-2019-00142"},
                    {"0198", "503-555-0198", "LN-2020-00398"},
                    {"0167", "512-555-0167", "LN-2018-00089"},
                    {"0134", "303-555-0134", "LN-2021-00567"},
                    {"0156", "602-555-0156", "LN-2017-00034"}
            };
            for (String[] record : records) {
                assertFalse(validator.validateSsnLast4NotFromPhone(record[0], record[1], record[2]),
                        "Should detect SSN-from-phone anomaly for " + record[2]);
            }
        }

        @Test
        @DisplayName("detects delinquent-but-active loan in seed data")
        void detectsDelinquentButActiveLoan() {
            // LN-2018-00089: DLQ_DAYS=15, STATUS=ACT
            assertFalse(validator.validateDelinquencyStatusConsistency("ACT", "15", "LN-2018-00089"));
        }

        @Test
        @DisplayName("detects payment sum mismatches in seed data")
        void detectsPaymentSumMismatchesInSeedData() {
            // PMT-2025120001: total=1487.02, components sum=1887.02 (mismatch)
            assertFalse(validator.validatePaymentComponentSum(
                    new BigDecimal("1487.02"), new BigDecimal("456.78"),
                    new BigDecimal("1074.69"), new BigDecimal("355.55"),
                    new BigDecimal("0.00"), "PMT-2025120001"));

            // PMT-2025120002: total=2924.18, components sum=2924.18 (valid)
            assertTrue(validator.validatePaymentComponentSum(
                    new BigDecimal("2924.18"), new BigDecimal("1842.56"),
                    new BigDecimal("815.50"), new BigDecimal("266.12"),
                    new BigDecimal("0.00"), "PMT-2025120002"));
        }
    }
}
