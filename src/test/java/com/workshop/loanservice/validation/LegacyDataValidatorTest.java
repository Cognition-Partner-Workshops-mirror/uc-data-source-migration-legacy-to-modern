package com.workshop.loanservice.validation;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for LegacyDataValidator covering all anomaly types identified in the
 * DATA_ANOMALY_REPORT.md. Each nested class corresponds to a specific anomaly category.
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Anomaly #3: Numeric amounts stored as strings with parsing risks
    // =========================================================================
    @Nested
    @DisplayName("Amount Parsing (Anomaly #3 - Numeric strings with commas)")
    class AmountParsingTests {

        @Test
        @DisplayName("Parses standard comma-separated amount: '285,000'")
        void parsesStandardCommaAmount() {
            BigDecimal result = validator.parseAmount("285,000", "test");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Parses amount with commas and decimals: '271,432.56'")
        void parsesAmountWithDecimals() {
            BigDecimal result = validator.parseAmount("271,432.56", "test");
            assertEquals(new BigDecimal("271432.56"), result);
        }

        @Test
        @DisplayName("Parses amount with dollar sign: '$285,000'")
        void parsesAmountWithDollarSign() {
            BigDecimal result = validator.parseAmount("$285,000", "test");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Handles accounting-format negative: '(1,200.00)'")
        void parsesAccountingNegative() {
            BigDecimal result = validator.parseAmount("(1,200.00)", "test");
            assertEquals(new BigDecimal("-1200.00"), result);
        }

        @Test
        @DisplayName("Returns zero for null input without throwing")
        void returnsZeroForNull() {
            BigDecimal result = validator.parseAmount(null, "test");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns zero for blank input without throwing")
        void returnsZeroForBlank() {
            BigDecimal result = validator.parseAmount("   ", "test");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns zero for non-numeric input 'N/A' without throwing")
        void returnsZeroForNonNumeric() {
            BigDecimal result = validator.parseAmount("N/A", "test");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns zero for garbled input 'ABC123' without throwing")
        void returnsZeroForGarbledInput() {
            BigDecimal result = validator.parseAmount("ABC123", "test");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Handles amount with spaces: ' 1,487.02 '")
        void parsesAmountWithSpaces() {
            BigDecimal result = validator.parseAmount(" 1,487.02 ", "test");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        @DisplayName("Parses zero amount: '0.00'")
        void parsesZeroAmount() {
            BigDecimal result = validator.parseAmount("0.00", "test");
            assertEquals(new BigDecimal("0.00"), result);
        }
    }

    // =========================================================================
    // Anomaly #4: Date strings without validation
    // =========================================================================
    @Nested
    @DisplayName("Date Parsing (Anomaly #4 - Date format inconsistencies)")
    class DateParsingTests {

        @Test
        @DisplayName("Parses valid MM/DD/YYYY date to ISO-8601")
        void parsesValidDate() {
            String result = validator.parseDateToIso("03/15/1978", "test");
            assertEquals("1978-03-15", result);
        }

        @Test
        @DisplayName("Parses date with leading zeros: '01/01/2020'")
        void parsesDateWithLeadingZeros() {
            String result = validator.parseDateToIso("01/01/2020", "test");
            assertEquals("2020-01-01", result);
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNullDate() {
            assertNull(validator.parseDateToIso(null, "test"));
        }

        @Test
        @DisplayName("Returns null for blank input")
        void returnsNullForBlankDate() {
            assertNull(validator.parseDateToIso("  ", "test"));
        }

        @Test
        @DisplayName("Returns raw string for invalid date '13/01/2020' (month 13)")
        void returnsRawStringForInvalidMonth() {
            String result = validator.parseDateToIso("13/01/2020", "test");
            // Invalid date returns raw string as fallback
            assertEquals("13/01/2020", result);
        }

        @Test
        @DisplayName("Returns raw string for wrong format 'YYYY-MM-DD'")
        void returnsRawStringForWrongFormat() {
            String result = validator.parseDateToIso("2020-01-15", "test");
            assertEquals("2020-01-15", result);
        }

        @Test
        @DisplayName("Returns raw string for invalid date '02/30/2020'")
        void returnsRawStringForInvalidDay() {
            String result = validator.parseDateToIso("02/30/2020", "test");
            assertEquals("02/30/2020", result);
        }

        @Test
        @DisplayName("Returns raw string for placeholder '00/00/0000'")
        void returnsRawStringForPlaceholder() {
            String result = validator.parseDateToIso("00/00/0000", "test");
            assertEquals("00/00/0000", result);
        }
    }

    // =========================================================================
    // Anomaly #8: Credit score string parsing risk
    // =========================================================================
    @Nested
    @DisplayName("Credit Score Parsing (Anomaly #8 - Integer parsing risk)")
    class CreditScoreTests {

        @Test
        @DisplayName("Parses valid credit score within FICO range")
        void parsesValidCreditScore() {
            assertEquals(745, validator.parseCreditScore("745", "B-10001"));
        }

        @Test
        @DisplayName("Returns null for non-numeric 'N/A'")
        void returnsNullForNonNumeric() {
            assertNull(validator.parseCreditScore("N/A", "B-TEST"));
        }

        @Test
        @DisplayName("Returns null for score below FICO minimum (300)")
        void returnsNullForScoreBelowMin() {
            assertNull(validator.parseCreditScore("200", "B-TEST"));
        }

        @Test
        @DisplayName("Returns null for score above FICO maximum (850)")
        void returnsNullForScoreAboveMax() {
            assertNull(validator.parseCreditScore("9999", "B-TEST"));
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNull() {
            assertNull(validator.parseCreditScore(null, "B-TEST"));
        }

        @Test
        @DisplayName("Returns null for blank input")
        void returnsNullForBlank() {
            assertNull(validator.parseCreditScore("  ", "B-TEST"));
        }

        @Test
        @DisplayName("Parses boundary value 300 (minimum valid)")
        void parsesMinBoundary() {
            assertEquals(300, validator.parseCreditScore("300", "B-TEST"));
        }

        @Test
        @DisplayName("Parses boundary value 850 (maximum valid)")
        void parsesMaxBoundary() {
            assertEquals(850, validator.parseCreditScore("850", "B-TEST"));
        }
    }

    // =========================================================================
    // Anomaly #1: Payment component mismatch
    // =========================================================================
    @Nested
    @DisplayName("Payment Component Validation (Anomaly #1 - Sum ≠ Total)")
    class PaymentComponentTests {

        @Test
        @DisplayName("Returns true when components sum correctly")
        void returnsTrueForValidComponents() {
            // From actual data: PMT-2025120002 (LN-2020-00398)
            boolean result = validator.validatePaymentComponents(
                    "PMT-2025120002",
                    new BigDecimal("2924.18"),   // total
                    new BigDecimal("1842.56"),   // principal
                    new BigDecimal("815.50"),    // interest
                    new BigDecimal("266.12"),    // escrow
                    new BigDecimal("0.00")       // late fee
            );
            assertTrue(result);
        }

        @Test
        @DisplayName("Returns false when components exceed total (Anomaly #1 exact case)")
        void returnsFalseForMismatchedComponents() {
            // From actual data: PMT-2025120001 (LN-2019-00142) — known bad record
            boolean result = validator.validatePaymentComponents(
                    "PMT-2025120001",
                    new BigDecimal("1487.02"),   // stated total
                    new BigDecimal("456.78"),    // principal
                    new BigDecimal("1074.69"),   // interest
                    new BigDecimal("355.55"),    // escrow
                    new BigDecimal("0.00")       // late fee
            );
            // Components sum to 1887.02, total is 1487.02 — mismatch
            assertFalse(result);
        }

        @Test
        @DisplayName("Returns true when all components are zero")
        void returnsTrueForAllZeros() {
            boolean result = validator.validatePaymentComponents(
                    "PMT-TEST",
                    BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO,
                    BigDecimal.ZERO, BigDecimal.ZERO
            );
            assertTrue(result);
        }
    }

    // =========================================================================
    // Anomaly #5: No FK constraints (status code validation)
    // =========================================================================
    @Nested
    @DisplayName("Status Code Validation (Anomaly #5 - Invalid codes)")
    class StatusCodeTests {

        @Test
        @DisplayName("Accepts valid loan status 'ACT'")
        void acceptsValidLoanStatus() {
            assertTrue(validator.isValidLoanStatus("ACT", "LN-TEST"));
        }

        @Test
        @DisplayName("Accepts valid loan status 'CLO'")
        void acceptsClosedStatus() {
            assertTrue(validator.isValidLoanStatus("CLO", "LN-TEST"));
        }

        @Test
        @DisplayName("Rejects unrecognized loan status 'XYZ'")
        void rejectsUnrecognizedLoanStatus() {
            assertFalse(validator.isValidLoanStatus("XYZ", "LN-TEST"));
        }

        @Test
        @DisplayName("Rejects null loan status")
        void rejectsNullLoanStatus() {
            assertFalse(validator.isValidLoanStatus(null, "LN-TEST"));
        }

        @Test
        @DisplayName("Accepts valid payment status 'PST'")
        void acceptsValidPaymentStatus() {
            assertTrue(validator.isValidPaymentStatus("PST", "PMT-TEST"));
        }

        @Test
        @DisplayName("Rejects unrecognized payment status 'XXX'")
        void rejectsUnrecognizedPaymentStatus() {
            assertFalse(validator.isValidPaymentStatus("XXX", "PMT-TEST"));
        }

        @Test
        @DisplayName("Accepts valid payment type 'REG'")
        void acceptsValidPaymentType() {
            assertTrue(validator.isValidPaymentType("REG", "PMT-TEST"));
        }

        @Test
        @DisplayName("Rejects unrecognized payment type 'UNK'")
        void rejectsUnrecognizedPaymentType() {
            assertFalse(validator.isValidPaymentType("UNK", "PMT-TEST"));
        }
    }

    // =========================================================================
    // Anomaly #10: Address concatenation with potential NULLs
    // =========================================================================
    @Nested
    @DisplayName("Address Formatting (Anomaly #10 - NULL handling)")
    class AddressFormattingTests {

        @Test
        @DisplayName("Formats complete address correctly")
        void formatsCompleteAddress() {
            String result = validator.formatAddress("742 Elm Street", "Springfield", "IL", "62701");
            assertEquals("742 Elm Street, Springfield, IL 62701", result);
        }

        @Test
        @DisplayName("Handles null city gracefully")
        void handlesNullCity() {
            String result = validator.formatAddress("742 Elm Street", null, "IL", "62701");
            assertEquals("742 Elm Street, IL 62701", result);
        }

        @Test
        @DisplayName("Handles null state gracefully")
        void handlesNullState() {
            String result = validator.formatAddress("742 Elm Street", "Springfield", null, "62701");
            assertEquals("742 Elm Street, Springfield 62701", result);
        }

        @Test
        @DisplayName("Handles all nulls — returns default message")
        void handlesAllNulls() {
            String result = validator.formatAddress(null, null, null, null);
            assertEquals("Address not available", result);
        }

        @Test
        @DisplayName("Handles blank strings same as null")
        void handlesBlankStrings() {
            String result = validator.formatAddress("  ", "", null, "");
            assertEquals("Address not available", result);
        }
    }

    // =========================================================================
    // Anomaly #5: FK reference validation
    // =========================================================================
    @Nested
    @DisplayName("Reference Validation (Anomaly #5 - Orphaned records)")
    class ReferenceValidationTests {

        @Test
        @DisplayName("Accepts valid non-null reference")
        void acceptsValidReference() {
            assertTrue(validator.isValidReference("LN-2019-00142", "test"));
        }

        @Test
        @DisplayName("Rejects null reference")
        void rejectsNullReference() {
            assertFalse(validator.isValidReference(null, "test"));
        }

        @Test
        @DisplayName("Rejects blank reference")
        void rejectsBlankReference() {
            assertFalse(validator.isValidReference("  ", "test"));
        }
    }

    // =========================================================================
    // Decimal parsing (interest rates, LTV percentages)
    // =========================================================================
    @Nested
    @DisplayName("Decimal Parsing (Interest rates and percentages)")
    class DecimalParsingTests {

        @Test
        @DisplayName("Parses interest rate '4.750'")
        void parsesInterestRate() {
            BigDecimal result = validator.parseDecimal("4.750", "test");
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        @DisplayName("Parses LTV percentage '82.5'")
        void parsesLtvPercent() {
            BigDecimal result = validator.parseDecimal("82.5", "test");
            assertEquals(new BigDecimal("82.5"), result);
        }

        @Test
        @DisplayName("Returns zero for non-numeric input without throwing")
        void returnsZeroForNonNumeric() {
            BigDecimal result = validator.parseDecimal("VARIABLE", "test");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns zero for null input")
        void returnsZeroForNull() {
            BigDecimal result = validator.parseDecimal(null, "test");
            assertEquals(BigDecimal.ZERO, result);
        }
    }

    // =========================================================================
    // Integer parsing (term months, delinquency days)
    // =========================================================================
    @Nested
    @DisplayName("Integer Parsing (Term months, delinquency days)")
    class IntegerParsingTests {

        @Test
        @DisplayName("Parses term months '360'")
        void parsesTermMonths() {
            assertEquals(360, validator.parseInteger("360", "test"));
        }

        @Test
        @DisplayName("Parses delinquency days '15'")
        void parsesDelinquencyDays() {
            assertEquals(15, validator.parseInteger("15", "test"));
        }

        @Test
        @DisplayName("Returns null for non-numeric input")
        void returnsNullForNonNumeric() {
            assertNull(validator.parseInteger("N/A", "test"));
        }

        @Test
        @DisplayName("Returns null for decimal input '3.5'")
        void returnsNullForDecimal() {
            assertNull(validator.parseInteger("3.5", "test"));
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNull() {
            assertNull(validator.parseInteger(null, "test"));
        }
    }
}
