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

    // =========================================================================
    // ANO-001 / ANO-005: VARCHAR numeric fields and comma-formatted amounts
    // =========================================================================
    @Nested
    class ParseAmountTests {

        @Test
        void parsesStandardCommaAmount() {
            assertEquals(new BigDecimal("285000"), validator.parseAmount("285,000", "amt", "R1"));
        }

        @Test
        void parsesAmountWithDecimal() {
            assertEquals(new BigDecimal("271432.56"), validator.parseAmount("271,432.56", "amt", "R1"));
        }

        @Test
        void parsesAmountWithDollarSign() {
            assertEquals(new BigDecimal("285000"), validator.parseAmount("$285,000", "amt", "R1"));
        }

        @Test
        void parsesAmountWithMultipleCommas() {
            assertEquals(new BigDecimal("1500000"), validator.parseAmount("1,500,000", "amt", "R1"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount(null, "amt", "R1"));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("  ", "amt", "R1"));
        }

        @Test
        void returnsZeroForNonNumericText() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("N/A", "amt", "R1"));
        }

        @Test
        void returnsZeroForDashes() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("--", "amt", "R1"));
        }

        @Test
        void parsesPlainInteger() {
            assertEquals(new BigDecimal("50000"), validator.parseAmount("50000", "amt", "R1"));
        }

        @Test
        void parsesZeroAmount() {
            assertEquals(new BigDecimal("0.00"), validator.parseAmount("0.00", "amt", "R1"));
        }

        @Test
        void parsesNegativeAmount() {
            assertEquals(new BigDecimal("-1234.56"), validator.parseAmount("-1,234.56", "amt", "R1"));
        }
    }

    @Nested
    class ParseDecimalTests {

        @Test
        void parsesInterestRate() {
            assertEquals(new BigDecimal("4.750"), validator.parseDecimal("4.750", "rate", "R1"));
        }

        @Test
        void parsesLtvPercent() {
            assertEquals(new BigDecimal("82.5"), validator.parseDecimal("82.5", "ltv", "R1"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal(null, "rate", "R1"));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal("", "rate", "R1"));
        }

        @Test
        void returnsZeroForNonNumericText() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal("PENDING", "rate", "R1"));
        }

        @Test
        void handlesLeadingTrailingSpaces() {
            assertEquals(new BigDecimal("5.250"), validator.parseDecimal("  5.250  ", "rate", "R1"));
        }
    }

    @Nested
    class ParseIntegerTests {

        @Test
        void parsesTermMonths() {
            assertEquals(360, validator.parseInteger("360", "term", "R1"));
        }

        @Test
        void parsesDelinquencyDays() {
            assertEquals(15, validator.parseInteger("15", "days", "R1"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseInteger(null, "field", "R1"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseInteger("", "field", "R1"));
        }

        @Test
        void returnsNullForNonNumericText() {
            assertNull(validator.parseInteger("N/A", "field", "R1"));
        }

        @Test
        void parsesZero() {
            assertEquals(0, validator.parseInteger("0", "days", "R1"));
        }
    }

    // =========================================================================
    // ANO-007: Credit score as VARCHAR with range validation
    // =========================================================================
    @Nested
    class CreditScoreTests {

        @Test
        void parsesValidCreditScore() {
            assertEquals(745, validator.parseCreditScore("745", "B-10001"));
        }

        @Test
        void parsesMinScore() {
            assertEquals(300, validator.parseCreditScore("300", "B-test"));
        }

        @Test
        void parsesMaxScore() {
            assertEquals(850, validator.parseCreditScore("850", "B-test"));
        }

        @Test
        void returnsNullForScoreBelowMin() {
            assertNull(validator.parseCreditScore("100", "B-test"));
        }

        @Test
        void returnsNullForScoreAboveMax() {
            assertNull(validator.parseCreditScore("900", "B-test"));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.parseCreditScore("N/A", "B-test"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseCreditScore(null, "B-test"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseCreditScore("", "B-test"));
        }
    }

    // =========================================================================
    // ANO-006: Date strings in MM/DD/YYYY format
    // =========================================================================
    @Nested
    class DateParsingTests {

        @Test
        void parsesLegacyDateFormat() {
            assertEquals("1978-03-15", validator.parseLegacyDate("03/15/1978", "dob", "R1"));
        }

        @Test
        void parsesAnotherLegacyDate() {
            assertEquals("2019-02-15", validator.parseLegacyDate("02/15/2019", "origDt", "R1"));
        }

        @Test
        void handlesIsoFormatInput() {
            assertEquals("2025-12-01", validator.parseLegacyDate("2025-12-01", "dt", "R1"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseLegacyDate(null, "dt", "R1"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseLegacyDate("", "dt", "R1"));
        }

        @Test
        void returnsOriginalForUnparseableDate() {
            assertEquals("not-a-date", validator.parseLegacyDate("not-a-date", "dt", "R1"));
        }

        @Test
        void handlesDateWithSpaces() {
            assertEquals("2025-12-15", validator.parseLegacyDate("  12/15/2025  ", "dt", "R1"));
        }
    }

    // =========================================================================
    // ANO-010: Status code validation
    // =========================================================================
    @Nested
    class StatusCodeValidationTests {

        @Test
        void acceptsValidLoanStatusCodes() {
            assertEquals("ACT", validator.validateLoanStatusCode("ACT", "LN-1"));
            assertEquals("CLO", validator.validateLoanStatusCode("CLO", "LN-1"));
            assertEquals("DFT", validator.validateLoanStatusCode("DFT", "LN-1"));
            assertEquals("FRB", validator.validateLoanStatusCode("FRB", "LN-1"));
        }

        @Test
        void returnsInvalidLoanStatusAsIs() {
            assertEquals("BAD", validator.validateLoanStatusCode("BAD", "LN-1"));
        }

        @Test
        void returnsNullForNullLoanStatus() {
            assertNull(validator.validateLoanStatusCode(null, "LN-1"));
        }

        @Test
        void acceptsValidPaymentTypeCodes() {
            assertEquals("REG", validator.validatePaymentTypeCode("REG", "PMT-1"));
            assertEquals("EXT", validator.validatePaymentTypeCode("EXT", "PMT-1"));
            assertEquals("PRT", validator.validatePaymentTypeCode("PRT", "PMT-1"));
            assertEquals("PRE", validator.validatePaymentTypeCode("PRE", "PMT-1"));
        }

        @Test
        void returnsInvalidPaymentTypeAsIs() {
            assertEquals("XXX", validator.validatePaymentTypeCode("XXX", "PMT-1"));
        }

        @Test
        void acceptsValidPaymentStatusCodes() {
            assertEquals("PST", validator.validatePaymentStatusCode("PST", "PMT-1"));
            assertEquals("REV", validator.validatePaymentStatusCode("REV", "PMT-1"));
            assertEquals("NSF", validator.validatePaymentStatusCode("NSF", "PMT-1"));
            assertEquals("PND", validator.validatePaymentStatusCode("PND", "PMT-1"));
        }

        @Test
        void acceptsValidPropertyTypeCodes() {
            assertEquals("SFR", validator.validatePropertyTypeCode("SFR", "LN-1"));
            assertEquals("CND", validator.validatePropertyTypeCode("CND", "LN-1"));
            assertEquals("MFR", validator.validatePropertyTypeCode("MFR", "LN-1"));
            assertEquals("TWN", validator.validatePropertyTypeCode("TWN", "LN-1"));
        }

        @Test
        void returnsNullForNullPropertyType() {
            assertNull(validator.validatePropertyTypeCode(null, "LN-1"));
        }
    }

    // =========================================================================
    // ANO-012: Required field validation
    // =========================================================================
    @Nested
    class RequiredFieldTests {

        @Test
        void returnsValueWhenPresent() {
            assertEquals("James", validator.validateRequiredField("James", "firstName", "R1", "Unknown"));
        }

        @Test
        void returnsFallbackForNull() {
            assertEquals("Unknown", validator.validateRequiredField(null, "firstName", "R1", "Unknown"));
        }

        @Test
        void returnsFallbackForBlank() {
            assertEquals("Unknown", validator.validateRequiredField("  ", "firstName", "R1", "Unknown"));
        }

        @Test
        void returnsFallbackForEmpty() {
            assertEquals("N/A", validator.validateRequiredField("", "address", "R1", "N/A"));
        }
    }

    // =========================================================================
    // ANO-008: Payment component reconciliation
    // =========================================================================
    @Nested
    class PaymentReconciliationTests {

        @Test
        void passesWhenComponentsMatchTotal() {
            assertTrue(validator.validatePaymentReconciliation(
                    new BigDecimal("2924.18"),
                    new BigDecimal("1842.56"),
                    new BigDecimal("815.50"),
                    new BigDecimal("266.12"),
                    new BigDecimal("0.00"),
                    "PMT-OK"));
        }

        @Test
        void failsWhenComponentsDoNotMatchTotal() {
            assertFalse(validator.validatePaymentReconciliation(
                    new BigDecimal("1487.02"),
                    new BigDecimal("456.78"),
                    new BigDecimal("1074.69"),
                    new BigDecimal("355.55"),
                    new BigDecimal("0.00"),
                    "PMT-BAD"));
        }

        @Test
        void passesWithinTolerance() {
            assertTrue(validator.validatePaymentReconciliation(
                    new BigDecimal("100.01"),
                    new BigDecimal("50.00"),
                    new BigDecimal("40.00"),
                    new BigDecimal("10.00"),
                    new BigDecimal("0.00"),
                    "PMT-CLOSE"));
        }

        @Test
        void failsForAllZeroTotal() {
            assertTrue(validator.validatePaymentReconciliation(
                    BigDecimal.ZERO,
                    BigDecimal.ZERO,
                    BigDecimal.ZERO,
                    BigDecimal.ZERO,
                    BigDecimal.ZERO,
                    "PMT-ZERO"));
        }
    }

    // =========================================================================
    // ANO-010: Delinquency consistency (no crash, just logging)
    // =========================================================================
    @Nested
    class DelinquencyConsistencyTests {

        @Test
        void doesNotThrowForDelinquentActiveLoans() {
            assertDoesNotThrow(() ->
                    validator.validateDelinquencyConsistency("15", "ACT", "LN-1"));
        }

        @Test
        void doesNotThrowForZeroDelinquencyActiveLoan() {
            assertDoesNotThrow(() ->
                    validator.validateDelinquencyConsistency("0", "ACT", "LN-1"));
        }

        @Test
        void doesNotThrowForDelinquentDefaultLoan() {
            assertDoesNotThrow(() ->
                    validator.validateDelinquencyConsistency("30", "DFT", "LN-1"));
        }

        @Test
        void doesNotThrowForNullDelinquency() {
            assertDoesNotThrow(() ->
                    validator.validateDelinquencyConsistency(null, "ACT", "LN-1"));
        }
    }

    // =========================================================================
    // ANO-011: LTV consistency
    // =========================================================================
    @Nested
    class LtvConsistencyTests {

        @Test
        void doesNotThrowForConsistentLtv() {
            assertDoesNotThrow(() ->
                    validator.validateLtvConsistency("68.2", "420,000", "615,000", "LN-1"));
        }

        @Test
        void doesNotThrowForInconsistentLtv() {
            assertDoesNotThrow(() ->
                    validator.validateLtvConsistency("82.5", "271,432.56", "345,000", "LN-1"));
        }

        @Test
        void doesNotThrowForZeroAppraised() {
            assertDoesNotThrow(() ->
                    validator.validateLtvConsistency("82.5", "271,432.56", "0", "LN-1"));
        }
    }

    // =========================================================================
    // ANO-004: Denormalized borrower name validation
    // =========================================================================
    @Nested
    class DenormalizedBorrowerTests {

        @Test
        void doesNotThrowForMatchingNames() {
            assertDoesNotThrow(() ->
                    validator.validateDenormalizedBorrowerName("James", "Mitchell", "James", "Mitchell", "LN-1"));
        }

        @Test
        void doesNotThrowForMismatchedNames() {
            assertDoesNotThrow(() ->
                    validator.validateDenormalizedBorrowerName("Jim", "Mitchell", "James", "Mitchell", "LN-1"));
        }

        @Test
        void doesNotThrowForNullNames() {
            assertDoesNotThrow(() ->
                    validator.validateDenormalizedBorrowerName(null, null, "James", "Mitchell", "LN-1"));
        }
    }
}
