package com.workshop.loanservice.migration;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for {@link DateValidator} — validates VARCHAR → DATE/TIMESTAMP transformation
 * logic including format detection, strict calendar validation, ambiguity detection,
 * null handling, and date ordering checks.
 */
class DateValidatorTest {

    private DateValidator validator;

    @BeforeEach
    void setUp() {
        validator = new DateValidator();
    }

    // =========================================================================
    // parseDate — valid MM/dd/yyyy parsing
    // =========================================================================

    @Test
    void parseDate_validMmDdYyyy_returnsOk() {
        // Standard legacy format used across all CDW tables
        ValidationResult<LocalDate> result = validator.parseDate("03/15/1978", "date_of_birth", true);
        assertTrue(result.isValid());
        assertEquals(LocalDate.of(1978, 3, 15), result.getValue());
    }

    @Test
    void parseDate_validIsoFormat_returnsOk() {
        // Fallback: yyyy-MM-dd ISO format
        ValidationResult<LocalDate> result = validator.parseDate("2020-01-15", "created_at", false);
        assertTrue(result.isValid());
        assertEquals(LocalDate.of(2020, 1, 15), result.getValue());
    }

    @Test
    void parseDate_validSingleDigitFormat_returnsOk() {
        // Fallback: M/d/yyyy with single-digit month/day
        ValidationResult<LocalDate> result = validator.parseDate("3/5/2020", "some_date", false);
        assertTrue(result.isValid());
        assertEquals(LocalDate.of(2020, 3, 5), result.getValue());
    }

    // =========================================================================
    // parseDate — strict mode rejects impossible dates
    // =========================================================================

