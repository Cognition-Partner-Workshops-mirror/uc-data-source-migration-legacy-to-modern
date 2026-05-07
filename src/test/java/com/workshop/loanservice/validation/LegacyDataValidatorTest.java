package com.workshop.loanservice.validation;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANM-001: Loose Typing — numeric parsing with error handling
    // =========================================================================

    @Test
    void parseAmount_validAmountWithCommas() {
        BigDecimal result = validator.parseAmount("285,000", "originalAmount", "LN-001");
        assertEquals(new BigDecimal("285000"), result);
    }

    @Test
    void parseAmount_validAmountWithCommasAndDecimals() {
        BigDecimal result = validator.parseAmount("1,487.02", "monthlyPayment", "LN-001");
        assertEquals(new BigDecimal("1487.02"), result);
    }

    @Test
    void parseAmount_dollarSign() {
        BigDecimal result = validator.parseAmount("$285,000", "originalAmount", "LN-001");
        assertEquals(new BigDecimal("285000"), result);
    }

    @Test
    void parseAmount_unparseableString() {
        BigDecimal result = validator.parseAmount("N/A", "originalAmount", "LN-001");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    void parseAmount_doubleDecimalPoint() {
        BigDecimal result = validator.parseAmount("285000.00.00", "originalAmount", "LN-001");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    void parseDecimal_validDecimal() {
        BigDecimal result = validator.parseDecimal("5.250", "interestRate", "LN-001");
        assertEquals(new BigDecimal("5.250"), result);
    }

    @Test
    void parseDecimal_withComma() {
        BigDecimal result = validator.parseDecimal("5,250", "interestRate", "LN-001");
        assertEquals(new BigDecimal("5250"), result);
    }

    @Test
    void parseDecimal_unparseableString() {
        BigDecimal result = validator.parseDecimal("abc", "interestRate", "LN-001");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    void parseInteger_validInteger() {
        Integer result = validator.parseInteger("360", "termMonths", "LN-001");
        assertEquals(360, result);
    }

    @Test
    void parseInteger_unparseableString() {
        Integer result = validator.parseInteger("N/A", "termMonths", "LN-001");
        assertNull(result);
    }

    @Test
    void parseInteger_withWhitespace() {
        Integer result = validator.parseInteger("  360  ", "termMonths", "LN-001");
        assertEquals(360, result);
    }

    // =========================================================================
    // ANM-002: Null/blank required fields
    // =========================================================================

    @Test
    void parseAmount_nullReturnsZero() {
        BigDecimal result = validator.parseAmount(null, "originalAmount", "LN-001");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    void parseAmount_blankReturnsZero() {
        BigDecimal result = validator.parseAmount("   ", "originalAmount", "LN-001");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    void parseDecimal_nullReturnsZero() {
        BigDecimal result = validator.parseDecimal(null, "interestRate", "LN-001");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    void parseInteger_nullReturnsNull() {
        Integer result = validator.parseInteger(null, "creditScore", "B-001");
        assertNull(result);
    }

    @Test
    void parseInteger_blankReturnsNull() {
        Integer result = validator.parseInteger("", "creditScore", "B-001");
        assertNull(result);
    }

    @Test
    void validateRequiredString_nullReturnsFallback() {
        String result = validator.validateRequiredString(null, "firstName", "B-001", "[Unknown]");
        assertEquals("[Unknown]", result);
    }

    @Test
    void validateRequiredString_blankReturnsFallback() {
        String result = validator.validateRequiredString("  ", "firstName", "B-001", "[Unknown]");
        assertEquals("[Unknown]", result);
    }

    @Test
    void validateRequiredString_validReturnsValue() {
        String result = validator.validateRequiredString("James", "firstName", "B-001", "[Unknown]");
        assertEquals("James", result);
    }

    // =========================================================================
    // ANM-003: Orphaned records (foreign key validation)
    // =========================================================================

    @Test
    void validateForeignKey_validKey() {
        Set<String> validKeys = Set.of("B-10001", "B-10002", "B-10003");
        assertTrue(validator.validateForeignKey("B-10001", validKeys, "BORR_ID", "LN-001"));
    }

    @Test
    void validateForeignKey_orphanedKey() {
        Set<String> validKeys = Set.of("B-10001", "B-10002");
        assertFalse(validator.validateForeignKey("B-99999", validKeys, "BORR_ID", "LN-001"));
    }

    @Test
    void validateForeignKey_nullKey() {
        Set<String> validKeys = Set.of("B-10001");
        assertFalse(validator.validateForeignKey(null, validKeys, "BORR_ID", "LN-001"));
    }

    @Test
    void validateForeignKey_blankKey() {
        Set<String> validKeys = Set.of("B-10001");
        assertFalse(validator.validateForeignKey("  ", validKeys, "BORR_ID", "LN-001"));
    }

    // =========================================================================
    // ANM-004: Date format inconsistencies
    // =========================================================================

    @Test
    void parseDate_validMmDdYyyy() {
        LocalDate result = validator.parseDate("03/15/1978", "dateOfBirth", "B-001");
        assertEquals(LocalDate.of(1978, 3, 15), result);
    }

    @Test
    void parseDate_isoFormat() {
        LocalDate result = validator.parseDate("2025-03-15", "dateOfBirth", "B-001");
        assertNull(result);
    }

    @Test
    void parseDate_ddMmYyyy() {
        LocalDate result = validator.parseDate("15/03/1978", "dateOfBirth", "B-001");
        assertNull(result);
    }

    @Test
    void parseDate_nullReturnsNull() {
        LocalDate result = validator.parseDate(null, "dateOfBirth", "B-001");
        assertNull(result);
    }

    @Test
    void parseDate_blankReturnsNull() {
        LocalDate result = validator.parseDate("", "dateOfBirth", "B-001");
        assertNull(result);
    }

    @Test
    void parseDate_garbageReturnsNull() {
        LocalDate result = validator.parseDate("March 15", "dateOfBirth", "B-001");
        assertNull(result);
    }

    @Test
    void formatDateIso_validDate() {
        assertEquals("2025-03-15", validator.formatDateIso(LocalDate.of(2025, 3, 15)));
    }

    @Test
    void formatDateIso_nullReturnsNA() {
        assertEquals("N/A", validator.formatDateIso(null));
    }

    // =========================================================================
    // ANM-005: Financial amounts with dollar signs and special characters
    // =========================================================================

    @Test
    void parseAmount_dollarSignAndCommas() {
        BigDecimal result = validator.parseAmount("$1,487.02", "amount", "PMT-001");
        assertEquals(new BigDecimal("1487.02"), result);
    }

    @Test
    void parseAmount_spacesInAmount() {
        BigDecimal result = validator.parseAmount("  285,000  ", "amount", "LN-001");
        assertEquals(new BigDecimal("285000"), result);
    }

    // =========================================================================
    // ANM-006: Payment component sum mismatch
    // =========================================================================

    @Test
    void validatePaymentSum_componentsMatchTotal() {
        List<String> warnings = validator.validatePaymentSum(
                new BigDecimal("2924.18"),
                new BigDecimal("1842.56"),
                new BigDecimal("815.50"),
                new BigDecimal("266.12"),
                new BigDecimal("0.00"),
                "PMT-001");
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validatePaymentSum_componentsExceedTotal() {
        // PMT-2025120001: total=1487.02, components sum=1887.02 ($400 discrepancy)
        List<String> warnings = validator.validatePaymentSum(
                new BigDecimal("1487.02"),
                new BigDecimal("456.78"),
                new BigDecimal("1074.69"),
                new BigDecimal("355.55"),
                new BigDecimal("0.00"),
                "PMT-2025120001");
        assertEquals(1, warnings.size());
        assertTrue(warnings.get(0).contains("ANM-006"));
        assertTrue(warnings.get(0).contains("400.00"));
    }

    @Test
    void validatePaymentSum_lateFeeNotIncludedInTotal() {
        // PMT-2025110003: total=1077.05, late_fee=47.50 not reflected in total
        List<String> warnings = validator.validatePaymentSum(
                new BigDecimal("1077.05"),
                new BigDecimal("295.82"),
                new BigDecimal("781.23"),
                new BigDecimal("0.00"),
                new BigDecimal("47.50"),
                "PMT-2025110003");
        assertEquals(1, warnings.size());
        assertTrue(warnings.get(0).contains("ANM-006"));
        assertTrue(warnings.get(0).contains("47.50"));
    }

    // =========================================================================
    // ANM-008: Delinquency days vs status code inconsistency
    // =========================================================================

    @Test
    void validateDelinquencyStatus_delinquentButActive() {
        List<String> warnings = validator.validateDelinquencyStatus("15", "ACT", "LN-2018-00089");
        assertEquals(1, warnings.size());
        assertTrue(warnings.get(0).contains("ANM-008"));
        assertTrue(warnings.get(0).contains("15 delinquency days"));
    }

    @Test
    void validateDelinquencyStatus_zeroDaysActive() {
        List<String> warnings = validator.validateDelinquencyStatus("0", "ACT", "LN-001");
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateDelinquencyStatus_delinquentAndDefaultStatus() {
        List<String> warnings = validator.validateDelinquencyStatus("90", "DFT", "LN-001");
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateDelinquencyStatus_nullDays() {
        List<String> warnings = validator.validateDelinquencyStatus(null, "ACT", "LN-001");
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // ANM-009: Credit score range validation
    // =========================================================================

    @Test
    void validateCreditScore_validScore() {
        Integer result = validator.validateCreditScore("745", "B-001");
        assertEquals(745, result);
    }

    @Test
    void validateCreditScore_tooLow() {
        Integer result = validator.validateCreditScore("100", "B-001");
        assertNull(result);
    }

    @Test
    void validateCreditScore_tooHigh() {
        Integer result = validator.validateCreditScore("9999", "B-001");
        assertNull(result);
    }

    @Test
    void validateCreditScore_nonNumeric() {
        Integer result = validator.validateCreditScore("N/A", "B-001");
        assertNull(result);
    }

    @Test
    void validateCreditScore_nullValue() {
        Integer result = validator.validateCreditScore(null, "B-001");
        assertNull(result);
    }

    @Test
    void validateCreditScore_boundaryMin() {
        Integer result = validator.validateCreditScore("300", "B-001");
        assertEquals(300, result);
    }

    @Test
    void validateCreditScore_boundaryMax() {
        Integer result = validator.validateCreditScore("850", "B-001");
        assertEquals(850, result);
    }

    // =========================================================================
    // ANM-011: LTV percent cross-validation
    // =========================================================================

    @Test
    void validateLtvPercent_withinTolerance() {
        // 285000/345000*100 = 82.6%, stored as 82.5 — diff = 0.1 < 0.5
        List<String> warnings = validator.validateLtvPercent("82.5", "285,000", "345,000", "LN-001");
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLtvPercent_outsideTolerance() {
        // Stored LTV=90, calculated=82.6 — diff=7.4 > 0.5
        List<String> warnings = validator.validateLtvPercent("90.0", "285,000", "345,000", "LN-001");
        assertEquals(1, warnings.size());
        assertTrue(warnings.get(0).contains("ANM-011"));
    }

    @Test
    void validateLtvPercent_zeroAppraisedValue() {
        List<String> warnings = validator.validateLtvPercent("82.5", "285,000", "0", "LN-001");
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // ANM-012: Payment date ordering
    // =========================================================================

    @Test
    void validatePaymentDateOrder_normalOrder() {
        List<String> warnings = validator.validatePaymentDateOrder(
                "12/01/2025", "12/01/2025", "PMT-001");
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validatePaymentDateOrder_receivedSameDay() {
        List<String> warnings = validator.validatePaymentDateOrder(
                "12/15/2025", "12/14/2025", "PMT-001");
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validatePaymentDateOrder_largeGap() {
        // PMT-2025110003: payment 11/01, received 11/18 — 17-day gap
        List<String> warnings = validator.validatePaymentDateOrder(
                "11/01/2025", "11/18/2025", "PMT-2025110003");
        assertEquals(1, warnings.size());
        assertTrue(warnings.get(0).contains("ANM-012"));
        assertTrue(warnings.get(0).contains("17 days"));
    }

    @Test
    void validatePaymentDateOrder_nullDates() {
        List<String> warnings = validator.validatePaymentDateOrder(null, "12/01/2025", "PMT-001");
        assertTrue(warnings.isEmpty());
    }
}
