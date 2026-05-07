package com.workshop.loanservice.validation;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;
    private List<DataQualityWarning> warnings;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
        warnings = new ArrayList<>();
    }

    // =========================================================================
    // ANO-002: Numeric string parsing with error handling
    // =========================================================================

    @Test
    void parseAmount_validAmountWithCommas_returnsBigDecimal() {
        BigDecimal result = validator.parseAmount("285,000", "LN_ORIG_AMT", "LN-001", warnings);
        assertEquals(new BigDecimal("285000"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_validAmountWithDecimal_returnsBigDecimal() {
        BigDecimal result = validator.parseAmount("1,487.02", "LN_PMT_AMT", "LN-001", warnings);
        assertEquals(new BigDecimal("1487.02"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_nullValue_returnsZero() {
        BigDecimal result = validator.parseAmount(null, "LN_ORIG_AMT", "LN-001", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_blankValue_returnsZero() {
        BigDecimal result = validator.parseAmount("  ", "LN_ORIG_AMT", "LN-001", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_malformedValue_returnsZeroAndWarns() {
        BigDecimal result = validator.parseAmount("N/A", "BORR_ANN_INCM", "B-10001", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertEquals(1, warnings.size());
        assertEquals("ANO-002", warnings.get(0).getAnomalyId());
        assertEquals("Critical", warnings.get(0).getSeverity());
        assertTrue(warnings.get(0).getMessage().contains("Malformed numeric value"));
    }

    @Test
    void parseAmount_dollarSign_strippedAndParsed() {
        BigDecimal result = validator.parseAmount("$285,000", "LN_ORIG_AMT", "LN-001", warnings);
        assertEquals(new BigDecimal("285000"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_textWithNumbers_returnsZeroAndWarns() {
        BigDecimal result = validator.parseAmount("UNKNOWN", "BORR_ANN_INCM", "B-10001", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertEquals(1, warnings.size());
    }

    @Test
    void parseDecimal_validRate_returnsBigDecimal() {
        BigDecimal result = validator.parseDecimal("4.750", "LN_INT_RT", "LN-001", warnings);
        assertEquals(new BigDecimal("4.750"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseDecimal_percentSign_strippedAndParsed() {
        BigDecimal result = validator.parseDecimal("4.750%", "LN_INT_RT", "LN-001", warnings);
        assertEquals(new BigDecimal("4.750"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseDecimal_malformedValue_returnsZeroAndWarns() {
        BigDecimal result = validator.parseDecimal("VARIABLE", "LN_INT_RT", "LN-001", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertEquals(1, warnings.size());
        assertEquals("ANO-002", warnings.get(0).getAnomalyId());
    }

    @Test
    void parseInteger_validValue_returnsInteger() {
        Integer result = validator.parseInteger("745", "BORR_CRDT_SCR", "B-10001", warnings);
        assertEquals(745, result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseInteger_nullValue_returnsNull() {
        Integer result = validator.parseInteger(null, "BORR_CRDT_SCR", "B-10001", warnings);
        assertNull(result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseInteger_malformedValue_returnsNullAndWarns() {
        Integer result = validator.parseInteger("PENDING", "BORR_CRDT_SCR", "B-10001", warnings);
        assertNull(result);
        assertEquals(1, warnings.size());
        assertEquals("ANO-002", warnings.get(0).getAnomalyId());
        assertTrue(warnings.get(0).getMessage().contains("Malformed integer"));
    }

    // =========================================================================
    // ANO-008: Date string parsing
    // =========================================================================

    @Test
    void parseDate_validDate_returnsLocalDate() {
        LocalDate result = validator.parseDate("03/15/1978", "BORR_DOB_DT", "B-10001", warnings);
        assertEquals(LocalDate.of(1978, 3, 15), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseDate_nullDate_returnsNull() {
        LocalDate result = validator.parseDate(null, "BORR_DOB_DT", "B-10001", warnings);
        assertNull(result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseDate_invalidDate_returnsNullAndWarns() {
        LocalDate result = validator.parseDate("99/99/9999", "BORR_DOB_DT", "B-10001", warnings);
        assertNull(result);
        assertEquals(1, warnings.size());
        assertEquals("ANO-008", warnings.get(0).getAnomalyId());
        assertTrue(warnings.get(0).getMessage().contains("Invalid date format"));
    }

    @Test
    void parseDate_wrongFormat_returnsNullAndWarns() {
        LocalDate result = validator.parseDate("2020-03-15", "BORR_DOB_DT", "B-10001", warnings);
        assertNull(result);
        assertEquals(1, warnings.size());
        assertEquals("ANO-008", warnings.get(0).getAnomalyId());
    }

    @Test
    void parseDate_garbageDate_returnsNullAndWarns() {
        LocalDate result = validator.parseDate("13/15/2025", "BORR_DOB_DT", "B-10001", warnings);
        assertNull(result);
        assertEquals(1, warnings.size());
    }

    // =========================================================================
    // ANO-001: Payment component sum mismatch
    // =========================================================================

    @Test
    void validatePaymentComponentSum_matching_noWarning() {
        validator.validatePaymentComponentSum("PMT-001",
                new BigDecimal("2924.18"),
                new BigDecimal("1842.56"),
                new BigDecimal("815.50"),
                new BigDecimal("266.12"),
                BigDecimal.ZERO,
                warnings);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validatePaymentComponentSum_mismatch_warnsWithDifference() {
        validator.validatePaymentComponentSum("PMT-2025120001",
                new BigDecimal("1487.02"),
                new BigDecimal("456.78"),
                new BigDecimal("1074.69"),
                new BigDecimal("355.55"),
                BigDecimal.ZERO,
                warnings);
        assertEquals(1, warnings.size());
        assertEquals("ANO-001", warnings.get(0).getAnomalyId());
        assertEquals("Critical", warnings.get(0).getSeverity());
        assertTrue(warnings.get(0).getMessage().contains("component sum mismatch"));
    }

    @Test
    void validatePaymentComponentSum_lateFeeNotIncluded_warnsWithDifference() {
        validator.validatePaymentComponentSum("PMT-2025110003",
                new BigDecimal("1077.05"),
                new BigDecimal("295.82"),
                new BigDecimal("781.23"),
                BigDecimal.ZERO,
                new BigDecimal("47.50"),
                warnings);
        assertEquals(1, warnings.size());
        assertEquals("ANO-001", warnings.get(0).getAnomalyId());
    }

    @Test
    void validatePaymentComponentSum_withinTolerance_noWarning() {
        validator.validatePaymentComponentSum("PMT-001",
                new BigDecimal("100.00"),
                new BigDecimal("50.00"),
                new BigDecimal("49.99"),
                BigDecimal.ZERO,
                BigDecimal.ZERO,
                warnings);
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // ANO-004: Delinquency vs status inconsistency
    // =========================================================================

    @Test
    void validateDelinquencyStatus_delinquentButActive_warns() {
        validator.validateDelinquencyStatus("LN-2018-00089", "15", "ACT", warnings);
        assertEquals(1, warnings.size());
        assertEquals("ANO-004", warnings.get(0).getAnomalyId());
        assertEquals("High", warnings.get(0).getSeverity());
        assertTrue(warnings.get(0).getMessage().contains("15 days delinquent"));
    }

    @Test
    void validateDelinquencyStatus_zeroDaysActive_noWarning() {
        validator.validateDelinquencyStatus("LN-001", "0", "ACT", warnings);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateDelinquencyStatus_delinquentAndDefault_noWarning() {
        validator.validateDelinquencyStatus("LN-001", "90", "DFT", warnings);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateDelinquencyStatus_nullDelinquency_noWarning() {
        validator.validateDelinquencyStatus("LN-001", null, "ACT", warnings);
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // ANO-005: Denormalized borrower name drift
    // =========================================================================

    @Test
    void validateBorrowerNameConsistency_matching_noWarning() {
        validator.validateBorrowerNameConsistency("LN-001",
                "James", "Mitchell", "James", "Mitchell", warnings);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateBorrowerNameConsistency_mismatch_warns() {
        validator.validateBorrowerNameConsistency("LN-001",
                "Sarah", "Chen", "Sarah", "Chen-Smith", warnings);
        assertEquals(1, warnings.size());
        assertEquals("ANO-005", warnings.get(0).getAnomalyId());
        assertEquals("High", warnings.get(0).getSeverity());
        assertTrue(warnings.get(0).getMessage().contains("denormalized borrower name mismatch"));
    }

    @Test
    void validateBorrowerNameConsistency_caseInsensitive_noWarning() {
        validator.validateBorrowerNameConsistency("LN-001",
                "james", "MITCHELL", "James", "Mitchell", warnings);
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // ANO-006: Late fee inconsistency
    // =========================================================================

    @Test
    void validateLateFeeConsistency_lateWithNoFee_warns() {
        validator.validateLateFeeConsistency("PMT-001",
                "12/01/2025", "12/20/2025", BigDecimal.ZERO, 15, warnings);
        assertEquals(1, warnings.size());
        assertEquals("ANO-006", warnings.get(0).getAnomalyId());
        assertTrue(warnings.get(0).getMessage().contains("days late but has no late fee"));
    }

    @Test
    void validateLateFeeConsistency_lateWithFee_noWarning() {
        validator.validateLateFeeConsistency("PMT-001",
                "11/01/2025", "11/18/2025", new BigDecimal("47.50"), 15, warnings);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLateFeeConsistency_withinGracePeriod_noWarning() {
        validator.validateLateFeeConsistency("PMT-001",
                "12/01/2025", "12/05/2025", BigDecimal.ZERO, 15, warnings);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLateFeeConsistency_onTime_noWarning() {
        validator.validateLateFeeConsistency("PMT-001",
                "12/01/2025", "11/30/2025", BigDecimal.ZERO, 15, warnings);
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // ANO-007: Stale LTV percentages
    // =========================================================================

    @Test
    void validateLtvAccuracy_staleLtv_warns() {
        validator.validateLtvAccuracy("LN-2019-00142",
                new BigDecimal("271432.56"),
                new BigDecimal("345000"),
                new BigDecimal("82.5"),
                warnings);
        assertEquals(1, warnings.size());
        assertEquals("ANO-007", warnings.get(0).getAnomalyId());
        assertTrue(warnings.get(0).getMessage().contains("stale LTV"));
    }

    @Test
    void validateLtvAccuracy_accurateLtv_noWarning() {
        // 271432.56 / 345000 = 78.7%
        validator.validateLtvAccuracy("LN-001",
                new BigDecimal("271432.56"),
                new BigDecimal("345000"),
                new BigDecimal("78.7"),
                warnings);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLtvAccuracy_zeroAppraisedValue_noWarning() {
        validator.validateLtvAccuracy("LN-001",
                new BigDecimal("100000"),
                BigDecimal.ZERO,
                new BigDecimal("80.0"),
                warnings);
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // ANO-009: NULL values in required fields
    // =========================================================================

    @Test
    void validateRequiredField_present_returnsValue() {
        String result = validator.validateRequiredField("James", "BORR_FST_NM", "B-10001", "Unknown", warnings);
        assertEquals("James", result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateRequiredField_null_returnsDefaultAndWarns() {
        String result = validator.validateRequiredField(null, "BORR_FST_NM", "B-10001", "Unknown", warnings);
        assertEquals("Unknown", result);
        assertEquals(1, warnings.size());
        assertEquals("ANO-009", warnings.get(0).getAnomalyId());
        assertTrue(warnings.get(0).getMessage().contains("Required field is null/blank"));
    }

    @Test
    void validateRequiredField_blank_returnsDefaultAndWarns() {
        String result = validator.validateRequiredField("  ", "BORR_FST_NM", "B-10001", "Unknown", warnings);
        assertEquals("Unknown", result);
        assertEquals(1, warnings.size());
    }
}