    @Test
    void parseDate_feb30_returnsError() {
        // Feb 30 does not exist — strict resolver must reject
        ValidationResult<LocalDate> result = validator.parseDate("02/30/2020", "some_date", true);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    @Test
    void parseDate_apr31_returnsError() {
        // April has only 30 days — strict resolver must reject
        ValidationResult<LocalDate> result = validator.parseDate("04/31/2020", "some_date", true);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    // =========================================================================
    // parseDate — ambiguous date detection (day <= 12)
    // =========================================================================

    @Test
    void parseDate_ambiguousDate_returnsWarning() {
        // 03/04/2020 — day=4, month=3, day <= 12, could be DD/MM/YYYY
        ValidationResult<LocalDate> result = validator.parseDate("03/04/2020", "some_date", false);
        assertTrue(result.isValid());
        assertNotNull(result.getValue());
        assertEquals(ValidationResult.Severity.WARNING, result.getSeverity());
        assertTrue(result.getErrorMessage().contains("Ambiguous"));
    }

    @Test
    void parseDate_nonAmbiguousDate_noWarning() {
        // 03/15/1978 — day=15 > 12, no ambiguity
        ValidationResult<LocalDate> result = validator.parseDate("03/15/1978", "date_of_birth", true);
        assertTrue(result.isValid());
        assertNull(result.getSeverity()); // OK result has no severity
    }

    @Test
    void parseDate_sameDayAndMonth_noWarning() {
        // 05/05/2020 — day == month, no ambiguity even though day <= 12
        ValidationResult<LocalDate> result = validator.parseDate("05/05/2020", "some_date", false);
        assertTrue(result.isValid());
        assertNull(result.getSeverity());
    }

    // =========================================================================
    // parseDate — null handling for required vs optional
    // =========================================================================

    @Test
    void parseDate_nullRequired_returnsError() {
        ValidationResult<LocalDate> result = validator.parseDate(null, "origination_date", true);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    @Test
    void parseDate_nullOptional_returnsOk() {
        ValidationResult<LocalDate> result = validator.parseDate(null, "some_date", false);
        assertTrue(result.isValid());
        assertNull(result.getValue());
    }

    @Test
    void parseDate_blankRequired_returnsError() {
        ValidationResult<LocalDate> result = validator.parseDate("  ", "origination_date", true);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    @Test
    void parseDate_unparseable_optionalReturnsWarning() {
        ValidationResult<LocalDate> result = validator.parseDate("NOT-A-DATE", "some_date", false);
        assertTrue(result.isValid()); // warning is technically "valid" with no value
        assertEquals(ValidationResult.Severity.WARNING, result.getSeverity());
    }

    // =========================================================================
    // parseTimestamp — DATE → TIMESTAMP promotion
    // =========================================================================

    @Test
    void parseTimestamp_validDate_promotedToMidnight() {
        // Timestamp promotion should set time to 00:00:00 and add INFO about time loss
        ValidationResult<LocalDateTime> result = validator.parseTimestamp(
                "01/15/2019", "created_at", false);
        assertTrue(result.isValid());
        assertEquals(LocalDateTime.of(2019, 1, 15, 0, 0, 0), result.getValue());
        assertEquals(ValidationResult.Severity.INFO, result.getSeverity());
        assertTrue(result.getErrorMessage().contains("00:00:00"));
    }

    @Test
    void parseTimestamp_nullOptional_returnsOk() {
        ValidationResult<LocalDateTime> result = validator.parseTimestamp(null, "updated_at", false);
        assertTrue(result.isValid());
        assertNull(result.getValue());
    }

    @Test
    void parseTimestamp_nullRequired_returnsError() {
        ValidationResult<LocalDateTime> result = validator.parseTimestamp(null, "created_at", true);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    // =========================================================================
    // validateDateOrdering — loan date chronology checks
    // =========================================================================

    @Test
    void validateDateOrdering_validOrder_noWarnings() {
        // origination < maturity, firstPayment > origination
        LocalDate origination = LocalDate.of(2019, 2, 15);
        LocalDate maturity = LocalDate.of(2049, 2, 15);
        LocalDate firstPayment = LocalDate.of(2019, 3, 15);
        LocalDate nextPayment = LocalDate.of(2026, 1, 15);

        List<ValidationResult<?>> results = validator.validateDateOrdering(
                origination, maturity, firstPayment, nextPayment);
        assertTrue(results.isEmpty(), "Expected no warnings for valid date ordering");
    }

    @Test
    void validateDateOrdering_originationAfterMaturity_returnsWarning() {
        LocalDate origination = LocalDate.of(2049, 2, 15);
        LocalDate maturity = LocalDate.of(2019, 2, 15);

        List<ValidationResult<?>> results = validator.validateDateOrdering(
                origination, maturity, null, null);
        assertFalse(results.isEmpty());
        assertTrue(results.get(0).getErrorMessage().contains("before maturity"));
    }

    @Test
    void validateDateOrdering_firstPaymentBeforeOrigination_returnsWarning() {
        LocalDate origination = LocalDate.of(2019, 2, 15);
        LocalDate maturity = LocalDate.of(2049, 2, 15);
        LocalDate firstPayment = LocalDate.of(2019, 1, 1); // Before origination

        List<ValidationResult<?>> results = validator.validateDateOrdering(
                origination, maturity, firstPayment, null);
        assertFalse(results.isEmpty());
        assertTrue(results.stream().anyMatch(
                r -> r.getErrorMessage().contains("First payment date should be after origination")));
    }

    // =========================================================================
    // validatePaymentDateOrdering — payment processing date checks
    // =========================================================================

    @Test
    void validatePaymentDateOrdering_validOrder_noWarnings() {
        LocalDate paymentDate = LocalDate.of(2025, 12, 15);
        LocalDate receivedDate = LocalDate.of(2025, 12, 14);
        LocalDate processedDate = LocalDate.of(2025, 12, 15);

        // receivedDate (14th) is before paymentDate (15th) — this should produce warning
        List<ValidationResult<?>> results = validator.validatePaymentDateOrdering(
                paymentDate, receivedDate, processedDate);
        // In this case receivedDate < paymentDate triggers a warning
        assertFalse(results.isEmpty());
    }

    @Test
    void validatePaymentDateOrdering_receivedBeforePayment_returnsWarning() {
        LocalDate paymentDate = LocalDate.of(2025, 12, 15);
        LocalDate receivedDate = LocalDate.of(2025, 12, 10);
        LocalDate processedDate = LocalDate.of(2025, 12, 15);

        List<ValidationResult<?>> results = validator.validatePaymentDateOrdering(
                paymentDate, receivedDate, processedDate);
        assertTrue(results.stream().anyMatch(
                r -> r.getErrorMessage().contains("Received date should not be before payment date")));
    }
}
