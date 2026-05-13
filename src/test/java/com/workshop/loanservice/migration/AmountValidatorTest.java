package com.workshop.loanservice.migration;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for {@link AmountValidator} — validates VARCHAR → DECIMAL transformation
 * logic including comma stripping, precision/scale enforcement, range checks,
 * null handling, and payment component sum validation.
 */
class AmountValidatorTest {

    private AmountValidator validator;

    @BeforeEach
    void setUp() {
        validator = new AmountValidator();
    }

    // =========================================================================
    // parseAmount — comma stripping
    // =========================================================================

    @Test
    void parseAmount_commaStripping_wholeNumber() {
        // "285,000" → 285000 — common legacy format for original loan amounts
        ValidationResult<BigDecimal> result = validator.parseAmount(
                "285,000", "original_amount", true, 12, 2);
        assertTrue(result.isValid());
        assertEquals(0, new BigDecimal("285000").compareTo(result.getValue()));
    }

    @Test
    void parseAmount_commaStripping_withDecimals() {
        // "271,432.56" → 271432.56 — current balance format
        ValidationResult<BigDecimal> result = validator.parseAmount(
                "271,432.56", "current_balance", true, 12, 2);
        assertTrue(result.isValid());
        assertEquals(0, new BigDecimal("271432.56").compareTo(result.getValue()));
    }

    @Test
    void parseAmount_smallAmountWithComma() {
        // "1,487.02" → 1487.02 — monthly payment format
        ValidationResult<BigDecimal> result = validator.parseAmount(
                "1,487.02", "monthly_payment", true, 10, 2);
        assertTrue(result.isValid());
        assertEquals(0, new BigDecimal("1487.02").compareTo(result.getValue()));
    }

    // =========================================================================
    // parseAmount — precision overflow detection
    // =========================================================================

    @Test
    void parseAmount_precisionOverflow_decimal53() {
        // DECIMAL(5,3) max is 99.999 — value 100.000 should fail
        ValidationResult<BigDecimal> result = validator.parseAmount(
                "100.000", "interest_rate", true, 5, 3);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
        assertTrue(result.getErrorMessage().contains("exceeds"));
    }

    @Test
    void parseAmount_precisionOverflow_decimal102() {
        // DECIMAL(10,2) max is 99999999.99 — value within range
        ValidationResult<BigDecimal> result = validator.parseAmount(
                "99999999.99", "some_amount", true, 10, 2);
        assertTrue(result.isValid());
    }

    @Test
    void parseAmount_validForDecimal53() {
        // 4.750 fits within DECIMAL(5,3)
        ValidationResult<BigDecimal> result = validator.parseAmount(
                "4.750", "interest_rate", true, 5, 3);
        assertTrue(result.isValid());
        assertEquals(0, new BigDecimal("4.750").compareTo(result.getValue()));
    }

    // =========================================================================
    // parseAmount — null/blank handling
    // =========================================================================

