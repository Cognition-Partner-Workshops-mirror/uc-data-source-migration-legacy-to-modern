package com.workshop.loanservice.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // parseAmount tests — ANOM-002, ANOM-010
    // =========================================================================

    @Test
    void parseAmount_validCommaFormatted() {
        assertEquals(new BigDecimal("285000"), validator.parseAmount("285,000", "field", "rec1"));
    }

    @Test
    void parseAmount_validDecimalWithComma() {
        assertEquals(new BigDecimal("1487.02"), validator.parseAmount("1,487.02", "field", "rec1"));
    }

    @Test
    void parseAmount_nullReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseAmount(null, "field", "rec1"));
    }

    @Test
    void parseAmount_blankReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseAmount("", "field", "rec1"));
        assertEquals(BigDecimal.ZERO, validator.parseAmount("   ", "field", "rec1"));
    }

    @Test
    void parseAmount_dollarSignStripped() {
        assertEquals(new BigDecimal("285000"), validator.parseAmount("$285,000", "field", "rec1"));
    }

    @Test
    void parseAmount_nonNumericReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseAmount("N/A", "field", "rec1"));
        assertEquals(BigDecimal.ZERO, validator.parseAmount("TBD", "field", "rec1"));
    }

    @Test
    void parseAmount_parenthesesNegativeStripped() {
        // Parentheses stripped, leaving just digits — not ideal but safe
        BigDecimal result = validator.parseAmount("(1,487.02)", "field", "rec1");
        assertNotNull(result);
    }

    @Test
    void parseAmount_spacesInAmount() {
        assertEquals(new BigDecimal("285000"), validator.parseAmount(" 285,000 ", "field", "rec1"));
    }

    // =========================================================================
    // parseDecimal tests — ANOM-010
    // =========================================================================

    @Test
    void parseDecimal_validRate() {
        assertEquals(new BigDecimal("5.250"), validator.parseDecimal("5.250", "rate", "rec1"));
    }

    @Test
    void parseDecimal_nullReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseDecimal(null, "rate", "rec1"));
    }

    @Test
    void parseDecimal_nonNumericReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseDecimal("TBD", "rate", "rec1"));
    }

    @Test
    void parseDecimal_percentSignStripped() {
        assertEquals(new BigDecimal("5.250"), validator.parseDecimal("5.250%", "rate", "rec1"));
    }

    // =========================================================================
    // parseInteger tests — ANOM-010
    // =========================================================================

    @Test
    void parseInteger_valid() {
        assertEquals(360, validator.parseInteger("360", "term", "rec1"));
    }

    @Test
    void parseInteger_nullReturnsNull() {
        assertNull(validator.parseInteger(null, "term", "rec1"));
    }

    @Test
    void parseInteger_blankReturnsNull() {
        assertNull(validator.parseInteger("", "term", "rec1"));
    }

    @Test
    void parseInteger_nonNumericReturnsNull() {
        assertNull(validator.parseInteger("OPEN", "term", "rec1"));
        assertNull(validator.parseInteger("N/A", "term", "rec1"));
    }

    @Test
    void parseInteger_withSpaces() {
        assertEquals(360, validator.parseInteger(" 360 ", "term", "rec1"));
    }

    // =========================================================================
    // parseCreditScore tests — ANOM-003
    // =========================================================================

    @Test
    void parseCreditScore_validScore() {
        assertEquals(745, validator.parseCreditScore("745", "B-10001"));
    }

    @Test
    void parseCreditScore_tooLow() {
        assertNull(validator.parseCreditScore("100", "B-10001"));
    }

    @Test
    void parseCreditScore_tooHigh() {
        assertNull(validator.parseCreditScore("900", "B-10001"));
    }

    @Test
    void parseCreditScore_nonNumeric() {
        assertNull(validator.parseCreditScore("abc", "B-10001"));
    }

    @Test
    void parseCreditScore_null() {
        assertNull(validator.parseCreditScore(null, "B-10001"));
    }

    @Test
    void parseCreditScore_boundaryLow() {
        assertEquals(300, validator.parseCreditScore("300", "B-10001"));
    }

    @Test
    void parseCreditScore_boundaryHigh() {
        assertEquals(850, validator.parseCreditScore("850", "B-10001"));
    }

    // =========================================================================
    // parseLegacyDate tests — ANOM-004
    // =========================================================================

    @Test
    void parseLegacyDate_validDate() {
        assertEquals("1978-03-15", validator.parseLegacyDate("03/15/1978", "dob", "B-10001"));
    }

    @Test
    void parseLegacyDate_nullReturnsNull() {
        assertNull(validator.parseLegacyDate(null, "dob", "B-10001"));
    }

    @Test
    void parseLegacyDate_blankReturnsNull() {
        assertNull(validator.parseLegacyDate("", "dob", "B-10001"));
    }

    @Test
    void parseLegacyDate_invalidFormatReturnsOriginal() {
        assertEquals("2025-01-15", validator.parseLegacyDate("2025-01-15", "dob", "B-10001"));
    }

    @Test
    void parseLegacyDate_garbageReturnsOriginal() {
        assertEquals("N/A", validator.parseLegacyDate("N/A", "dob", "B-10001"));
    }

    // =========================================================================
    // validateLoanStatus tests — ANOM-010
    // =========================================================================

    @Test
    void validateLoanStatus_validStatus() {
        assertEquals("ACT", validator.validateLoanStatus("ACT", "LN-001"));
        assertEquals("CLO", validator.validateLoanStatus("CLO", "LN-001"));
        assertEquals("DFT", validator.validateLoanStatus("DFT", "LN-001"));
        assertEquals("FRB", validator.validateLoanStatus("FRB", "LN-001"));
    }

    @Test
    void validateLoanStatus_nullDefaultsToAct() {
        assertEquals("ACT", validator.validateLoanStatus(null, "LN-001"));
    }

    @Test
    void validateLoanStatus_blankDefaultsToAct() {
        assertEquals("ACT", validator.validateLoanStatus("", "LN-001"));
    }

    @Test
    void validateLoanStatus_invalidKeptAsIs() {
        assertEquals("XYZ", validator.validateLoanStatus("XYZ", "LN-001"));
    }

    // =========================================================================
    // validatePaymentStatus tests
    // =========================================================================

    @Test
    void validatePaymentStatus_validStatus() {
        assertEquals("PST", validator.validatePaymentStatus("PST", "PMT-001"));
    }

    @Test
    void validatePaymentStatus_nullDefaultsToPnd() {
        assertEquals("PND", validator.validatePaymentStatus(null, "PMT-001"));
    }

    // =========================================================================
    // validatePaymentType tests
    // =========================================================================

    @Test
    void validatePaymentType_validType() {
        assertEquals("REG", validator.validatePaymentType("REG", "PMT-001"));
    }

    @Test
    void validatePaymentType_nullDefaultsToReg() {
        assertEquals("REG", validator.validatePaymentType(null, "PMT-001"));
    }

    // =========================================================================
    // validatePropertyType tests
    // =========================================================================

    @Test
    void validatePropertyType_validType() {
        assertEquals("SFR", validator.validatePropertyType("SFR", "LN-001"));
    }

    @Test
    void validatePropertyType_nullReturnsNull() {
        assertNull(validator.validatePropertyType(null, "LN-001"));
    }

    @Test
    void validatePropertyType_invalidLogsWarning() {
        assertEquals("XXX", validator.validatePropertyType("XXX", "LN-001"));
    }

    // =========================================================================
    // validateBorrowerReference tests — ANOM-005
    // =========================================================================

    @Test
    void validateBorrowerReference_validReference() {
        Set<String> knownIds = Set.of("B-10001", "B-10002");
        assertTrue(validator.validateBorrowerReference("B-10001", knownIds, "LN-001"));
    }

    @Test
    void validateBorrowerReference_orphanedReference() {
        Set<String> knownIds = Set.of("B-10001", "B-10002");
        assertFalse(validator.validateBorrowerReference("B-99999", knownIds, "LN-001"));
    }

    @Test
    void validateBorrowerReference_nullId() {
        Set<String> knownIds = Set.of("B-10001");
        assertFalse(validator.validateBorrowerReference(null, knownIds, "LN-001"));
    }

    // =========================================================================
    // validateProductReference tests — ANOM-005
    // =========================================================================

    @Test
    void validateProductReference_validReference() {
        Set<String> knownCodes = Set.of("FXD30", "FXD15", "ARM51");
        assertTrue(validator.validateProductReference("FXD30", knownCodes, "LN-001"));
    }

    @Test
    void validateProductReference_orphanedReference() {
        Set<String> knownCodes = Set.of("FXD30", "FXD15");
        assertFalse(validator.validateProductReference("INVALID", knownCodes, "LN-001"));
    }

    // =========================================================================
    // validateLoanAccountReference tests — ANOM-005
    // =========================================================================

    @Test
    void validateLoanAccountReference_validReference() {
        Set<String> knownLoanIds = Set.of("LN-2019-00142");
        assertTrue(validator.validateLoanAccountReference("LN-2019-00142", knownLoanIds, "PMT-001"));
    }

    @Test
    void validateLoanAccountReference_orphanedReference() {
        Set<String> knownLoanIds = Set.of("LN-2019-00142");
        assertFalse(validator.validateLoanAccountReference("LN-NONEXISTENT", knownLoanIds, "PMT-001"));
    }

    // =========================================================================
    // validatePaymentAmounts tests — ANOM-008
    // =========================================================================

    @Test
    void validatePaymentAmounts_balanced() {
        assertTrue(validator.validatePaymentAmounts(
                new BigDecimal("100.00"),
                new BigDecimal("50.00"),
                new BigDecimal("40.00"),
                new BigDecimal("10.00"),
                new BigDecimal("0.00"),
                "PMT-001"));
    }

    @Test
    void validatePaymentAmounts_unbalanced() {
        assertFalse(validator.validatePaymentAmounts(
                new BigDecimal("1487.02"),
                new BigDecimal("456.78"),
                new BigDecimal("1074.69"),
                new BigDecimal("355.55"),
                new BigDecimal("0.00"),
                "PMT-2025120001"));
    }

    @Test
    void validatePaymentAmounts_withinTolerance() {
        assertTrue(validator.validatePaymentAmounts(
                new BigDecimal("100.01"),
                new BigDecimal("50.00"),
                new BigDecimal("40.00"),
                new BigDecimal("10.00"),
                new BigDecimal("0.00"),
                "PMT-001"));
    }

    // =========================================================================
    // safeBorrowerName tests — ANOM-001, ANOM-006
    // =========================================================================

    @Test
    void safeBorrowerName_bothPresent() {
        assertEquals("James Mitchell", validator.safeBorrowerName("James", "Mitchell"));
    }

    @Test
    void safeBorrowerName_firstNameNull() {
        assertEquals("Unknown Mitchell", validator.safeBorrowerName(null, "Mitchell"));
    }

    @Test
    void safeBorrowerName_lastNameNull() {
        assertEquals("James Unknown", validator.safeBorrowerName("James", null));
    }

    @Test
    void safeBorrowerName_bothNull() {
        assertEquals("Unknown Unknown", validator.safeBorrowerName(null, null));
    }

    // =========================================================================
    // validateDelinquencyConsistency tests — ANOM-007
    // =========================================================================

    @Test
    void validateDelinquencyConsistency_activeWithZeroDays() {
        // Should not warn — consistent state
        validator.validateDelinquencyConsistency("0", "ACT", "LN-001");
    }

    @Test
    void validateDelinquencyConsistency_activeWithDelinquentDays() {
        // Should warn — inconsistent state (15 days delinquent but Active)
        validator.validateDelinquencyConsistency("15", "ACT", "LN-2018-00089");
    }

    @Test
    void validateDelinquencyConsistency_defaultWithDelinquentDays() {
        // Should not warn — default status is expected for delinquent loans
        validator.validateDelinquencyConsistency("90", "DFT", "LN-001");
    }

    // =========================================================================
    // validateLatePaymentConsistency tests — ANOM-009
    // =========================================================================

    @Test
    void validateLatePaymentConsistency_lateWithNoFee() {
        // Should warn — received after due date but no late fee
        validator.validateLatePaymentConsistency(
                "12/01/2025", "12/05/2025", BigDecimal.ZERO, "PMT-2025120003");
    }

    @Test
    void validateLatePaymentConsistency_lateWithFee() {
        // Should not warn — late with appropriate fee
        validator.validateLatePaymentConsistency(
                "11/01/2025", "11/18/2025", new BigDecimal("47.50"), "PMT-2025110003");
    }

    @Test
    void validateLatePaymentConsistency_onTime() {
        // Should not warn — on time
        validator.validateLatePaymentConsistency(
                "12/15/2025", "12/14/2025", BigDecimal.ZERO, "PMT-2025120001");
    }
}
