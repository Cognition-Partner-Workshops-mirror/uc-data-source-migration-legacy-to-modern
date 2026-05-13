package com.workshop.loanservice.migration;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.List;

/**
 * Validates and parses legacy VARCHAR date fields into proper Java temporal types.
 * <p>
 * Legacy CDW tables store dates as VARCHAR(10) in MM/DD/YYYY format.
 * The modern schema uses DATE and TIMESTAMP columns. This validator
 * handles format detection, strict parsing (rejects Feb 30, Apr 31, etc.),
 * and flags ambiguous day/month values where DD &le; 12.
 * </p>
 */
public class DateValidator {

    // Primary format used in legacy CDW tables — strict mode rejects invalid calendar dates
    private static final DateTimeFormatter MM_DD_YYYY =
            DateTimeFormatter.ofPattern("MM/dd/uuuu").withResolverStyle(ResolverStyle.STRICT);

    // Fallback: ISO date format (yyyy-MM-dd)
    private static final DateTimeFormatter YYYY_MM_DD =
            DateTimeFormatter.ofPattern("uuuu-MM-dd").withResolverStyle(ResolverStyle.STRICT);

    // Fallback: single-digit month/day variant (M/d/yyyy)
    private static final DateTimeFormatter M_D_YYYY =
            DateTimeFormatter.ofPattern("M/d/uuuu").withResolverStyle(ResolverStyle.STRICT);

    /**
     * Parse a legacy VARCHAR date string into LocalDate.
     * Tries MM/dd/yyyy first, then yyyy-MM-dd, then M/d/yyyy.
     * If the day component is &le; 12, adds a WARNING about DD/MM/YYYY ambiguity.
     *
     * @param raw        the raw string from the legacy table
     * @param columnName the source column name for error reporting
     * @param required   if true, null/blank/unparseable yields ERROR; otherwise WARNING
     * @return validation result containing the parsed LocalDate or error details
     */
    public ValidationResult<LocalDate> parseDate(String raw, String columnName, boolean required) {
        // Handle null/blank input
        if (raw == null || raw.isBlank()) {
            if (required) {
                return ValidationResult.error(columnName, raw,
                        "Required date field is null or blank");
            }
            return ValidationResult.ok(null);
        }

        String trimmed = raw.trim();
        LocalDate parsed = tryParse(trimmed);

        if (parsed == null) {
            if (required) {
                return ValidationResult.error(columnName, trimmed,
                        "Cannot parse date value — expected MM/dd/yyyy, yyyy-MM-dd, or M/d/yyyy");
            }
            return ValidationResult.warning(columnName, trimmed,
                    "Cannot parse optional date value — expected MM/dd/yyyy, yyyy-MM-dd, or M/d/yyyy");
        }

        // Check for DD/MM/YYYY ambiguity: if day <= 12, the value could be misinterpreted
        if (parsed.getDayOfMonth() <= 12 && parsed.getMonthValue() != parsed.getDayOfMonth()) {
            return ValidationResult.warningWithValue(parsed, columnName, trimmed,
                    "Ambiguous date — day (" + parsed.getDayOfMonth()
                            + ") <= 12, could be DD/MM/YYYY instead of MM/DD/YYYY");
        }

        return ValidationResult.ok(parsed);
    }