    @Test
    void parseAmount_nullRequired_returnsError() {
        ValidationResult<BigDecimal> result = validator.parseAmount(
                null, "original_amount", true, 12, 2);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    @Test
    void parseAmount_nullOptional_returnsOk() {
        ValidationResult<BigDecimal> result = validator.parseAmount(
                null, "escrow_balance", false, 10, 2);
        assertTrue(result.isValid());
        assertNull(result.getValue());
    }

    @Test
    void parseAmount_blankRequired_returnsError() {
        ValidationResult<BigDecimal> result = validator.parseAmount(
                "  ", "original_amount", true, 12, 2);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    // =========================================================================
    // parseAmount — negative value rejection
    // =========================================================================

    @Test
    void parseAmount_negativeValue_returnsError() {
        // The regex only allows digits, so negative values with a leading minus won't match
        ValidationResult<BigDecimal> result = validator.parseAmount(
                "-500.00", "some_amount", true, 10, 2);
        assertFalse(result.isValid());
    }

    // =========================================================================
    // parseInterestRate — DECIMAL(5,3) with 0-30% range
    // =========================================================================

    @Test
    void parseInterestRate_validRate() {
        ValidationResult<BigDecimal> result = validator.parseInterestRate("4.750");
        assertTrue(result.isValid());
        assertEquals(0, new BigDecimal("4.750").compareTo(result.getValue()));
    }

    @Test
    void parseInterestRate_exceedsRange_returnsWarning() {
        // 35% exceeds the 30% typical maximum — should produce WARNING
        ValidationResult<BigDecimal> result = validator.parseInterestRate("35.000");
        assertTrue(result.isValid()); // Warning, not error
        assertEquals(ValidationResult.Severity.WARNING, result.getSeverity());
        assertTrue(result.getErrorMessage().contains("exceeds typical maximum"));
    }

    @Test
    void parseInterestRate_zeroRate_isValid() {
        ValidationResult<BigDecimal> result = validator.parseInterestRate("0.000");
        assertTrue(result.isValid());
    }

    // =========================================================================
    // parseLtvPercent — 0-200% range
    // =========================================================================

    @Test
    void parseLtvPercent_validPercent() {
        ValidationResult<BigDecimal> result = validator.parseLtvPercent("82.5");
        assertTrue(result.isValid());
    }

    @Test
    void parseLtvPercent_exceedsRange_returnsWarning() {
        ValidationResult<BigDecimal> result = validator.parseLtvPercent("250.00");
        assertEquals(ValidationResult.Severity.WARNING, result.getSeverity());
        assertTrue(result.getErrorMessage().contains("exceeds maximum of 200%"));
    }

    // =========================================================================
    // parseCreditScore — 300-850 range
    // =========================================================================

    @Test
    void parseCreditScore_validScore() {
        ValidationResult<Integer> result = validator.parseCreditScore("745");
        assertTrue(result.isValid());
        assertEquals(745, result.getValue());
    }

    @Test
    void parseCreditScore_belowRange_returnsWarning() {
        ValidationResult<Integer> result = validator.parseCreditScore("200");
        assertEquals(ValidationResult.Severity.WARNING, result.getSeverity());
        assertTrue(result.getErrorMessage().contains("outside valid range"));
    }

    @Test
    void parseCreditScore_aboveRange_returnsWarning() {
        ValidationResult<Integer> result = validator.parseCreditScore("900");
        assertEquals(ValidationResult.Severity.WARNING, result.getSeverity());
    }

    @Test
    void parseCreditScore_nonNumeric_returnsError() {
        ValidationResult<Integer> result = validator.parseCreditScore("ABC");
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    @Test
    void parseCreditScore_null_returnsOk() {
        ValidationResult<Integer> result = validator.parseCreditScore(null);
        assertTrue(result.isValid());
        assertNull(result.getValue());
    }

    // =========================================================================
    // parseInteger — replaces legacy parseLegacyInteger
    // =========================================================================

    @Test
    void parseInteger_valid() {
        ValidationResult<Integer> result = validator.parseInteger("360", "term_months", true);
        assertTrue(result.isValid());
        assertEquals(360, result.getValue());
    }

    @Test
    void parseInteger_invalid_required_returnsError() {
        ValidationResult<Integer> result = validator.parseInteger("abc", "term_months", true);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    @Test
    void parseInteger_invalid_optional_returnsWarning() {
        ValidationResult<Integer> result = validator.parseInteger("abc", "delinquency_days", false);
        assertEquals(ValidationResult.Severity.WARNING, result.getSeverity());
    }

    // =========================================================================
    // validatePaymentComponentSum — including known PMT-2025120001 mismatch
    // =========================================================================

    @Test
    void validatePaymentComponentSum_matching_noWarning() {
        // Components that sum correctly: 100 + 50 + 30 + 0 = 180
        BigDecimal total = new BigDecimal("180.00");
        BigDecimal principal = new BigDecimal("100.00");
        BigDecimal interest = new BigDecimal("50.00");
        BigDecimal escrow = new BigDecimal("30.00");
        BigDecimal lateFee = BigDecimal.ZERO;

        List<ValidationResult<?>> results = validator.validatePaymentComponentSum(
                total, principal, interest, escrow, lateFee, "TEST-001");
        assertTrue(results.isEmpty(), "Expected no warnings when components sum to total");
    }

    @Test
    void validatePaymentComponentSum_pmt2025120001_mismatch() {
        // Known failing case from seed data: PMT-2025120001
        // total=1,487.02, principal=456.78, interest=1,074.69, escrow=355.55, lateFee=0.00
        // Components sum: 456.78 + 1074.69 + 355.55 + 0.00 = 1887.02
        // Delta: 1887.02 - 1487.02 = 400.00
        BigDecimal total = new BigDecimal("1487.02");
        BigDecimal principal = new BigDecimal("456.78");
        BigDecimal interest = new BigDecimal("1074.69");
        BigDecimal escrow = new BigDecimal("355.55");
        BigDecimal lateFee = new BigDecimal("0.00");

        List<ValidationResult<?>> results = validator.validatePaymentComponentSum(
                total, principal, interest, escrow, lateFee, "PMT-2025120001");
        assertFalse(results.isEmpty(), "Expected warning for PMT-2025120001 component mismatch");
        assertTrue(results.get(0).getErrorMessage().contains("mismatch"));
        assertTrue(results.get(0).getErrorMessage().contains("1887.02"));
    }

    @Test
    void validatePaymentComponentSum_nullTotal_noValidation() {
        // If total is null, validation should be skipped
        List<ValidationResult<?>> results = validator.validatePaymentComponentSum(
                null, new BigDecimal("100"), new BigDecimal("50"),
                BigDecimal.ZERO, BigDecimal.ZERO, "TEST-002");
        assertTrue(results.isEmpty());
    }
}
