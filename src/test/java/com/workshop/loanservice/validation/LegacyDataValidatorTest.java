package com.workshop.loanservice.validation;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    // ===== parseAmount =====

    @Test
    void parseAmount_withCommas_succeeds() {
        BigDecimal result = LegacyDataValidator.parseAmount("285,000", "testField");
        assertEquals(new BigDecimal("285000"), result);
    }

    @Test
    void parseAmount_withDollarSign_succeeds() {
        BigDecimal result = LegacyDataValidator.parseAmount("$1,487.02", "testField");
        assertEquals(new BigDecimal("1487.02"), result);
    }

    @Test
    void parseAmount_withInvalidString_returnsZero() {
        BigDecimal result = LegacyDataValidator.parseAmount("PENDING", "testField");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    void parseAmount_withNull_returnsZero() {
        BigDecimal result = LegacyDataValidator.parseAmount(null, "testField");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    void parseAmount_withBlank_returnsZero() {
        BigDecimal result = LegacyDataValidator.parseAmount("   ", "testField");
        assertEquals(BigDecimal.ZERO, result);
    }

    // ===== parseInteger =====

    @Test
    void parseInteger_withValidNumber_succeeds() {
        Integer result = LegacyDataValidator.parseInteger("745", "testField");
        assertEquals(745, result);
    }

    @Test
    void parseInteger_withCommas_succeeds() {
        Integer result = LegacyDataValidator.parseInteger("1,200", "testField");
        assertEquals(1200, result);
    }

    @Test
    void parseInteger_withInvalidString_returnsNull() {
        Integer result = LegacyDataValidator.parseInteger("N/A", "testField");
        assertNull(result);
    }

    @Test
    void parseInteger_withNull_returnsNull() {
        Integer result = LegacyDataValidator.parseInteger(null, "testField");
        assertNull(result);
    }

    // ===== parseDate =====

    @Test
    void parseDate_withValidMMDDYYYY_succeeds() {
        LocalDate result = LegacyDataValidator.parseDate("01/15/2025", "testField");
        assertEquals(LocalDate.of(2025, 1, 15), result);
    }

    @Test
    void parseDate_withISOFormat_returnsNull() {
        LocalDate result = LegacyDataValidator.parseDate("2025-01-15", "testField");
        assertNull(result);
    }

    @Test
    void parseDate_withInvalidDate_returnsNull() {
        LocalDate result = LegacyDataValidator.parseDate("13/32/2025", "testField");
        assertNull(result);
    }

    @Test
    void parseDate_withNull_returnsNull() {
        LocalDate result = LegacyDataValidator.parseDate(null, "testField");
        assertNull(result);
    }

    // ===== validatePaymentComponents =====

    @Test
    void validatePaymentComponents_matchingSum_noWarnings() {
        List<String> warnings = LegacyDataValidator.validatePaymentComponents(
                new BigDecimal("1000.00"),
                new BigDecimal("500.00"),
                new BigDecimal("300.00"),
                new BigDecimal("150.00"),
                new BigDecimal("50.00"),
                "PMT-TEST-001");
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validatePaymentComponents_mismatchedSum_returnsWarning() {
        List<String> warnings = LegacyDataValidator.validatePaymentComponents(
                new BigDecimal("1487.02"),
                new BigDecimal("456.78"),
                new BigDecimal("1074.69"),
                new BigDecimal("355.55"),
                new BigDecimal("0.00"),
                "PMT-2025120001");
        assertEquals(1, warnings.size());
        assertTrue(warnings.get(0).contains("PMT-2025120001"));
        assertTrue(warnings.get(0).contains("component sum"));
    }

    // ===== validateLoanStatusConsistency =====

    @Test
    void validateLoanStatusConsistency_activeWithDelinquency_returnsWarning() {
        String warning = LegacyDataValidator.validateLoanStatusConsistency("ACT", "15", "LN-TEST-001");
        assertNotNull(warning);
        assertTrue(warning.contains("LN-TEST-001"));
        assertTrue(warning.contains("ACT"));
        assertTrue(warning.contains("15"));
    }

    @Test
    void validateLoanStatusConsistency_activeWithZeroDelinquency_returnsNull() {
        String warning = LegacyDataValidator.validateLoanStatusConsistency("ACT", "0", "LN-TEST-002");
        assertNull(warning);
    }

    // ===== parseDecimal =====

    @Test
    void parseDecimal_withValidValue_succeeds() {
        BigDecimal result = LegacyDataValidator.parseDecimal("4.750", "testField");
        assertEquals(new BigDecimal("4.750"), result);
    }

    @Test
    void parseDecimal_withInvalidValue_returnsZero() {
        BigDecimal result = LegacyDataValidator.parseDecimal("abc", "testField");
        assertEquals(BigDecimal.ZERO, result);
    }

    // ===== validateDateFormat =====

    @Test
    void validateDateFormat_withValidDate_returnsOriginal() {
        String result = LegacyDataValidator.validateDateFormat("02/15/2019", "testField");
        assertEquals("02/15/2019", result);
    }

    @Test
    void validateDateFormat_withInvalidDate_returnsNull() {
        String result = LegacyDataValidator.validateDateFormat("not-a-date", "testField");
        assertNull(result);
    }

    // ===== isPresent =====

    @Test
    void isPresent_withValue_returnsTrue() {
        assertTrue(LegacyDataValidator.isPresent("hello", "field", "record1"));
    }

    @Test
    void isPresent_withNull_returnsFalse() {
        assertFalse(LegacyDataValidator.isPresent(null, "field", "record1"));
    }

    @Test
    void isPresent_withBlank_returnsFalse() {
        assertFalse(LegacyDataValidator.isPresent("  ", "field", "record1"));
    }
}