    /**
     * Parse a legacy VARCHAR date string into LocalDateTime (promoted at midnight 00:00:00).
     * Used for TIMESTAMP target columns. Adds INFO-level note about time component loss.
     *
     * @param raw        the raw string from the legacy table
     * @param columnName the source column name for error reporting
     * @param required   if true, null/blank/unparseable yields ERROR; otherwise WARNING
     * @return validation result containing the parsed LocalDateTime or error details
     */
    public ValidationResult<LocalDateTime> parseTimestamp(String raw, String columnName,
                                                          boolean required) {
        ValidationResult<LocalDate> dateResult = parseDate(raw, columnName, required);

        // Propagate errors from date parsing
        if (dateResult.getSeverity() != null
                && dateResult.getSeverity() == ValidationResult.Severity.ERROR) {
            return ValidationResult.error(columnName, raw, dateResult.getErrorMessage());
        }

        // Propagate warnings from date parsing (e.g. unparseable optional value)
        if (dateResult.getSeverity() != null
                && dateResult.getSeverity() == ValidationResult.Severity.WARNING
                && dateResult.getValue() == null) {
            return ValidationResult.warning(columnName, raw, dateResult.getErrorMessage());
        }

        if (dateResult.getValue() == null && !required) {
            return ValidationResult.ok(null);
        }

        if (dateResult.getValue() == null) {
            return ValidationResult.error(columnName, raw,
                    "Required timestamp field could not be parsed");
        }

        // Promote LocalDate to LocalDateTime at midnight
        LocalDateTime ts = dateResult.getValue().atStartOfDay();

        // If the underlying date had an ambiguity warning, preserve it on the timestamp result
        if (dateResult.getSeverity() == ValidationResult.Severity.WARNING) {
            return ValidationResult.warningWithValue(ts, columnName, raw,
                    dateResult.getErrorMessage()
                            + "; time component set to 00:00:00");
        }

        // Normal case: add INFO about time component loss
        return ValidationResult.info(ts, columnName, raw,
                "Time component set to 00:00:00 — legacy source stores date only");
    }

    /**
     * Validate chronological ordering of key loan dates.
     * Checks: origination &lt; maturity, firstPayment &gt; origination,
     * firstPayment &le; maturity, nextPayment &gt; origination.
     *
     * @return list of WARNING results for any ordering violations
     */
    public List<ValidationResult<?>> validateDateOrdering(LocalDate origination, LocalDate maturity,
                                                          LocalDate firstPayment,
                                                          LocalDate nextPayment) {
        List<ValidationResult<?>> results = new ArrayList<>();

        if (origination != null && maturity != null && !origination.isBefore(maturity)) {
            results.add(ValidationResult.warning("origination_date/maturity_date",
                    origination + " / " + maturity,
                    "Origination date should be before maturity date"));
        }

        if (firstPayment != null && origination != null && !firstPayment.isAfter(origination)) {
            results.add(ValidationResult.warning("first_payment_date/origination_date",
                    firstPayment + " / " + origination,
                    "First payment date should be after origination date"));
        }

        if (firstPayment != null && maturity != null && firstPayment.isAfter(maturity)) {
            results.add(ValidationResult.warning("first_payment_date/maturity_date",
                    firstPayment + " / " + maturity,
                    "First payment date should not be after maturity date"));
        }

        if (nextPayment != null && origination != null && !nextPayment.isAfter(origination)) {
            results.add(ValidationResult.warning("next_payment_date/origination_date",
                    nextPayment + " / " + origination,
                    "Next payment date should be after origination date"));
        }

        return results;
    }

    /**
     * Validate chronological ordering of payment processing dates.
     * Checks: receivedDate &ge; paymentDate, processedDate &ge; receivedDate.
     *
     * @return list of WARNING results for any ordering violations
     */
    public List<ValidationResult<?>> validatePaymentDateOrdering(LocalDate paymentDate,
                                                                  LocalDate receivedDate,
                                                                  LocalDate processedDate) {
        List<ValidationResult<?>> results = new ArrayList<>();

        if (receivedDate != null && paymentDate != null && receivedDate.isBefore(paymentDate)) {
            results.add(ValidationResult.warning("received_date/payment_date",
                    receivedDate + " / " + paymentDate,
                    "Received date should not be before payment date"));
        }

        if (processedDate != null && receivedDate != null && processedDate.isBefore(receivedDate)) {
            results.add(ValidationResult.warning("processed_date/received_date",
                    processedDate + " / " + receivedDate,
                    "Processed date should not be before received date"));
        }

        return results;
    }

    // ---- Internal helpers ----

    /** Try each supported format in order; return null if none match */
    private LocalDate tryParse(String value) {
        // Try MM/dd/yyyy (primary legacy format)
        LocalDate result = tryParseWith(value, MM_DD_YYYY);
        if (result != null) return result;

        // Try yyyy-MM-dd (ISO format)
        result = tryParseWith(value, YYYY_MM_DD);
        if (result != null) return result;

        // Try M/d/yyyy (single-digit month/day variant)
        return tryParseWith(value, M_D_YYYY);
    }

    private LocalDate tryParseWith(String value, DateTimeFormatter formatter) {
        try {
            return LocalDate.parse(value, formatter);
        } catch (DateTimeParseException e) {
            return null;
        }
    }
}
