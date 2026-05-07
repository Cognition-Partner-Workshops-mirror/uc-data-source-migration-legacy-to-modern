package com.workshop.loanservice.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for LegacyDataValidator covering all anomaly types from DATA_ANOMALY_REPORT.md.
 * Each test section maps to a specific anomaly ID (ANM-001 through ANM-012).
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANM-002: Financial amounts as comma-formatted strings
    // =========================================================================

    @Test
    void parseAmount_validCommaFormatted() {
        BigDecimal result = validator.parseAmount("285,000", "testField", "REC-1");
        assertEquals(new BigDecimal("285000"), result);
    }

    @Test
    void parseAmount_validDecimalWithCommas() {
        BigDecimal result = validator.parseAmount("1,487.02", "testField", "REC-1");
        assertEquals(new BigDecimal("1487.02"), result);
    }

    @Test
    void parseAmount_nullReturnsNull() {
        assertNull(validator.parseAmount(null, "testField", "REC-1"));
    }

    @Test
    void parseAmount_blankReturnsNull() {
        assertNull(validator.parseAmount("  ", "testField", "REC-1"));
    }

    @Test
    void parseAmount_dollarSignStripped() {
        BigDecimal result = validator.parseAmount("$285,000", "testField", "REC-1");
        assertEquals(new BigDecimal("285000"), result);
    }

    @Test
    void parseAmount_completelyInvalidReturnsNull() {
        assertNull(validator.parseAmount("N/A", "testField", "REC-1"));
    }

    @Test
    void parseAmountWithDefault_nullUsesDefault() {
        BigDecimal result = validator.parseAmountWithDefault(null, "testField", "REC-1", BigDecimal.ZERO);
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    void parseAmountWithDefault_validIgnoresDefault() {
        BigDecimal result = validator.parseAmountWithDefault("1,000", "testField", "REC-1", BigDecimal.ZERO);
        assertEquals(new BigDecimal("1000"), result);
    }

    // =========================================================================
    // ANM-003: Date format inconsistencies
    // =========================================================================

    @Test
    void parseDate_validMMDDYYYY() {
        LocalDate result = validator.parseDate("03/15/1978", "testField", "REC-1");
        assertEquals(LocalDate.of(1978, 3, 15), result);
    }

    @Test
    void parseDate_nullReturnsNull() {
        assertNull(validator.parseDate(null, "testField", "REC-1"));
    }

    @Test
    void parseDate_invalidFormatReturnsNull() {
        assertNull(validator.parseDate("1978-03-15", "testField", "REC-1"));
    }

    @Test
    void parseDate_garbageReturnsNull() {
        assertNull(validator.parseDate("not-a-date", "testField", "REC-1"));
    }

    @Test
    void parseDate_wrongOrder_DDMMYYYY_ReturnsNullOrWrongDate() {
        // "15/03/1978" — month=15 is invalid, should return null
        assertNull(validator.parseDate("15/03/1978", "testField", "REC-1"));
    }

    // =========================================================================
    // ANM-004: Orphaned records (foreign key violations)
    // =========================================================================

    @Test
    void validateForeignKey_validKey() {
        Set<String> validKeys = Set.of("B-10001", "B-10002", "B-10003");
        assertTrue(validator.validateForeignKey("B-10001", validKeys, "BORR_ID", "LN-001"));
    }

    @Test
    void validateForeignKey_orphanedRecord() {
        Set<String> validKeys = Set.of("B-10001", "B-10002");
        assertFalse(validator.validateForeignKey("B-99999", validKeys, "BORR_ID", "LN-001"));
    }

    @Test
    void validateForeignKey_nullKey() {
        Set<String> validKeys = Set.of("B-10001");
        assertFalse(validator.validateForeignKey(null, validKeys, "BORR_ID", "LN-001"));
    }

    // =========================================================================
    // ANM-005: Credit score parsing and range validation
    // =========================================================================

    @Test
    void validateCreditScore_validScore() {
        assertEquals(745, validator.validateCreditScore("745", "REC-1"));
    }

    @Test
    void validateCreditScore_tooLow() {
        assertNull(validator.validateCreditScore("100", "REC-1"));
    }

    @Test
    void validateCreditScore_tooHigh() {
        assertNull(validator.validateCreditScore("900", "REC-1"));
    }

    @Test
    void validateCreditScore_nonNumeric() {
        assertNull(validator.validateCreditScore("N/A", "REC-1"));
    }

    @Test
    void validateCreditScore_null() {
        assertNull(validator.validateCreditScore(null, "REC-1"));
    }

    @Test
    void validateCreditScore_boundaryMin() {
        assertEquals(300, validator.validateCreditScore("300", "REC-1"));
    }

    @Test
    void validateCreditScore_boundaryMax() {
        assertEquals(850, validator.validateCreditScore("850", "REC-1"));
    }

    // =========================================================================
    // ANM-006: Status code validation
    // =========================================================================

    @Test
    void validateLoanStatus_validACT() {
        assertEquals("ACT", validator.validateLoanStatus("ACT", "REC-1"));
    }

    @Test
    void validateLoanStatus_validDFT() {
        assertEquals("DFT", validator.validateLoanStatus("DFT", "REC-1"));
    }

    @Test
    void validateLoanStatus_unknownCodePassesThrough() {
        // Unknown codes are returned (with a log warning) — not rejected
        assertEquals("XYZ", validator.validateLoanStatus("XYZ", "REC-1"));
    }

    @Test
    void validateLoanStatus_null() {
        assertNull(validator.validateLoanStatus(null, "REC-1"));
    }

    @Test
    void validatePaymentStatus_valid() {
        assertEquals("PST", validator.validatePaymentStatus("PST", "REC-1"));
    }

    @Test
    void validatePaymentType_valid() {
        assertEquals("REG", validator.validatePaymentType("REG", "REC-1"));
    }

    @Test
    void validatePropertyType_valid() {
        assertEquals("SFR", validator.validatePropertyType("SFR", "REC-1"));
    }

    @Test
    void validateBorrowerStatus_valid() {
        assertEquals("ACT", validator.validateBorrowerStatus("ACT", "REC-1"));
    }

    // =========================================================================
    // ANM-010: Payment reconciliation
    // =========================================================================

    @Test
    void validatePaymentReconciliation_balanced() {
        assertTrue(validator.validatePaymentReconciliation("PMT-1",
                new BigDecimal("1000.00"),
                new BigDecimal("600.00"),
                new BigDecimal("300.00"),
                new BigDecimal("100.00"),
                BigDecimal.ZERO));
    }

    @Test
    void validatePaymentReconciliation_mismatch() {
        // Total=1487.02 but components sum to 1887.02 (off by 400)
        assertFalse(validator.validatePaymentReconciliation("PMT-2025120001",
                new BigDecimal("1487.02"),
                new BigDecimal("456.78"),
                new BigDecimal("1074.69"),
                new BigDecimal("355.55"),
                BigDecimal.ZERO));
    }

    @Test
    void validatePaymentReconciliation_withinTolerance() {
        // Off by $0.01 — within tolerance
        assertTrue(validator.validatePaymentReconciliation("PMT-1",
                new BigDecimal("1000.00"),
                new BigDecimal("600.00"),
                new BigDecimal("300.00"),
                new BigDecimal("100.01"),
                BigDecimal.ZERO));
    }

    @Test
    void validatePaymentReconciliation_nullTotal() {
        assertFalse(validator.validatePaymentReconciliation("PMT-1",
                null,
                new BigDecimal("600.00"),
                new BigDecimal("300.00"),
                BigDecimal.ZERO,
                BigDecimal.ZERO));
    }

    // =========================================================================
    // ANM-008: Delinquency days validation
    // =========================================================================

    @Test
    void validateDelinquencyDays_valid() {
        assertEquals(15, validator.validateDelinquencyDays("15", "REC-1"));
    }

    @Test
    void validateDelinquencyDays_zero() {
        assertEquals(0, validator.validateDelinquencyDays("0", "REC-1"));
    }

    @Test
    void validateDelinquencyDays_negative() {
        assertEquals(0, validator.validateDelinquencyDays("-5", "REC-1"));
    }

    @Test
    void validateDelinquencyDays_tooHigh() {
        assertEquals(0, validator.validateDelinquencyDays("9999", "REC-1"));
    }

    @Test
    void validateDelinquencyDays_null() {
        assertEquals(0, validator.validateDelinquencyDays(null, "REC-1"));
    }

    // =========================================================================
    // ANM-009: LTV percent validation
    // =========================================================================

    @Test
    void validateLtvPercent_valid() {
        assertEquals(new BigDecimal("82.5"), validator.validateLtvPercent("82.5", "REC-1"));
    }

    @Test
    void validateLtvPercent_overHundred() {
        // Should return the value but log a warning
        assertEquals(new BigDecimal("105.0"), validator.validateLtvPercent("105.0", "REC-1"));
    }

    @Test
    void validateLtvPercent_null() {
        assertNull(validator.validateLtvPercent(null, "REC-1"));
    }

    // =========================================================================
    // ANM-012: Interest rate validation
    // =========================================================================

    @Test
    void validateInterestRate_valid() {
        assertEquals(new BigDecimal("4.750"), validator.validateInterestRate("4.750", "REC-1"));
    }

    @Test
    void validateInterestRate_null() {
        assertNull(validator.validateInterestRate(null, "REC-1"));
    }

    @Test
    void validateInterestRate_nonNumeric() {
        assertNull(validator.validateInterestRate("N/A", "REC-1"));
    }

    // =========================================================================
    // ANM-007: Denormalized borrower name drift
    // =========================================================================

    @Test
    void validateDenormalizedName_matching() {
        // Should not throw — names match
        validator.validateDenormalizedName("LN-001", "James", "Mitchell", "James", "Mitchell");
    }

    @Test
    void validateDenormalizedName_mismatch() {
        // Should log a warning but not throw
        validator.validateDenormalizedName("LN-001", "Jim", "Mitchell", "James", "Mitchell");
    }

    // =========================================================================
    // ANM-001: Required field validation
    // =========================================================================

    @Test
    void validateRequired_present() {
        assertEquals("test@email.com", validator.validateRequired("test@email.com", "email", "REC-1"));
    }

    @Test
    void validateRequired_null() {
        assertNull(validator.validateRequired(null, "email", "REC-1"));
    }

    @Test
    void validateRequired_blank() {
        assertNull(validator.validateRequired("  ", "email", "REC-1"));
    }

    // =========================================================================
    // General parsing: integers and decimals
    // =========================================================================

    @Test
    void parseInteger_valid() {
        assertEquals(360, validator.parseInteger("360", "testField", "REC-1"));
    }

    @Test
    void parseInteger_null() {
        assertNull(validator.parseInteger(null, "testField", "REC-1"));
    }

    @Test
    void parseInteger_nonNumeric() {
        assertNull(validator.parseInteger("abc", "testField", "REC-1"));
    }

    @Test
    void parseDecimal_valid() {
        assertEquals(new BigDecimal("4.750"), validator.parseDecimal("4.750", "testField", "REC-1"));
    }

    @Test
    void parseDecimal_withWhitespace() {
        assertEquals(new BigDecimal("4.750"), validator.parseDecimal("  4.750  ", "testField", "REC-1"));
    }

    @Test
    void parseDecimal_null() {
        assertNull(validator.parseDecimal(null, "testField", "REC-1"));
    }
}
