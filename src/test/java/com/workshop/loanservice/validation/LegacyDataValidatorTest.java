package com.workshop.loanservice.validation;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for LegacyDataValidator covering all anomaly types
 * identified in docs/DATA_ANOMALY_REPORT.md.
 */
class LegacyDataValidatorTest {

    // =========================================================================
    // ANO-004: Numeric strings with commas — parseAmount
    // =========================================================================

    @Test
    @DisplayName("ANO-004: parseAmount handles comma-formatted amounts")
    void parseAmount_commaFormatted() {
        assertEquals(new BigDecimal("285000"), LegacyDataValidator.parseAmount("285,000", "LN_ORIG_AMT", "TEST-001"));
        assertEquals(new BigDecimal("1487.02"), LegacyDataValidator.parseAmount("1,487.02", "PMT_AMT", "TEST-001"));
        assertEquals(new BigDecimal("1500000"), LegacyDataValidator.parseAmount("1,500,000", "PROD_MAX_AMT", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-004: parseAmount returns ZERO for null/blank input")
    void parseAmount_nullOrBlank() {
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount(null, "LN_ORIG_AMT", "TEST-001"));
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount("", "LN_ORIG_AMT", "TEST-001"));
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount("   ", "LN_ORIG_AMT", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-004: parseAmount handles malformed input without throwing")
    void parseAmount_malformed() {
        // Dollar sign prefix (mainframe artifact)
        assertEquals(new BigDecimal("285000"), LegacyDataValidator.parseAmount("$285,000", "LN_ORIG_AMT", "TEST-001"));

        // Completely non-numeric — should return ZERO, not throw
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount("N/A", "BORR_ANN_INCM", "TEST-001"));
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount("TBD", "BORR_ANN_INCM", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-004: parseAmount handles trailing dash (mainframe artifact)")
    void parseAmount_trailingDash() {
        assertEquals(new BigDecimal("285000"), LegacyDataValidator.parseAmount("285,000-", "LN_ORIG_AMT", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-011: parseAmount handles zero amount (VA loan edge case)")
    void parseAmount_zero() {
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount("0", "PROD_MIN_AMT", "VA30"));
    }

    // =========================================================================
    // ANO-004: Numeric strings — parseDecimal
    // =========================================================================

    @Test
    @DisplayName("ANO-004: parseDecimal handles interest rate strings")
    void parseDecimal_interestRate() {
        assertEquals(new BigDecimal("4.750"), LegacyDataValidator.parseDecimal("4.750", "LN_INT_RT", "TEST-001"));
        assertEquals(new BigDecimal("82.5"), LegacyDataValidator.parseDecimal("82.5", "LN_LTV_PCT", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-004: parseDecimal strips percent sign if present")
    void parseDecimal_percentSign() {
        assertEquals(new BigDecimal("4.750"), LegacyDataValidator.parseDecimal("4.750%", "LN_INT_RT", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-004: parseDecimal strips commas (unlike original parseLegacyDecimal)")
    void parseDecimal_withCommas() {
        // Original parseLegacyDecimal did NOT strip commas — this caused NumberFormatException
        assertEquals(new BigDecimal("1234"), LegacyDataValidator.parseDecimal("1,234", "TEST_FIELD", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-004: parseDecimal returns ZERO for malformed input")
    void parseDecimal_malformed() {
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseDecimal("N/A", "LN_INT_RT", "TEST-001"));
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseDecimal(null, "LN_INT_RT", "TEST-001"));
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseDecimal("", "LN_INT_RT", "TEST-001"));
    }

    // =========================================================================
    // ANO-004: Numeric strings — parseInteger
    // =========================================================================

    @Test
    @DisplayName("ANO-004: parseInteger handles credit score strings")
    void parseInteger_creditScore() {
        assertEquals(745, LegacyDataValidator.parseInteger("745", "BORR_CRDT_SCR", "TEST-001"));
        assertEquals(360, LegacyDataValidator.parseInteger("360", "PROD_TERM_MOS", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-004: parseInteger returns null for null/blank")
    void parseInteger_nullOrBlank() {
        assertNull(LegacyDataValidator.parseInteger(null, "BORR_CRDT_SCR", "TEST-001"));
        assertNull(LegacyDataValidator.parseInteger("", "BORR_CRDT_SCR", "TEST-001"));
        assertNull(LegacyDataValidator.parseInteger("   ", "BORR_CRDT_SCR", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-004: parseInteger returns null for non-numeric input (no exception)")
    void parseInteger_malformed() {
        // Original parseLegacyInteger would throw NumberFormatException for "N/A"
        assertNull(LegacyDataValidator.parseInteger("N/A", "BORR_CRDT_SCR", "TEST-001"));
        assertNull(LegacyDataValidator.parseInteger("abc", "BORR_CRDT_SCR", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-004: parseInteger handles comma-formatted integers")
    void parseInteger_withCommas() {
        // Original parseLegacyInteger did NOT strip commas
        assertEquals(1000, LegacyDataValidator.parseInteger("1,000", "TEST_FIELD", "TEST-001"));
    }

    // =========================================================================
    // ANO-010: Date format validation — parseDate
    // =========================================================================

    @Test
    @DisplayName("ANO-010: parseDate parses valid MM/DD/YYYY dates")
    void parseDate_validFormat() {
        assertEquals(LocalDate.of(1978, 3, 15), LegacyDataValidator.parseDate("03/15/1978", "BORR_DOB_DT", "TEST-001"));
        assertEquals(LocalDate.of(2025, 12, 15), LegacyDataValidator.parseDate("12/15/2025", "PMT_DT", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-010: parseDate returns null for invalid date formats")
    void parseDate_invalidFormat() {
        // ISO format (wrong for legacy)
        assertNull(LegacyDataValidator.parseDate("2025-12-15", "PMT_DT", "TEST-001"));
        // DD/MM/YYYY format (European)
        assertNull(LegacyDataValidator.parseDate("15/03/1978", "BORR_DOB_DT", "TEST-001"));
        // Non-date strings
        assertNull(LegacyDataValidator.parseDate("N/A", "BORR_DOB_DT", "TEST-001"));
        assertNull(LegacyDataValidator.parseDate("TBD", "BORR_DOB_DT", "TEST-001"));
    }

    @Test
    @DisplayName("ANO-010: parseDate returns null for null/blank")
    void parseDate_nullOrBlank() {
        assertNull(LegacyDataValidator.parseDate(null, "BORR_DOB_DT", "TEST-001"));
        assertNull(LegacyDataValidator.parseDate("", "BORR_DOB_DT", "TEST-001"));
    }

    // =========================================================================
    // ANO-002: Payment component mismatch validation
    // =========================================================================

    @Test
    @DisplayName("ANO-002: validatePaymentComponents detects sum mismatch")
    void validatePaymentComponents_mismatch() {
        // Simulates the actual ANO-002 anomaly: LN-2019-00142 payments
        BigDecimal total = new BigDecimal("1487.02");
        BigDecimal principal = new BigDecimal("456.78");
        BigDecimal interest = new BigDecimal("1074.69");
        BigDecimal escrow = new BigDecimal("355.55");

        List<String> warnings = LegacyDataValidator.validatePaymentComponents(
                total, principal, interest, escrow, "PMT-2025120001");

        assertFalse(warnings.isEmpty(), "Should detect $400 component mismatch");
        assertTrue(warnings.get(0).contains("400.00"), "Warning should mention the $400 difference");
    }

    @Test
    @DisplayName("ANO-002: validatePaymentComponents passes for correct sums")
    void validatePaymentComponents_correct() {
        // Simulates a correct payment: LN-2020-00398
        BigDecimal total = new BigDecimal("2924.18");
        BigDecimal principal = new BigDecimal("1842.56");
        BigDecimal interest = new BigDecimal("815.50");
        BigDecimal escrow = new BigDecimal("266.12");

        List<String> warnings = LegacyDataValidator.validatePaymentComponents(
                total, principal, interest, escrow, "PMT-2025120002");

        assertTrue(warnings.isEmpty(), "Should not flag a correctly-summing payment");
    }

    @Test
    @DisplayName("ANO-002: validatePaymentComponents allows small rounding tolerance")
    void validatePaymentComponents_withinTolerance() {
        // Sum is off by $0.01 — within tolerance
        BigDecimal total = new BigDecimal("1000.00");
        BigDecimal principal = new BigDecimal("500.00");
        BigDecimal interest = new BigDecimal("400.00");
        BigDecimal escrow = new BigDecimal("100.01");

        List<String> warnings = LegacyDataValidator.validatePaymentComponents(
                total, principal, interest, escrow, "PMT-TOLERANCE");

        assertTrue(warnings.isEmpty(), "Should tolerate $0.01 rounding difference");
    }

    // =========================================================================
    // ANO-006: Delinquency/status inconsistency validation
    // =========================================================================

    @Test
    @DisplayName("ANO-006: validateDelinquencyStatus detects active loan with delinquency")
    void validateDelinquencyStatus_inconsistent() {
        // Simulates ANO-006: LN-2018-00089 has 15 delinquency days but ACT status
        String warning = LegacyDataValidator.validateDelinquencyStatus(15, "ACT", "LN-2018-00089");
        assertNotNull(warning, "Should warn about delinquent but active loan");
        assertTrue(warning.contains("15"), "Warning should mention the delinquency days");
    }

    @Test
    @DisplayName("ANO-006: validateDelinquencyStatus passes for active loan with zero delinquency")
    void validateDelinquencyStatus_consistent() {
        assertNull(LegacyDataValidator.validateDelinquencyStatus(0, "ACT", "LN-2019-00142"));
    }

    @Test
    @DisplayName("ANO-006: validateDelinquencyStatus passes for defaulted loan with delinquency")
    void validateDelinquencyStatus_defaultStatus() {
        assertNull(LegacyDataValidator.validateDelinquencyStatus(90, "DFT", "LN-TEST"));
    }

    @Test
    @DisplayName("ANO-006: validateDelinquencyStatus handles null delinquency days")
    void validateDelinquencyStatus_nullDays() {
        assertNull(LegacyDataValidator.validateDelinquencyStatus(null, "ACT", "LN-TEST"));
    }

    // =========================================================================
    // ANO-001: SSN/phone confusion detection
    // =========================================================================

    @Test
    @DisplayName("ANO-001: validateSsnNotPhoneSuffix detects phone suffix in SSN field")
    void validateSsnNotPhoneSuffix_detected() {
        // Simulates ANO-001: B-10001 has SSN last-4 = phone last 4
        String warning = LegacyDataValidator.validateSsnNotPhoneSuffix("0142", "217-555-0142", "LN-2019-00142");
        assertNotNull(warning, "Should detect SSN matching phone suffix");
        assertTrue(warning.contains("ANO-001"), "Warning should reference ANO-001");
    }

    @Test
    @DisplayName("ANO-001: validateSsnNotPhoneSuffix passes when SSN differs from phone")
    void validateSsnNotPhoneSuffix_clean() {
        // SSN last-4 does NOT match phone suffix
        assertNull(LegacyDataValidator.validateSsnNotPhoneSuffix("9876", "217-555-0142", "LN-TEST"));
    }

    @Test
    @DisplayName("ANO-001: validateSsnNotPhoneSuffix handles null inputs")
    void validateSsnNotPhoneSuffix_nulls() {
        assertNull(LegacyDataValidator.validateSsnNotPhoneSuffix(null, "217-555-0142", "LN-TEST"));
        assertNull(LegacyDataValidator.validateSsnNotPhoneSuffix("0142", null, "LN-TEST"));
    }

    // =========================================================================
    // Status code validation
    // =========================================================================

    @Test
    @DisplayName("validateStatusCode accepts valid loan status codes")
    void validateStatusCode_validLoanCodes() {
        assertEquals("ACT", LegacyDataValidator.validateStatusCode("ACT",
                LegacyDataValidator.getValidLoanStatusCodes(), "LN_STAT_CD", "TEST-001"));
        assertEquals("CLO", LegacyDataValidator.validateStatusCode("CLO",
                LegacyDataValidator.getValidLoanStatusCodes(), "LN_STAT_CD", "TEST-001"));
        assertEquals("DFT", LegacyDataValidator.validateStatusCode("DFT",
                LegacyDataValidator.getValidLoanStatusCodes(), "LN_STAT_CD", "TEST-001"));
        assertEquals("FRB", LegacyDataValidator.validateStatusCode("FRB",
                LegacyDataValidator.getValidLoanStatusCodes(), "LN_STAT_CD", "TEST-001"));
    }

    @Test
    @DisplayName("validateStatusCode returns UNKNOWN for null/blank codes")
    void validateStatusCode_nullOrBlank() {
        assertEquals("UNKNOWN", LegacyDataValidator.validateStatusCode(null,
                LegacyDataValidator.getValidLoanStatusCodes(), "LN_STAT_CD", "TEST-001"));
        assertEquals("UNKNOWN", LegacyDataValidator.validateStatusCode("",
                LegacyDataValidator.getValidLoanStatusCodes(), "LN_STAT_CD", "TEST-001"));
    }

    @Test
    @DisplayName("validateStatusCode logs error for invalid codes but returns as-is")
    void validateStatusCode_invalid() {
        // Invalid code should be returned as-is (for display) but error is logged
        assertEquals("XYZ", LegacyDataValidator.validateStatusCode("XYZ",
                LegacyDataValidator.getValidLoanStatusCodes(), "LN_STAT_CD", "TEST-001"));
    }

    @Test
    @DisplayName("validateStatusCode validates payment type codes")
    void validateStatusCode_paymentTypes() {
        Set<String> validCodes = LegacyDataValidator.getValidPaymentTypeCodes();
        assertEquals("REG", LegacyDataValidator.validateStatusCode("REG", validCodes, "PMT_TYP_CD", "TEST-001"));
        assertEquals("EXT", LegacyDataValidator.validateStatusCode("EXT", validCodes, "PMT_TYP_CD", "TEST-001"));
    }

    // =========================================================================
    // ANO-007: Required field / null validation
    // =========================================================================

    @Test
    @DisplayName("ANO-007: requireNonBlank returns value when present")
    void requireNonBlank_present() {
        assertEquals("James", LegacyDataValidator.requireNonBlank("James", "BORR_FST_NM", "B-10001", "Unknown"));
    }

    @Test
    @DisplayName("ANO-007: requireNonBlank returns default for null/blank")
    void requireNonBlank_absent() {
        assertEquals("Unknown", LegacyDataValidator.requireNonBlank(null, "BORR_FST_NM", "B-10001", "Unknown"));
        assertEquals("Unknown", LegacyDataValidator.requireNonBlank("", "BORR_FST_NM", "B-10001", "Unknown"));
        assertEquals("Unknown", LegacyDataValidator.requireNonBlank("   ", "BORR_FST_NM", "B-10001", "Unknown"));
    }

    // =========================================================================
    // Credit score validation
    // =========================================================================

    @Test
    @DisplayName("validateCreditScore accepts scores in valid range (300-850)")
    void validateCreditScore_valid() {
        assertEquals(745, LegacyDataValidator.validateCreditScore(745, "B-10001"));
        assertEquals(300, LegacyDataValidator.validateCreditScore(300, "B-TEST"));
        assertEquals(850, LegacyDataValidator.validateCreditScore(850, "B-TEST"));
    }

    @Test
    @DisplayName("validateCreditScore rejects out-of-range scores")
    void validateCreditScore_outOfRange() {
        assertNull(LegacyDataValidator.validateCreditScore(200, "B-TEST"));
        assertNull(LegacyDataValidator.validateCreditScore(900, "B-TEST"));
        assertNull(LegacyDataValidator.validateCreditScore(-1, "B-TEST"));
    }

    @Test
    @DisplayName("validateCreditScore handles null input")
    void validateCreditScore_null() {
        assertNull(LegacyDataValidator.validateCreditScore(null, "B-TEST"));
    }

    // =========================================================================
    // ANO-009: LTV percent validation
    // =========================================================================

    @Test
    @DisplayName("ANO-009: validateLtvPercent detects discrepancy")
    void validateLtvPercent_discrepancy() {
        // LN-2019-00142: stored 82.5, computed 285000/345000*100 = 82.61
        BigDecimal storedLtv = new BigDecimal("82.5");
        BigDecimal originalAmount = new BigDecimal("285000");
        BigDecimal appraisedValue = new BigDecimal("345000");

        // Within 0.5% tolerance, so should NOT warn
        String warning = LegacyDataValidator.validateLtvPercent(storedLtv, originalAmount, appraisedValue, "LN-2019-00142");
        assertNull(warning, "0.11% discrepancy is within 0.5% tolerance");
    }

    @Test
    @DisplayName("ANO-009: validateLtvPercent flags large discrepancy")
    void validateLtvPercent_largeDiscrepancy() {
        BigDecimal storedLtv = new BigDecimal("75.0");
        BigDecimal originalAmount = new BigDecimal("285000");
        BigDecimal appraisedValue = new BigDecimal("345000"); // computed = 82.61

        String warning = LegacyDataValidator.validateLtvPercent(storedLtv, originalAmount, appraisedValue, "LN-TEST");
        assertNotNull(warning, "7.61% discrepancy should be flagged");
    }

    @Test
    @DisplayName("ANO-009: validateLtvPercent handles null/zero values")
    void validateLtvPercent_nullInputs() {
        assertNull(LegacyDataValidator.validateLtvPercent(null, new BigDecimal("100"), new BigDecimal("200"), "LN-TEST"));
        assertNull(LegacyDataValidator.validateLtvPercent(new BigDecimal("50"), null, new BigDecimal("200"), "LN-TEST"));
        assertNull(LegacyDataValidator.validateLtvPercent(new BigDecimal("50"), new BigDecimal("100"), BigDecimal.ZERO, "LN-TEST"));
    }
}
