package com.workshop.loanservice.validation;

import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class DataQualityValidatorTest {

    // =========================================================================
    // ANO-001: Numeric strings — parseAmount
    // =========================================================================

    @Nested
    class ParseAmountTests {

        @Test
        void parsesValidAmountWithCommas() {
            BigDecimal result = DataQualityValidator.parseAmount("285,000", "field", "REC-1");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void parsesValidAmountWithDecimal() {
            BigDecimal result = DataQualityValidator.parseAmount("1,487.02", "field", "REC-1");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        void parsesAmountWithDollarSign() {
            BigDecimal result = DataQualityValidator.parseAmount("$285,000", "field", "REC-1");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void returnsZeroForNull() {
            BigDecimal result = DataQualityValidator.parseAmount(null, "field", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsZeroForBlank() {
            BigDecimal result = DataQualityValidator.parseAmount("   ", "field", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsNullForNonNumeric() {
            BigDecimal result = DataQualityValidator.parseAmount("N/A", "field", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForTextPlaceholder() {
            BigDecimal result = DataQualityValidator.parseAmount("TBD", "field", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForPending() {
            BigDecimal result = DataQualityValidator.parseAmount("PENDING", "field", "REC-1");
            assertNull(result);
        }

        @Test
        void handlesTrailingSpaces() {
            BigDecimal result = DataQualityValidator.parseAmount("285,000 ", "field", "REC-1");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void handlesLeadingSpaces() {
            BigDecimal result = DataQualityValidator.parseAmount("  1,487.02", "field", "REC-1");
            assertEquals(new BigDecimal("1487.02"), result);
        }
    }

    // =========================================================================
    // ANO-001: Integer parsing
    // =========================================================================

    @Nested
    class ParseIntegerTests {

        @Test
        void parsesValidInteger() {
            Integer result = DataQualityValidator.parseInteger("745", "field", "REC-1");
            assertEquals(745, result);
        }

        @Test
        void returnsNullForNull() {
            Integer result = DataQualityValidator.parseInteger(null, "field", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForBlank() {
            Integer result = DataQualityValidator.parseInteger("", "field", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForNonNumeric() {
            Integer result = DataQualityValidator.parseInteger("N/A", "field", "REC-1");
            assertNull(result);
        }

        @Test
        void handlesWhitespace() {
            Integer result = DataQualityValidator.parseInteger("  745  ", "field", "REC-1");
            assertEquals(745, result);
        }

        @Test
        void handlesIntegerWithCommas() {
            Integer result = DataQualityValidator.parseInteger("1,000", "field", "REC-1");
            assertEquals(1000, result);
        }
    }

    // =========================================================================
    // ANO-002: Date parsing
    // =========================================================================

    @Nested
    class ParseDateTests {

        @Test
        void parsesValidMMddyyyyDate() {
            LocalDate result = DataQualityValidator.parseDate("03/15/1978", "field", "REC-1");
            assertEquals(LocalDate.of(1978, 3, 15), result);
        }

        @Test
        void parsesDecemberDate() {
            LocalDate result = DataQualityValidator.parseDate("12/01/2025", "field", "REC-1");
            assertEquals(LocalDate.of(2025, 12, 1), result);
        }

        @Test
        void returnsNullForNull() {
            LocalDate result = DataQualityValidator.parseDate(null, "field", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForBlank() {
            LocalDate result = DataQualityValidator.parseDate("", "field", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForIsoFormat() {
            LocalDate result = DataQualityValidator.parseDate("1978-03-15", "field", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForInvalidDate() {
            LocalDate result = DataQualityValidator.parseDate("13/32/2025", "field", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForTwoDigitYear() {
            LocalDate result = DataQualityValidator.parseDate("03/15/78", "field", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForTextDate() {
            LocalDate result = DataQualityValidator.parseDate("March 15, 1978", "field", "REC-1");
            assertNull(result);
        }
    }

    // =========================================================================
    // ANO-003: Payment integrity
    // =========================================================================

    @Nested
    class PaymentIntegrityTests {

        @Test
        void noWarningsWhenSumsMatch() {
            BigDecimal total = new BigDecimal("2924.18");
            BigDecimal prin = new BigDecimal("1842.56");
            BigDecimal interest = new BigDecimal("815.50");
            BigDecimal escrow = new BigDecimal("266.12");
            BigDecimal lateFee = BigDecimal.ZERO;

            List<String> warnings = DataQualityValidator.validatePaymentIntegrity(
                    total, prin, interest, escrow, lateFee, "PMT-OK");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void warnsWhenEscrowCausesOvercount() {
            BigDecimal total = new BigDecimal("1487.02");
            BigDecimal prin = new BigDecimal("456.78");
            BigDecimal interest = new BigDecimal("1074.69");
            BigDecimal escrow = new BigDecimal("355.55");
            BigDecimal lateFee = BigDecimal.ZERO;

            List<String> warnings = DataQualityValidator.validatePaymentIntegrity(
                    total, prin, interest, escrow, lateFee, "PMT-2025120001");
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("PMT-2025120001"));
            assertTrue(warnings.get(0).contains("delta"));
        }

        @Test
        void warnsWhenLateFeeExcluded() {
            BigDecimal total = new BigDecimal("1077.05");
            BigDecimal prin = new BigDecimal("295.82");
            BigDecimal interest = new BigDecimal("781.23");
            BigDecimal escrow = BigDecimal.ZERO;
            BigDecimal lateFee = new BigDecimal("47.50");

            List<String> warnings = DataQualityValidator.validatePaymentIntegrity(
                    total, prin, interest, escrow, lateFee, "PMT-2025110003");
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("47.50") || warnings.get(0).contains("delta"));
        }

        @Test
        void handlesNullAmounts() {
            List<String> warnings = DataQualityValidator.validatePaymentIntegrity(
                    null, new BigDecimal("100"), null, BigDecimal.ZERO, BigDecimal.ZERO, "PMT-NULL");
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("could not be parsed"));
        }
    }

    // =========================================================================
    // ANO-009: Credit score range
    // =========================================================================

    @Nested
    class CreditScoreTests {

        @Test
        void acceptsValidScore() {
            Integer result = DataQualityValidator.validateCreditScore("745", "REC-1");
            assertEquals(745, result);
        }

        @Test
        void acceptsMinScore() {
            Integer result = DataQualityValidator.validateCreditScore("300", "REC-1");
            assertEquals(300, result);
        }

        @Test
        void acceptsMaxScore() {
            Integer result = DataQualityValidator.validateCreditScore("850", "REC-1");
            assertEquals(850, result);
        }

        @Test
        void returnsScoreButWarnsForOutOfRange() {
            Integer result = DataQualityValidator.validateCreditScore("9999", "REC-1");
            assertEquals(9999, result);
        }

        @Test
        void returnsScoreButWarnsForTooLow() {
            Integer result = DataQualityValidator.validateCreditScore("0", "REC-1");
            assertEquals(0, result);
        }

        @Test
        void returnsNullForNonNumeric() {
            Integer result = DataQualityValidator.validateCreditScore("N/A", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForNull() {
            Integer result = DataQualityValidator.validateCreditScore(null, "REC-1");
            assertNull(result);
        }
    }

    // =========================================================================
    // ANO-010: Status code validation
    // =========================================================================

    @Nested
    class StatusCodeTests {

        @Test
        void acceptsValidLoanStatus() {
            assertTrue(DataQualityValidator.isValidStatusCode("ACT",
                    DataQualityValidator.getValidLoanStatuses(), "loanStatus", "LN-1"));
        }

        @Test
        void rejectsUnknownLoanStatus() {
            assertFalse(DataQualityValidator.isValidStatusCode("XYZ",
                    DataQualityValidator.getValidLoanStatuses(), "loanStatus", "LN-1"));
        }

        @Test
        void rejectsNullStatus() {
            assertFalse(DataQualityValidator.isValidStatusCode(null,
                    DataQualityValidator.getValidLoanStatuses(), "loanStatus", "LN-1"));
        }

        @Test
        void rejectsBlankStatus() {
            assertFalse(DataQualityValidator.isValidStatusCode("",
                    DataQualityValidator.getValidLoanStatuses(), "loanStatus", "LN-1"));
        }

        @Test
        void acceptsValidPaymentStatus() {
            assertTrue(DataQualityValidator.isValidStatusCode("PST",
                    DataQualityValidator.getValidPaymentStatuses(), "paymentStatus", "PMT-1"));
        }

        @Test
        void acceptsValidPaymentType() {
            assertTrue(DataQualityValidator.isValidStatusCode("REG",
                    DataQualityValidator.getValidPaymentTypes(), "paymentType", "PMT-1"));
        }
    }

    // =========================================================================
    // ANO-006: Required field validation
    // =========================================================================

    @Nested
    class RequiredFieldTests {

        @Test
        void returnsTrueForPresentField() {
            assertTrue(DataQualityValidator.isRequiredFieldPresent("James", "firstName", "REC-1"));
        }

        @Test
        void returnsFalseForNull() {
            assertFalse(DataQualityValidator.isRequiredFieldPresent(null, "firstName", "REC-1"));
        }

        @Test
        void returnsFalseForBlank() {
            assertFalse(DataQualityValidator.isRequiredFieldPresent("   ", "firstName", "REC-1"));
        }

        @Test
        void returnsFalseForEmpty() {
            assertFalse(DataQualityValidator.isRequiredFieldPresent("", "firstName", "REC-1"));
        }
    }

    // =========================================================================
    // ANO-011: Loan status consistency
    // =========================================================================

    @Nested
    class LoanStatusConsistencyTests {

        @Test
        void noWarningForZeroDelinquencyActive() {
            List<String> warnings = DataQualityValidator.validateLoanStatusConsistency("ACT", "0", "LN-1");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void warnsForDelinquentButActive() {
            List<String> warnings = DataQualityValidator.validateLoanStatusConsistency("ACT", "15", "LN-1");
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("15 delinquency days"));
            assertTrue(warnings.get(0).contains("ACT"));
        }

        @Test
        void noWarningForDelinquentDefault() {
            List<String> warnings = DataQualityValidator.validateLoanStatusConsistency("DFT", "90", "LN-1");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesNullDelinquency() {
            List<String> warnings = DataQualityValidator.validateLoanStatusConsistency("ACT", null, "LN-1");
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // ANO-012: LTV validation
    // =========================================================================

    @Nested
    class LtvValidationTests {

        @Test
        void noWarningForReasonableLtv() {
            List<String> warnings = DataQualityValidator.validateLtvPercent("82.5", "LN-1");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void warnsForExcessiveLtv() {
            List<String> warnings = DataQualityValidator.validateLtvPercent("825", "LN-1");
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("outside reasonable range"));
        }

        @Test
        void warnsForNegativeLtv() {
            List<String> warnings = DataQualityValidator.validateLtvPercent("-5", "LN-1");
            assertEquals(1, warnings.size());
        }

        @Test
        void handlesNullLtv() {
            List<String> warnings = DataQualityValidator.validateLtvPercent(null, "LN-1");
            assertTrue(warnings.isEmpty());
        }
    }
}
