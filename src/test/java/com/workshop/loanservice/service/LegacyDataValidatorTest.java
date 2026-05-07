package com.workshop.loanservice.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =====================================================================
    // ANO-001: Numeric fields stored as VARCHAR with commas
    // =====================================================================
    @Nested
    class AmountParsing {

        @Test
        void parsesCommaFormattedAmount() {
            assertEquals(new BigDecimal("285000"),
                    validator.parseAmount("285,000", "origAmt", "LN-001"));
        }

        @Test
        void parsesAmountWithCommasAndDecimals() {
            assertEquals(new BigDecimal("271432.56"),
                    validator.parseAmount("271,432.56", "currBal", "LN-001"));
        }

        @Test
        void parsesAmountWithoutCommas() {
            assertEquals(new BigDecimal("0"),
                    validator.parseAmount("0", "minAmt", "PROD-001"));
        }

        @Test
        void returnsZeroForNullAmount() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount(null, "amt", "X"));
        }

        @Test
        void returnsZeroForBlankAmount() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("  ", "amt", "X"));
        }

        @Test
        void returnsZeroForCurrencySymbol() {
            assertEquals(new BigDecimal("285000"),
                    validator.parseAmount("$285,000", "amt", "X"));
        }

        @Test
        void returnsZeroForAlphabeticText() {
            assertEquals(BigDecimal.ZERO,
                    validator.parseAmount("N/A", "amt", "X"));
        }

        @Test
        void returnsZeroForCompletelyInvalid() {
            assertEquals(BigDecimal.ZERO,
                    validator.parseAmount("abc.def", "amt", "X"));
        }
    }

    @Nested
    class DecimalParsing {

        @Test
        void parsesInterestRate() {
            assertEquals(new BigDecimal("5.250"),
                    validator.parseDecimal("5.250", "intRate", "LN-001"));
        }

        @Test
        void parsesWhitespacePadded() {
            assertEquals(new BigDecimal("4.750"),
                    validator.parseDecimal("  4.750  ", "intRate", "LN-001"));
        }

        @Test
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO,
                    validator.parseDecimal("VARIABLE", "intRate", "LN-001"));
        }

        @Test
        void handlesCommasInDecimal() {
            assertEquals(new BigDecimal("1234.56"),
                    validator.parseDecimal("1,234.56", "val", "X"));
        }
    }

    @Nested
    class IntegerParsing {

        @Test
        void parsesPlainInteger() {
            assertEquals(360, validator.parseInteger("360", "termMos", "LN-001"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseInteger(null, "field", "X"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseInteger("", "field", "X"));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.parseInteger("ABC", "field", "X"));
        }

        @Test
        void handlesCommasInInteger() {
            assertEquals(1000, validator.parseInteger("1,000", "field", "X"));
        }
    }

    // =====================================================================
    // ANO-010: Credit score range validation
    // =====================================================================
    @Nested
    class CreditScoreValidation {

        @Test
        void acceptsValidScore() {
            assertEquals(745, validator.parseCreditScore("745", "B-001"));
        }

        @Test
        void acceptsMinBoundary() {
            assertEquals(300, validator.parseCreditScore("300", "B-001"));
        }

        @Test
        void acceptsMaxBoundary() {
            assertEquals(850, validator.parseCreditScore("850", "B-001"));
        }

        @Test
        void rejectsScoreBelowRange() {
            assertNull(validator.parseCreditScore("100", "B-001"));
        }

        @Test
        void rejectsScoreAboveRange() {
            assertNull(validator.parseCreditScore("999", "B-001"));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.parseCreditScore("N/A", "B-001"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseCreditScore(null, "B-001"));
        }
    }

    // =====================================================================
    // ANO-002: Date format validation and conversion
    // =====================================================================
    @Nested
    class DateParsing {

        @Test
        void parsesLegacyDateToIso() {
            assertEquals("2019-02-15",
                    validator.parseLegacyDate("02/15/2019", "origDt", "LN-001"));
        }

        @Test
        void parsesMonthDayYearFormat() {
            assertEquals("1978-03-15",
                    validator.parseLegacyDate("03/15/1978", "dob", "B-001"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseLegacyDate(null, "dt", "X"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseLegacyDate("  ", "dt", "X"));
        }

        @Test
        void returnsNullForIsoFormat() {
            assertNull(validator.parseLegacyDate("2025-01-15", "dt", "X"));
        }

        @Test
        void returnsNullForGarbage() {
            assertNull(validator.parseLegacyDate("TBD", "dt", "X"));
        }

        @Test
        void returnsNullForInvalidDate() {
            assertNull(validator.parseLegacyDate("13/32/2025", "dt", "X"));
        }

        @Test
        void returnsNullForZeroDate() {
            assertNull(validator.parseLegacyDate("00/00/0000", "dt", "X"));
        }
    }

    // =====================================================================
    // ANO-005 / ANO-006: Null and required field validation
    // =====================================================================
    @Nested
    class RequiredFieldValidation {

        @Test
        void returnsValueWhenPresent() {
            assertEquals("James",
                    validator.requireNonBlank("James", "firstName", "B-001", "Unknown"));
        }

        @Test
        void returnsFallbackForNull() {
            assertEquals("Unknown",
                    validator.requireNonBlank(null, "firstName", "B-001", "Unknown"));
        }

        @Test
        void returnsFallbackForBlank() {
            assertEquals("Unknown",
                    validator.requireNonBlank("  ", "firstName", "B-001", "Unknown"));
        }

        @Test
        void returnsFallbackForEmpty() {
            assertEquals("Unknown",
                    validator.requireNonBlank("", "firstName", "B-001", "Unknown"));
        }
    }

    // =====================================================================
    // ANO-003: Referential integrity / orphaned records
    // =====================================================================
    @Nested
    class ReferentialIntegrity {

        @Test
        void returnsTrueWhenReferenceExists() {
            assertTrue(validator.validateReference("product", "prodCd", "FXD30", "LN-001"));
        }

        @Test
        void returnsFalseWhenReferenceIsNull() {
            assertFalse(validator.validateReference(null, "prodCd", "BADCODE", "LN-001"));
        }
    }

    // =====================================================================
    // ANO-007: Payment component sum validation
    // =====================================================================
    @Nested
    class PaymentSumValidation {

        @Test
        void noWarningWhenComponentsSumCorrectly() {
            // 2,924.18 = 1,842.56 + 815.50 + 266.12 + 0.00
            assertDoesNotThrow(() -> validator.validatePaymentSum(
                    new BigDecimal("2924.18"),
                    new BigDecimal("1842.56"),
                    new BigDecimal("815.50"),
                    new BigDecimal("266.12"),
                    new BigDecimal("0.00"),
                    "PMT-OK"));
        }

        @Test
        void detectsMismatchedPaymentComponents() {
            // From seed data PMT-2025120001: total=1487.02 but components sum to 1887.02
            assertDoesNotThrow(() -> validator.validatePaymentSum(
                    new BigDecimal("1487.02"),
                    new BigDecimal("456.78"),
                    new BigDecimal("1074.69"),
                    new BigDecimal("355.55"),
                    new BigDecimal("0.00"),
                    "PMT-2025120001"));
        }

        @Test
        void detectsLateFeeDiscrepancy() {
            // From seed data PMT-2025110003: total=1077.05 but components sum to 1124.55
            assertDoesNotThrow(() -> validator.validatePaymentSum(
                    new BigDecimal("1077.05"),
                    new BigDecimal("295.82"),
                    new BigDecimal("781.23"),
                    new BigDecimal("0.00"),
                    new BigDecimal("47.50"),
                    "PMT-2025110003"));
        }
    }

    // =====================================================================
    // ANO-008: Delinquency / status consistency
    // =====================================================================
    @Nested
    class DelinquencyConsistency {

        @Test
        void noWarningForActiveWithZeroDays() {
            assertDoesNotThrow(() ->
                    validator.validateDelinquencyConsistency("ACT", 0, "LN-001"));
        }

        @Test
        void warnsForActiveWithPositiveDays() {
            assertDoesNotThrow(() ->
                    validator.validateDelinquencyConsistency("ACT", 15, "LN-018-00089"));
        }

        @Test
        void noWarningForDefaultWithPositiveDays() {
            assertDoesNotThrow(() ->
                    validator.validateDelinquencyConsistency("DFT", 90, "LN-001"));
        }

        @Test
        void handlesNullDelinquencyDays() {
            assertDoesNotThrow(() ->
                    validator.validateDelinquencyConsistency("ACT", null, "LN-001"));
        }
    }
}
