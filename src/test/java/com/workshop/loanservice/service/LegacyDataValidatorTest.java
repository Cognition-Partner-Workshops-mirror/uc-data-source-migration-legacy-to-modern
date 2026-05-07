package com.workshop.loanservice.service;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    // =========================================================================
    // parseAmount tests
    // =========================================================================

    @Test
    void parseAmount_validAmountWithCommas() {
        BigDecimal result = LegacyDataValidator.parseAmount("285,000", "TEST", "REC-1");
        assertEquals(new BigDecimal("285000"), result);
    }

    @Test
    void parseAmount_validDecimalWithCommas() {
        BigDecimal result = LegacyDataValidator.parseAmount("1,487.02", "TEST", "REC-1");
        assertEquals(new BigDecimal("1487.02"), result);
    }

    @Test
    void parseAmount_nullReturnsZero() {
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount(null, "TEST", "REC-1"));
    }

    @Test
    void parseAmount_blankReturnsZero() {
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount("  ", "TEST", "REC-1"));
    }

    @Test
    void parseAmount_malformedStringReturnsZero() {
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount("N/A", "TEST", "REC-1"));
    }

    @Test
    void parseAmount_dollarSignStripped() {
        BigDecimal result = LegacyDataValidator.parseAmount("$285,000", "TEST", "REC-1");
        assertEquals(new BigDecimal("285000"), result);
    }

    @Test
    void parseAmount_parenthesesNegative() {
        BigDecimal result = LegacyDataValidator.parseAmount("(1,200)", "TEST", "REC-1");
        assertEquals(new BigDecimal("-1200"), result);
    }

    @Test
    void parseAmount_textPlaceholderReturnsZero() {
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseAmount("TBD", "TEST", "REC-1"));
    }

    // =========================================================================
    // parseDecimal tests
    // =========================================================================

    @Test
    void parseDecimal_validRate() {
        BigDecimal result = LegacyDataValidator.parseDecimal("4.750", "TEST", "REC-1");
        assertEquals(new BigDecimal("4.750"), result);
    }

    @Test
    void parseDecimal_nullReturnsZero() {
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseDecimal(null, "TEST", "REC-1"));
    }

    @Test
    void parseDecimal_malformedReturnsZero() {
        assertEquals(BigDecimal.ZERO, LegacyDataValidator.parseDecimal("abc", "TEST", "REC-1"));
    }

    @Test
    void parseDecimal_whitespaceTrimmed() {
        BigDecimal result = LegacyDataValidator.parseDecimal("  3.125  ", "TEST", "REC-1");
        assertEquals(new BigDecimal("3.125"), result);
    }

    // =========================================================================
    // parseInteger tests
    // =========================================================================

    @Test
    void parseInteger_validCreditScore() {
        assertEquals(745, LegacyDataValidator.parseInteger("745", "TEST", "REC-1"));
    }

    @Test
    void parseInteger_nullReturnsNull() {
        assertNull(LegacyDataValidator.parseInteger(null, "TEST", "REC-1"));
    }

    @Test
    void parseInteger_blankReturnsNull() {
        assertNull(LegacyDataValidator.parseInteger("", "TEST", "REC-1"));
    }

    @Test
    void parseInteger_malformedReturnsNull() {
        assertNull(LegacyDataValidator.parseInteger("N/A", "TEST", "REC-1"));
    }

    @Test
    void parseInteger_decimalReturnsNull() {
        assertNull(LegacyDataValidator.parseInteger("745.5", "TEST", "REC-1"));
    }

    @Test
    void parseInteger_withCommasStripped() {
        assertEquals(1000, LegacyDataValidator.parseInteger("1,000", "TEST", "REC-1"));
    }

    // =========================================================================
    // parseDate tests
    // =========================================================================

    @Test
    void parseDate_validDate() {
        assertEquals("2019-02-15", LegacyDataValidator.parseDate("02/15/2019", "TEST", "REC-1"));
    }

    @Test
    void parseDate_nullReturnsNull() {
        assertNull(LegacyDataValidator.parseDate(null, "TEST", "REC-1"));
    }

    @Test
    void parseDate_invalidDateReturnsRaw() {
        assertEquals("13/01/2020", LegacyDataValidator.parseDate("13/01/2020", "TEST", "REC-1"));
    }

    @Test
    void parseDate_textPlaceholderReturnsRaw() {
        assertEquals("TBD", LegacyDataValidator.parseDate("TBD", "TEST", "REC-1"));
    }

    @Test
    void parseDate_invalidDayParsedLeniently() {
        // Java DateTimeFormatter resolves Feb 30 to end-of-month (Feb 28)
        String result = LegacyDataValidator.parseDate("02/30/2025", "TEST", "REC-1");
        assertEquals("2025-02-28", result);
    }

    // =========================================================================
    // validatePaymentComponents tests
    // =========================================================================

    @Test
    void validatePaymentComponents_balanced() {
        List<String> warnings = LegacyDataValidator.validatePaymentComponents(
                "PMT-1",
                new BigDecimal("2924.18"),
                new BigDecimal("1842.56"),
                new BigDecimal("815.50"),
                new BigDecimal("266.12"),
                new BigDecimal("0.00"));
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validatePaymentComponents_mismatchDetected() {
        List<String> warnings = LegacyDataValidator.validatePaymentComponents(
                "PMT-2025120001",
                new BigDecimal("1487.02"),
                new BigDecimal("456.78"),
                new BigDecimal("1074.69"),
                new BigDecimal("355.55"),
                new BigDecimal("0.00"));
        assertEquals(1, warnings.size());
        assertTrue(warnings.get(0).contains("PMT-2025120001"));
        assertTrue(warnings.get(0).contains("delta"));
    }

    @Test
    void validatePaymentComponents_lateFeeMismatch() {
        List<String> warnings = LegacyDataValidator.validatePaymentComponents(
                "PMT-2025110003",
                new BigDecimal("1077.05"),
                new BigDecimal("295.82"),
                new BigDecimal("781.23"),
                new BigDecimal("0.00"),
                new BigDecimal("47.50"));
        assertEquals(1, warnings.size());
        assertTrue(warnings.get(0).contains("PMT-2025110003"));
    }

    // =========================================================================
    // validateLoanStatusConsistency tests
    // =========================================================================

    @Test
    void validateLoanStatusConsistency_healthyLoan() {
        List<String> warnings = LegacyDataValidator.validateLoanStatusConsistency(
                "LN-1", "ACT", "0");
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLoanStatusConsistency_delinquentButActive() {
        List<String> warnings = LegacyDataValidator.validateLoanStatusConsistency(
                "LN-2018-00089", "ACT", "15");
        assertEquals(1, warnings.size());
        assertTrue(warnings.get(0).contains("15 delinquency days"));
        assertTrue(warnings.get(0).contains("ACT"));
    }

    @Test
    void validateLoanStatusConsistency_delinquentAndDefaultIsOk() {
        List<String> warnings = LegacyDataValidator.validateLoanStatusConsistency(
                "LN-1", "DFT", "30");
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLoanStatusConsistency_nullDelinquencyDays() {
        List<String> warnings = LegacyDataValidator.validateLoanStatusConsistency(
                "LN-1", "ACT", null);
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // validateBorrowerReference tests
    // =========================================================================

    @Test
    void validateBorrowerReference_existsNoWarning() {
        assertNull(LegacyDataValidator.validateBorrowerReference("LN-1", "B-10001", true));
    }

    @Test
    void validateBorrowerReference_missingReturnsWarning() {
        String warning = LegacyDataValidator.validateBorrowerReference("LN-1", "B-99999", false);
        assertNotNull(warning);
        assertTrue(warning.contains("non-existent borrower"));
        assertTrue(warning.contains("B-99999"));
    }

    // =========================================================================
    // validateProductReference tests
    // =========================================================================

    @Test
    void validateProductReference_existsNoWarning() {
        assertNull(LegacyDataValidator.validateProductReference("LN-1", "FXD30", true));
    }

    @Test
    void validateProductReference_missingReturnsWarning() {
        String warning = LegacyDataValidator.validateProductReference("LN-1", "INVALID", false);
        assertNotNull(warning);
        assertTrue(warning.contains("non-existent product"));
    }

    // =========================================================================
    // validateDenormalizedBorrowerName tests
    // =========================================================================

    @Test
    void validateDenormalizedBorrowerName_matchNoWarning() {
        assertNull(LegacyDataValidator.validateDenormalizedBorrowerName(
                "LN-1", "James", "Mitchell", "James", "Mitchell"));
    }

    @Test
    void validateDenormalizedBorrowerName_mismatchReturnsWarning() {
        String warning = LegacyDataValidator.validateDenormalizedBorrowerName(
                "LN-1", "Jim", "Mitchell", "James", "Mitchell");
        assertNotNull(warning);
        assertTrue(warning.contains("differs from master"));
    }

    @Test
    void validateDenormalizedBorrowerName_bothNullMatch() {
        assertNull(LegacyDataValidator.validateDenormalizedBorrowerName(
                "LN-1", null, null, null, null));
    }

    // =========================================================================
    // validatePaymentTiming tests
    // =========================================================================

    @Test
    void validatePaymentTiming_onTimeNoWarning() {
        assertNull(LegacyDataValidator.validatePaymentTiming(
                "PMT-1", "12/01/2025", "11/30/2025", BigDecimal.ZERO));
    }

    @Test
    void validatePaymentTiming_lateNoFeeReturnsWarning() {
        String warning = LegacyDataValidator.validatePaymentTiming(
                "PMT-2025120003", "12/01/2025", "12/05/2025", BigDecimal.ZERO);
        assertNotNull(warning);
        assertTrue(warning.contains("no late fee"));
    }

    @Test
    void validatePaymentTiming_lateWithFeeNoWarning() {
        assertNull(LegacyDataValidator.validatePaymentTiming(
                "PMT-1", "11/01/2025", "11/18/2025", new BigDecimal("47.50")));
    }

    @Test
    void validatePaymentTiming_nullDatesNoWarning() {
        assertNull(LegacyDataValidator.validatePaymentTiming(
                "PMT-1", null, null, BigDecimal.ZERO));
    }
}
