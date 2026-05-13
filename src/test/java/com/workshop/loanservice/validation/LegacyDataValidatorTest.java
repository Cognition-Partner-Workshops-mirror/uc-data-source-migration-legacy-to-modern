package com.workshop.loanservice.validation;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for LegacyDataValidator.
 * Verifies that each data anomaly type discovered in the legacy CDW tables
 * is properly caught and handled at ingestion time.
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Anomaly #2: Numeric Parsing Without Error Handling
    // =========================================================================

    @Nested
    @DisplayName("Amount Parsing (Anomaly #2 — Numeric string parsing risks)")
    class AmountParsingTests {

        @Test
        @DisplayName("Parses valid amount with commas")
        void parsesValidAmountWithCommas() {
            BigDecimal result = validator.parseAmount("285,000", "LN_ORIG_AMT", "LN-001");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Parses valid amount with commas and decimals")
        void parsesValidAmountWithCommasAndDecimals() {
            BigDecimal result = validator.parseAmount("1,487.02", "LN_PMT_AMT", "LN-001");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        @DisplayName("Returns ZERO for null input — no exception")
        void returnsZeroForNull() {
            BigDecimal result = validator.parseAmount(null, "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns ZERO for blank input — no exception")
        void returnsZeroForBlank() {
            BigDecimal result = validator.parseAmount("   ", "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Strips dollar sign and parses successfully — catches currency symbol anomaly")
        void stripsDollarSign() {
            BigDecimal result = validator.parseAmount("$285,000", "LN_ORIG_AMT", "LN-001");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Returns ZERO for text value 'N/A' — no exception thrown")
        void handlesTextValueNA() {
            BigDecimal result = validator.parseAmount("N/A", "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns ZERO for text value 'PENDING' — no exception thrown")
        void handlesTextValuePending() {
            BigDecimal result = validator.parseAmount("PENDING", "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Handles malformed decimal with double period — returns ZERO")
        void handlesMalformedDecimal() {
            BigDecimal result = validator.parseAmount("1,487.02.5", "LN_PMT_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Parses negative amount correctly")
        void parsesNegativeAmount() {
            BigDecimal result = validator.parseAmount("-1,234.56", "LN_BAL", "LN-001");
            assertEquals(new BigDecimal("-1234.56"), result);
        }
    }

    @Nested
    @DisplayName("Decimal Parsing")
    class DecimalParsingTests {

        @Test
        @DisplayName("Parses valid interest rate string")
        void parsesValidDecimal() {
            BigDecimal result = validator.parseDecimal("5.250", "LN_INT_RT", "LN-001");
            assertEquals(new BigDecimal("5.250"), result);
        }

        @Test
        @DisplayName("Returns ZERO for null — no exception")
        void returnsZeroForNull() {
            BigDecimal result = validator.parseDecimal(null, "LN_INT_RT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Strips percent sign and parses — catches symbol anomaly")
        void stripsPercentSign() {
            BigDecimal result = validator.parseDecimal("5.25%", "LN_INT_RT", "LN-001");
            assertEquals(new BigDecimal("5.25"), result);
        }

        @Test
        @DisplayName("Returns ZERO for non-numeric text — no exception")
        void handlesNonNumericText() {
            BigDecimal result = validator.parseDecimal("VARIABLE", "LN_INT_RT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }
    }

    @Nested
    @DisplayName("Integer Parsing (Credit Score, Term Months)")
    class IntegerParsingTests {

        @Test
        @DisplayName("Parses valid credit score string")
        void parsesValidInteger() {
            Integer result = validator.parseInteger("745", "BORR_CRDT_SCR", "B-10001");
            assertEquals(745, result);
        }

        @Test
        @DisplayName("Returns null for null input — no exception")
        void returnsNullForNull() {
            Integer result = validator.parseInteger(null, "BORR_CRDT_SCR", "B-10001");
            assertNull(result);
        }

        @Test
        @DisplayName("Returns null for blank input — no exception")
        void returnsNullForBlank() {
            Integer result = validator.parseInteger("", "BORR_CRDT_SCR", "B-10001");
            assertNull(result);
        }

        @Test
        @DisplayName("Returns null for non-integer text — no exception thrown")
        void handlesNonIntegerText() {
            Integer result = validator.parseInteger("UNKNOWN", "BORR_CRDT_SCR", "B-10001");
            assertNull(result);
        }

        @Test
        @DisplayName("Strips leading/trailing whitespace")
        void handlesWhitespace() {
            Integer result = validator.parseInteger("  780  ", "BORR_CRDT_SCR", "B-10001");
            assertEquals(780, result);
        }
    }

    // =========================================================================
    // Anomaly #6: Date String Validation
    // =========================================================================

    @Nested
    @DisplayName("Date Validation (Anomaly #6 — Date format inconsistencies)")
    class DateValidationTests {

        @Test
        @DisplayName("Valid MM/DD/YYYY date passes validation")
        void validDatePasses() {
            String result = validator.parseAndValidateDate("03/15/1978", "BORR_DOB_DT", "B-10001");
            assertEquals("03/15/1978", result);
        }

        @Test
        @DisplayName("Returns null for null input")
        void nullDateReturnsNull() {
            String result = validator.parseAndValidateDate(null, "BORR_DOB_DT", "B-10001");
            assertNull(result);
        }

        @Test
        @DisplayName("Returns null for blank input")
        void blankDateReturnsNull() {
            String result = validator.parseAndValidateDate("  ", "BORR_DOB_DT", "B-10001");
            assertNull(result);
        }

        @Test
        @DisplayName("Rejects impossible date Feb 30 — catches invalid day anomaly")
        void rejectsImpossibleDate() {
            String result = validator.parseAndValidateDate("02/30/2020", "LN_ORIG_DT", "LN-001");
            assertNull(result);
        }

        @Test
        @DisplayName("Rejects month 13 — catches invalid month anomaly")
        void rejectsInvalidMonth() {
            String result = validator.parseAndValidateDate("13/01/2020", "LN_ORIG_DT", "LN-001");
            assertNull(result);
        }

        @Test
        @DisplayName("Rejects ISO format YYYY-MM-DD — catches format inconsistency")
        void rejectsIsoFormat() {
            String result = validator.parseAndValidateDate("2020-01-15", "LN_ORIG_DT", "LN-001");
            assertNull(result);
        }

        @Test
        @DisplayName("Rejects text value 'N/A'")
        void rejectsTextValue() {
            String result = validator.parseAndValidateDate("N/A", "LN_ORIG_DT", "LN-001");
            assertNull(result);
        }
    }

    // =========================================================================
    // Anomaly #3: Null Values in Required Fields
    // =========================================================================

    @Nested
    @DisplayName("Null Safety (Anomaly #3 — Null fields in string concatenation)")
    class NullSafetyTests {

        @Test
        @DisplayName("safeString returns empty for null — prevents 'null' literal")
        void safeStringReturnsEmptyForNull() {
            assertEquals("", validator.safeString(null));
        }

        @Test
        @DisplayName("safeString returns original value when non-null")
        void safeStringReturnsValueForNonNull() {
            assertEquals("James", validator.safeString("James"));
        }

        @Test
        @DisplayName("safeStringOrDefault returns default for null")
        void safeStringOrDefaultForNull() {
            assertEquals("N/A", validator.safeStringOrDefault(null, "N/A"));
        }

        @Test
        @DisplayName("safeStringOrDefault returns default for blank")
        void safeStringOrDefaultForBlank() {
            assertEquals("N/A", validator.safeStringOrDefault("  ", "N/A"));
        }

        @Test
        @DisplayName("safeStringOrDefault returns value when present")
        void safeStringOrDefaultForPresent() {
            assertEquals("Springfield", validator.safeStringOrDefault("Springfield", "N/A"));
        }
    }

    // =========================================================================
    // Anomaly #1: Payment Component Sum Mismatch
    // =========================================================================

    @Nested
    @DisplayName("Payment Integrity (Anomaly #1 — Component sum mismatch)")
    class PaymentIntegrityTests {

        @Test
        @DisplayName("No warnings when components sum to total")
        void noWarningsWhenComponentsSumCorrectly() {
            BigDecimal total = new BigDecimal("2924.18");
            BigDecimal principal = new BigDecimal("1842.56");
            BigDecimal interest = new BigDecimal("815.50");
            BigDecimal escrow = new BigDecimal("266.12");
            BigDecimal lateFee = BigDecimal.ZERO;

            List<String> warnings = validator.validatePaymentIntegrity(
                    "PMT-OK", total, principal, interest, escrow, lateFee);
            assertTrue(warnings.isEmpty());
        }

        @Test
        @DisplayName("Detects $400 discrepancy in payment PMT-2025120001")
        void detectsLargeDiscrepancy() {
            // Actual data from data-legacy.sql: PMT-2025120001
            BigDecimal total = new BigDecimal("1487.02");
            BigDecimal principal = new BigDecimal("456.78");
            BigDecimal interest = new BigDecimal("1074.69");
            BigDecimal escrow = new BigDecimal("355.55");
            BigDecimal lateFee = BigDecimal.ZERO;

            List<String> warnings = validator.validatePaymentIntegrity(
                    "PMT-2025120001", total, principal, interest, escrow, lateFee);
            assertFalse(warnings.isEmpty());
            assertTrue(warnings.get(0).contains("mismatch"));
            assertTrue(warnings.get(0).contains("PMT-2025120001"));
        }

        @Test
        @DisplayName("Detects late fee discrepancy in payment PMT-2025110003")
        void detectsLateFeeDiscrepancy() {
            // Actual data from data-legacy.sql: PMT-2025110003
            BigDecimal total = new BigDecimal("1077.05");
            BigDecimal principal = new BigDecimal("295.82");
            BigDecimal interest = new BigDecimal("781.23");
            BigDecimal escrow = BigDecimal.ZERO;
            BigDecimal lateFee = new BigDecimal("47.50");

            List<String> warnings = validator.validatePaymentIntegrity(
                    "PMT-2025110003", total, principal, interest, escrow, lateFee);
            assertFalse(warnings.isEmpty());
            assertTrue(warnings.get(0).contains("mismatch"));
        }

        @Test
        @DisplayName("Tolerates rounding difference of $0.01")
        void toleratesRoundingDifference() {
            BigDecimal total = new BigDecimal("100.00");
            BigDecimal principal = new BigDecimal("50.005");
            BigDecimal interest = new BigDecimal("49.995");
            BigDecimal escrow = BigDecimal.ZERO;
            BigDecimal lateFee = BigDecimal.ZERO;

            List<String> warnings = validator.validatePaymentIntegrity(
                    "PMT-ROUND", total, principal, interest, escrow, lateFee);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // Anomaly #5: Delinquency Status Inconsistency
    // =========================================================================

    @Nested
    @DisplayName("Loan Status Consistency (Anomaly #5 — Delinquency vs. status)")
    class LoanStatusConsistencyTests {

        @Test
        @DisplayName("No warning for active loan with 0 delinquency days")
        void noWarningForActiveWithZeroDelinquency() {
            List<String> warnings = validator.validateLoanStatusConsistency(
                    "LN-001", "ACT", "0");
            assertTrue(warnings.isEmpty());
        }

        @Test
        @DisplayName("Detects delinquent loan with active status — LN-2018-00089 pattern")
        void detectsDelinquentActiveInconsistency() {
            // Matches actual data: LN-2018-00089 has 15 days delinquent but ACT status
            List<String> warnings = validator.validateLoanStatusConsistency(
                    "LN-2018-00089", "ACT", "15");
            assertFalse(warnings.isEmpty());
            assertTrue(warnings.get(0).contains("15 delinquency days"));
            assertTrue(warnings.get(0).contains("ACT"));
        }

        @Test
        @DisplayName("No warning for defaulted loan with delinquency days")
        void noWarningForDefaultWithDelinquency() {
            List<String> warnings = validator.validateLoanStatusConsistency(
                    "LN-001", "DFT", "90");
            assertTrue(warnings.isEmpty());
        }

        @Test
        @DisplayName("Handles null delinquency days gracefully")
        void handlesNullDelinquencyDays() {
            List<String> warnings = validator.validateLoanStatusConsistency(
                    "LN-001", "ACT", null);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // Anomaly #7: Orphaned Records (Referential Integrity)
    // =========================================================================

    @Nested
    @DisplayName("Referential Integrity (Anomaly #7 — Orphaned records)")
    class ReferentialIntegrityTests {

        @Test
        @DisplayName("Valid reference passes")
        void validReferenceReturnsTrue() {
            assertTrue(validator.validateReferenceNotEmpty("B-10001", "BORR_ID", "LN-001"));
        }

        @Test
        @DisplayName("Null reference detected as orphan risk")
        void nullReferenceReturnsFalse() {
            assertFalse(validator.validateReferenceNotEmpty(null, "BORR_ID", "LN-001"));
        }

        @Test
        @DisplayName("Blank reference detected as orphan risk")
        void blankReferenceReturnsFalse() {
            assertFalse(validator.validateReferenceNotEmpty("  ", "BORR_ID", "LN-001"));
        }

        @Test
        @DisplayName("Empty string reference detected as orphan risk")
        void emptyReferenceReturnsFalse() {
            assertFalse(validator.validateReferenceNotEmpty("", "LN_ACCT_NBR", "PMT-001"));
        }
    }
}
