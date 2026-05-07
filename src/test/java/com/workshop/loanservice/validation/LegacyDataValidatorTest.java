package com.workshop.loanservice.validation;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANM-003: Numeric string parsing with error handling
    // =========================================================================

    @Test
    void parseAmount_validAmountWithCommas() {
        assertEquals(new BigDecimal("285000"), validator.parseAmount("285,000", "AMT", "REC-1"));
    }

    @Test
    void parseAmount_validAmountWithDecimal() {
        assertEquals(new BigDecimal("271432.56"), validator.parseAmount("271,432.56", "AMT", "REC-1"));
    }

    @Test
    void parseAmount_nullReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseAmount(null, "AMT", "REC-1"));
    }

    @Test
    void parseAmount_blankReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseAmount("  ", "AMT", "REC-1"));
    }

    @Test
    void parseAmount_currencySymbolStripped() {
        assertEquals(new BigDecimal("285000"), validator.parseAmount("$285,000", "AMT", "REC-1"));
    }

    @Test
    void parseAmount_malformedReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseAmount("N/A", "AMT", "REC-1"));
    }

    @Test
    void parseAmount_doubleCommaStillParses() {
        assertEquals(new BigDecimal("285000"), validator.parseAmount("285,,000", "AMT", "REC-1"));
    }

    @Test
    void parseAmount_textWithDigitsReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseAmount("USD285000", "AMT", "REC-1"));
    }

    @Test
    void parseDecimal_validDecimal() {
        assertEquals(new BigDecimal("4.750"), validator.parseDecimal("4.750", "RT", "REC-1"));
    }

    @Test
    void parseDecimal_nullReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseDecimal(null, "RT", "REC-1"));
    }

    @Test
    void parseDecimal_malformedReturnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseDecimal("PENDING", "RT", "REC-1"));
    }

    @Test
    void parseInteger_validInteger() {
        assertEquals(745, validator.parseInteger("745", "SCR", "REC-1"));
    }

    @Test
    void parseInteger_nullReturnsNull() {
        assertNull(validator.parseInteger(null, "SCR", "REC-1"));
    }

    @Test
    void parseInteger_blankReturnsNull() {
        assertNull(validator.parseInteger("  ", "SCR", "REC-1"));
    }

    @Test
    void parseInteger_malformedReturnsNull() {
        assertNull(validator.parseInteger("N/A", "SCR", "REC-1"));
    }

    @Test
    void parseInteger_withWhitespace() {
        assertEquals(360, validator.parseInteger(" 360 ", "TERM", "REC-1"));
    }

    // =========================================================================
    // ANM-009: Date string validation
    // =========================================================================

    @Test
    void parseLegacyDate_validDate() {
        assertEquals(LocalDate.of(2019, 2, 15), validator.parseLegacyDate("02/15/2019", "DT", "REC-1"));
    }

    @Test
    void parseLegacyDate_nullReturnsNull() {
        assertNull(validator.parseLegacyDate(null, "DT", "REC-1"));
    }

    @Test
    void parseLegacyDate_isoFormatReturnsNull() {
        assertNull(validator.parseLegacyDate("2025-01-15", "DT", "REC-1"));
    }

    @Test
    void parseLegacyDate_placeholderReturnsNull() {
        assertNull(validator.parseLegacyDate("00/00/0000", "DT", "REC-1"));
    }

    @Test
    void parseLegacyDate_textReturnsNull() {
        assertNull(validator.parseLegacyDate("TBD", "DT", "REC-1"));
    }

    @Test
    void formatLegacyDate_validDateReturnsIso() {
        assertEquals("2019-02-15", validator.formatLegacyDate("02/15/2019", "DT", "REC-1"));
    }

    @Test
    void formatLegacyDate_invalidDateReturnsOriginal() {
        assertEquals("TBD", validator.formatLegacyDate("TBD", "DT", "REC-1"));
    }

    // =========================================================================
    // ANM-001: Payment component sum mismatch
    // =========================================================================

    @Test
    void validatePaymentComponents_matchingComponentsReturnsTrue() {
        assertTrue(validator.validatePaymentComponents("PMT-1",
                new BigDecimal("2924.18"),
                new BigDecimal("1842.56"),
                new BigDecimal("815.50"),
                new BigDecimal("266.12"),
                new BigDecimal("0.00")));
    }

    @Test
    void validatePaymentComponents_mismatchReturnsFalse() {
        assertFalse(validator.validatePaymentComponents("PMT-2025120001",
                new BigDecimal("1487.02"),
                new BigDecimal("456.78"),
                new BigDecimal("1074.69"),
                new BigDecimal("355.55"),
                new BigDecimal("0.00")));
    }

    @Test
    void validatePaymentComponents_withinToleranceReturnsTrue() {
        assertTrue(validator.validatePaymentComponents("PMT-1",
                new BigDecimal("100.01"),
                new BigDecimal("50.00"),
                new BigDecimal("50.00"),
                BigDecimal.ZERO,
                BigDecimal.ZERO));
    }

    // =========================================================================
    // ANM-004 / ANM-011: Status code validation
    // =========================================================================

    @Test
    void validateLoanStatus_validStatusReturnsTrue() {
        assertTrue(validator.validateLoanStatus("ACT", "0", "LN-1"));
    }

    @Test
    void validateLoanStatus_invalidStatusReturnsFalse() {
        assertFalse(validator.validateLoanStatus("XYZ", "0", "LN-1"));
    }

    @Test
    void validateLoanStatus_delinquentWithActiveStatus() {
        assertTrue(validator.validateLoanStatus("ACT", "15", "LN-2018-00089"));
    }

    @Test
    void validatePaymentType_validTypeReturnsTrue() {
        assertTrue(validator.validatePaymentType("REG", "PMT-1"));
    }

    @Test
    void validatePaymentType_invalidTypeReturnsFalse() {
        assertFalse(validator.validatePaymentType("BAD", "PMT-1"));
    }

    @Test
    void validatePaymentStatus_validStatusReturnsTrue() {
        assertTrue(validator.validatePaymentStatus("PST", "PMT-1"));
    }

    @Test
    void validatePaymentStatus_invalidStatusReturnsFalse() {
        assertFalse(validator.validatePaymentStatus("XXX", "PMT-1"));
    }

    @Test
    void validatePropertyType_validTypeReturnsTrue() {
        assertTrue(validator.validatePropertyType("SFR", "LN-1"));
    }

    @Test
    void validatePropertyType_invalidTypeReturnsFalse() {
        assertFalse(validator.validatePropertyType("ZZZ", "LN-1"));
    }

    @Test
    void validatePropertyType_nullReturnsTrue() {
        assertTrue(validator.validatePropertyType(null, "LN-1"));
    }

    // =========================================================================
    // ANM-005 / ANM-010: Null-safe name and address building
    // =========================================================================

    @Test
    void buildSafeName_bothPresent() {
        assertEquals("James Mitchell", validator.buildSafeName("James", "Mitchell"));
    }

    @Test
    void buildSafeName_nullFirstName() {
        assertEquals("Unknown Mitchell", validator.buildSafeName(null, "Mitchell"));
    }

    @Test
    void buildSafeName_nullLastName() {
        assertEquals("James Unknown", validator.buildSafeName("James", null));
    }

    @Test
    void buildSafeName_bothNull() {
        assertEquals("Unknown Unknown", validator.buildSafeName(null, null));
    }

    @Test
    void buildSafeFullName_withMiddleInitial() {
        assertEquals("James R. Mitchell", validator.buildSafeFullName("James", "R", "Mitchell"));
    }

    @Test
    void buildSafeFullName_noMiddleInitial() {
        assertEquals("Robert Williams", validator.buildSafeFullName("Robert", null, "Williams"));
    }

    @Test
    void buildSafeAddress_allPresent() {
        assertEquals("742 Elm Street, Springfield, IL 62701",
                validator.buildSafeAddress("742 Elm Street", "Springfield", "IL", "62701"));
    }

    @Test
    void buildSafeAddress_nullAddress() {
        assertEquals("Springfield, IL 62701",
                validator.buildSafeAddress(null, "Springfield", "IL", "62701"));
    }

    @Test
    void buildSafeAddress_allNull() {
        assertEquals("Address unavailable",
                validator.buildSafeAddress(null, null, null, null));
    }

    @Test
    void buildSafeAddress_partialFields() {
        assertEquals("Springfield, IL",
                validator.buildSafeAddress(null, "Springfield", "IL", null));
    }

    // =========================================================================
    // ANM-002: SSN last-4 vs phone suffix detection
    // =========================================================================

    @Test
    void validateSsnNotPhoneSuffix_matchReturnsFalse() {
        assertFalse(validator.validateSsnNotPhoneSuffix("0142", "217-555-0142", "LN-2019-00142"));
    }

    @Test
    void validateSsnNotPhoneSuffix_noMatchReturnsTrue() {
        assertTrue(validator.validateSsnNotPhoneSuffix("9876", "217-555-0142", "LN-2019-00142"));
    }

    @Test
    void validateSsnNotPhoneSuffix_nullSsnReturnsTrue() {
        assertTrue(validator.validateSsnNotPhoneSuffix(null, "217-555-0142", "LN-2019-00142"));
    }

    @Test
    void validateSsnNotPhoneSuffix_nullPhoneReturnsTrue() {
        assertTrue(validator.validateSsnNotPhoneSuffix("0142", null, "LN-2019-00142"));
    }

    // =========================================================================
    // ANM-012: LTV calculation
    // =========================================================================

    @Test
    void calculateLtv_normal() {
        BigDecimal ltv = validator.calculateLtv(new BigDecimal("285000"), new BigDecimal("345000"));
        assertEquals(new BigDecimal("82.61"), ltv);
    }

    @Test
    void calculateLtv_zeroAppraisedValue() {
        assertEquals(BigDecimal.ZERO, validator.calculateLtv(new BigDecimal("285000"), BigDecimal.ZERO));
    }

    @Test
    void calculateLtv_nullAppraisedValue() {
        assertEquals(BigDecimal.ZERO, validator.calculateLtv(new BigDecimal("285000"), null));
    }
}
