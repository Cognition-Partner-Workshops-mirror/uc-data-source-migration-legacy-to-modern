package com.workshop.loanservice.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for LegacyDataValidator covering each data anomaly type
 * identified in the DATA_ANOMALY_REPORT.md.
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANM-002: Numeric Strings Without Type Safety
    // =========================================================================

    @Nested
    @DisplayName("Amount Parsing (ANM-002)")
    class AmountParsing {

        @Test
        @DisplayName("Parses normal amount with commas")
        void parsesNormalAmountWithCommas() {
            BigDecimal result = validator.parseAmount("285,000", "LN_ORIG_AMT", "LN-TEST");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Parses decimal amount with commas")
        void parsesDecimalAmountWithCommas() {
            BigDecimal result = validator.parseAmount("1,487.02", "LN_PMT_AMT", "LN-TEST");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        @DisplayName("Returns ZERO for null input")
        void returnsZeroForNull() {
            BigDecimal result = validator.parseAmount(null, "LN_ORIG_AMT", "LN-TEST");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns ZERO for blank input")
        void returnsZeroForBlank() {
            BigDecimal result = validator.parseAmount("  ", "LN_ORIG_AMT", "LN-TEST");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns ZERO for garbage text instead of crashing")
        void returnsZeroForGarbageText() {
            BigDecimal result = validator.parseAmount("N/A", "BORR_CRDT_SCR", "B-TEST");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Handles dollar sign prefix")
        void handlesDollarSign() {
            BigDecimal result = validator.parseAmount("$285,000", "LN_ORIG_AMT", "LN-TEST");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Handles parenthesized negative amounts")
        void handlesParenthesizedNegative() {
            BigDecimal result = validator.parseAmount("(1,200.00)", "LN_CURR_BAL", "LN-TEST");
            assertEquals(new BigDecimal("-1200.00"), result);
        }

        @Test
        @DisplayName("Returns ZERO for placeholder text 'TBD'")
        void returnsZeroForPlaceholder() {
            BigDecimal result = validator.parseAmount("TBD", "LN_ORIG_AMT", "LN-TEST");
            assertEquals(BigDecimal.ZERO, result);
        }
    }

    @Nested
    @DisplayName("Decimal Parsing (ANM-002)")
    class DecimalParsing {

        @Test
        @DisplayName("Parses interest rate string")
        void parsesInterestRate() {
            BigDecimal result = validator.parseDecimal("5.250", "LN_INT_RT", "LN-TEST");
            assertEquals(new BigDecimal("5.250"), result);
        }

        @Test
        @DisplayName("Returns ZERO for null")
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal(null, "LN_INT_RT", "LN-TEST"));
        }

        @Test
        @DisplayName("Handles whitespace-padded value")
        void handlesWhitespace() {
            BigDecimal result = validator.parseDecimal("  5.250  ", "LN_INT_RT", "LN-TEST");
            assertEquals(new BigDecimal("5.250"), result);
        }

        @Test
        @DisplayName("Returns ZERO for non-numeric string")
        void returnsZeroForNonNumeric() {
            BigDecimal result = validator.parseDecimal("PENDING", "LN_INT_RT", "LN-TEST");
            assertEquals(BigDecimal.ZERO, result);
        }
    }

    @Nested
    @DisplayName("Integer Parsing (ANM-002)")
    class IntegerParsing {

        @Test
        @DisplayName("Parses credit score string")
        void parsesCreditScore() {
            Integer result = validator.parseInteger("745", "BORR_CRDT_SCR", "B-TEST");
            assertEquals(745, result);
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNull() {
            assertNull(validator.parseInteger(null, "BORR_CRDT_SCR", "B-TEST"));
        }

        @Test
        @DisplayName("Returns null for blank input")
        void returnsNullForBlank() {
            assertNull(validator.parseInteger("", "BORR_CRDT_SCR", "B-TEST"));
        }

        @Test
        @DisplayName("Returns null for non-numeric instead of crashing")
        void returnsNullForNonNumeric() {
            Integer result = validator.parseInteger("N/A", "BORR_CRDT_SCR", "B-TEST");
            assertNull(result);
        }

        @Test
        @DisplayName("Handles comma-formatted integer")
        void handlesCommaFormattedInteger() {
            Integer result = validator.parseInteger("92,500", "BORR_ANN_INCM", "B-TEST");
            assertEquals(92500, result);
        }
    }

    // =========================================================================
    // ANM-006: Date Strings Without Parsing or Validation
    // =========================================================================

    @Nested
    @DisplayName("Date Parsing (ANM-006)")
    class DateParsing {

        @Test
        @DisplayName("Parses MM/DD/YYYY to ISO format")
        void parsesLegacyDate() {
            String result = validator.parseLegacyDate("03/15/1978", "BORR_DOB_DT", "B-TEST");
            assertEquals("1978-03-15", result);
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNull() {
            assertNull(validator.parseLegacyDate(null, "BORR_DOB_DT", "B-TEST"));
        }

        @Test
        @DisplayName("Returns raw string for invalid date format")
        void returnsRawForInvalidFormat() {
            String result = validator.parseLegacyDate("2019-02-15", "LN_ORIG_DT", "LN-TEST");
            assertEquals("2019-02-15", result);
        }

        @Test
        @DisplayName("Returns raw string for impossible date")
        void returnsRawForImpossibleDate() {
            String result = validator.parseLegacyDate("13/32/2025", "PMT_DT", "PMT-TEST");
            assertEquals("13/32/2025", result);
        }

        @Test
        @DisplayName("Returns null for blank input")
        void returnsNullForBlank() {
            assertNull(validator.parseLegacyDate("", "BORR_DOB_DT", "B-TEST"));
        }
    }

    // =========================================================================
    // ANM-003: Missing NOT NULL Constraints — Null Name Handling
    // =========================================================================

    @Nested
    @DisplayName("Null-Safe Name Building (ANM-003)")
    class NullSafeNames {

        @Test
        @DisplayName("Builds full name with all parts present")
        void buildsFullName() {
            String result = validator.buildFullName("James", "R", "Mitchell");
            assertEquals("James R. Mitchell", result);
        }

        @Test
        @DisplayName("Builds full name without middle initial")
        void buildsFullNameNoMiddle() {
            String result = validator.buildFullName("Robert", null, "Williams");
            assertEquals("Robert Williams", result);
        }

        @Test
        @DisplayName("Uses [Unknown] for null first name instead of literal 'null'")
        void handlesNullFirstName() {
            String result = validator.buildFullName(null, "R", "Mitchell");
            assertEquals("[Unknown] R. Mitchell", result);
            assertFalse(result.contains("null"));
        }

        @Test
        @DisplayName("Uses [Unknown] for null last name")
        void handlesNullLastName() {
            String result = validator.buildFullName("James", "R", null);
            assertEquals("James R. [Unknown]", result);
            assertFalse(result.contains("null"));
        }

        @Test
        @DisplayName("Handles all null name parts")
        void handlesAllNullParts() {
            String result = validator.buildFullName(null, null, null);
            assertEquals("[Unknown] [Unknown]", result);
            assertFalse(result.contains("null"));
        }

        @Test
        @DisplayName("Builds simple name avoiding null literals")
        void buildsSimpleNameNullSafe() {
            String result = validator.buildSimpleName(null, "Mitchell");
            assertEquals("[Unknown] Mitchell", result);
            assertFalse(result.contains("null"));
        }
    }

    // =========================================================================
    // ANM-003: Null-Safe Address Building
    // =========================================================================

    @Nested
    @DisplayName("Null-Safe Address Building (ANM-003)")
    class NullSafeAddress {

        @Test
        @DisplayName("Builds full address with all parts")
        void buildsFullAddress() {
            String result = validator.buildAddress("742 Elm Street", "Springfield", "IL", "62701");
            assertEquals("742 Elm Street, Springfield, IL 62701", result);
        }

        @Test
        @DisplayName("Handles null city gracefully")
        void handlesNullCity() {
            String result = validator.buildAddress("742 Elm Street", null, "IL", "62701");
            assertEquals("742 Elm Street, IL 62701", result);
            assertFalse(result.contains("null"));
        }

        @Test
        @DisplayName("Returns [No Address] for all null parts")
        void handlesAllNullParts() {
            String result = validator.buildAddress(null, null, null, null);
            assertEquals("[No Address]", result);
        }
    }

    // =========================================================================
    // ANM-001: Payment Component Sum Mismatch
    // =========================================================================

    @Nested
    @DisplayName("Payment Component Sum Validation (ANM-001)")
    class PaymentSumValidation {

        @Test
        @DisplayName("Returns true when components sum to total")
        void validWhenComponentsMatchTotal() {
            boolean result = validator.validatePaymentComponentSum(
                    "PMT-TEST",
                    new BigDecimal("2924.18"),
                    new BigDecimal("1842.56"),
                    new BigDecimal("815.50"),
                    new BigDecimal("266.12"),
                    new BigDecimal("0.00"));
            assertTrue(result);
        }

        @Test
        @DisplayName("Returns false when components do NOT sum to total (ANM-001 actual data)")
        void invalidWhenComponentsMismatch() {
            boolean result = validator.validatePaymentComponentSum(
                    "PMT-2025120001",
                    new BigDecimal("1487.02"),
                    new BigDecimal("456.78"),
                    new BigDecimal("1074.69"),
                    new BigDecimal("355.55"),
                    new BigDecimal("0.00"));
            assertFalse(result);
        }

        @Test
        @DisplayName("Detects late fee not included in total (ANM-001 actual data)")
        void detectsLateFeeNotInTotal() {
            boolean result = validator.validatePaymentComponentSum(
                    "PMT-2025110003",
                    new BigDecimal("1077.05"),
                    new BigDecimal("295.82"),
                    new BigDecimal("781.23"),
                    new BigDecimal("0.00"),
                    new BigDecimal("47.50"));
            assertFalse(result);
        }
    }

    // =========================================================================
    // ANM-005: Delinquency Days Inconsistent with Loan Status
    // =========================================================================

    @Nested
    @DisplayName("Status-Delinquency Consistency (ANM-005)")
    class StatusDelinquencyConsistency {

        @Test
        @DisplayName("No warning for active loan with zero delinquency days")
        void noWarningForActiveWithZeroDays() {
            // Should not throw or error — just validates silently
            assertDoesNotThrow(() ->
                    validator.validateStatusDelinquencyConsistency("LN-TEST", "ACT", "0"));
        }

        @Test
        @DisplayName("Logs warning for active loan with positive delinquency days (does not throw)")
        void logsWarningForDelinquentActiveLoan() {
            assertDoesNotThrow(() ->
                    validator.validateStatusDelinquencyConsistency("LN-2018-00089", "ACT", "15"));
        }

        @Test
        @DisplayName("No warning for defaulted loan with delinquency days")
        void noWarningForDefaultedLoanWithDays() {
            assertDoesNotThrow(() ->
                    validator.validateStatusDelinquencyConsistency("LN-TEST", "DFT", "90"));
        }

        @Test
        @DisplayName("Handles null delinquency days gracefully")
        void handlesNullDelinquencyDays() {
            assertDoesNotThrow(() ->
                    validator.validateStatusDelinquencyConsistency("LN-TEST", "ACT", null));
        }
    }

    // =========================================================================
    // ANM-002: Status Code Validation
    // =========================================================================

    @Nested
    @DisplayName("Status Code Validation")
    class StatusCodeValidation {

        @Test
        @DisplayName("Recognizes valid loan statuses")
        void validLoanStatuses() {
            assertTrue(validator.isValidLoanStatus("ACT"));
            assertTrue(validator.isValidLoanStatus("CLO"));
            assertTrue(validator.isValidLoanStatus("DFT"));
            assertTrue(validator.isValidLoanStatus("FRB"));
        }

        @Test
        @DisplayName("Rejects unknown loan status")
        void rejectsUnknownLoanStatus() {
            assertFalse(validator.isValidLoanStatus("XYZ"));
            assertFalse(validator.isValidLoanStatus(null));
        }

        @Test
        @DisplayName("Recognizes valid payment statuses")
        void validPaymentStatuses() {
            assertTrue(validator.isValidPaymentStatus("PST"));
            assertTrue(validator.isValidPaymentStatus("REV"));
            assertTrue(validator.isValidPaymentStatus("NSF"));
            assertTrue(validator.isValidPaymentStatus("PND"));
        }

        @Test
        @DisplayName("Rejects unknown payment status")
        void rejectsUnknownPaymentStatus() {
            assertFalse(validator.isValidPaymentStatus("INVALID"));
            assertFalse(validator.isValidPaymentStatus(null));
        }

        @Test
        @DisplayName("Recognizes valid payment types")
        void validPaymentTypes() {
            assertTrue(validator.isValidPaymentType("REG"));
            assertTrue(validator.isValidPaymentType("EXT"));
            assertTrue(validator.isValidPaymentType("PRT"));
            assertTrue(validator.isValidPaymentType("PRE"));
        }

        @Test
        @DisplayName("Recognizes valid property types")
        void validPropertyTypes() {
            assertTrue(validator.isValidPropertyType("SFR"));
            assertTrue(validator.isValidPropertyType("CND"));
            assertTrue(validator.isValidPropertyType("MFR"));
            assertTrue(validator.isValidPropertyType("TWN"));
        }

        @Test
        @DisplayName("Recognizes valid borrower statuses")
        void validBorrowerStatuses() {
            assertTrue(validator.isValidBorrowerStatus("ACT"));
            assertTrue(validator.isValidBorrowerStatus("INA"));
            assertFalse(validator.isValidBorrowerStatus("DELETED"));
        }
    }

    // =========================================================================
    // ANM-009: Credit Score Validation
    // =========================================================================

    @Nested
    @DisplayName("Credit Score Validation (ANM-009)")
    class CreditScoreValidation {

        @Test
        @DisplayName("Returns valid credit score")
        void returnsValidScore() {
            assertEquals(745, validator.validateCreditScore("745", "B-TEST"));
        }

        @Test
        @DisplayName("Returns score even if out of range (with warning)")
        void returnsOutOfRangeScore() {
            Integer result = validator.validateCreditScore("200", "B-TEST");
            assertEquals(200, result);
        }

        @Test
        @DisplayName("Returns null for non-numeric credit score")
        void returnsNullForNonNumeric() {
            assertNull(validator.validateCreditScore("N/A", "B-TEST"));
        }

        @Test
        @DisplayName("Returns null for null credit score")
        void returnsNullForNull() {
            assertNull(validator.validateCreditScore(null, "B-TEST"));
        }
    }

    // =========================================================================
    // Helper Method Tests
    // =========================================================================

    @Nested
    @DisplayName("Safe String Helper")
    class SafeStringHelper {

        @Test
        @DisplayName("Returns value when non-null and non-blank")
        void returnsValueWhenPresent() {
            assertEquals("hello", validator.safeString("hello", "default"));
        }

        @Test
        @DisplayName("Returns fallback for null")
        void returnsFallbackForNull() {
            assertEquals("default", validator.safeString(null, "default"));
        }

        @Test
        @DisplayName("Returns fallback for blank")
        void returnsFallbackForBlank() {
            assertEquals("default", validator.safeString("  ", "default"));
        }
    }
}
