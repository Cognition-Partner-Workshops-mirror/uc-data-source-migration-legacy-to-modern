package com.workshop.loanservice.validation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Validates and sanitizes legacy CDW data at ingestion time.
 * Catches known anomalies (malformed numerics, null fields, inconsistent dates)
 * and provides safe fallbacks with logging for observability.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Pattern to strip currency symbols, whitespace, and other non-numeric noise
    // Allows digits, commas, periods, and minus sign
    private static final Pattern NUMERIC_NOISE = Pattern.compile("[^\\d.,-]");

    // Expected legacy date format — strict mode rejects invalid dates like 02/30
    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/uuuu").withResolverStyle(ResolverStyle.STRICT);

    /**
     * Safely parses a legacy amount string (e.g., "285,000" or "$1,487.02") to BigDecimal.
     * Strips commas, currency symbols, and whitespace before parsing.
     * Returns BigDecimal.ZERO with a warning log if the value is unparseable.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        // Strip known noise characters (dollar signs, spaces, etc.)
        String cleaned = NUMERIC_NOISE.matcher(amount).replaceAll("").replace(",", "");
        if (cleaned.isEmpty()) {
            log.warn("DATA_ANOMALY: Unparseable amount in field '{}' for record '{}': raw value='{}'",
                    fieldName, recordId, amount);
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("DATA_ANOMALY: NumberFormatException in field '{}' for record '{}': raw value='{}', cleaned='{}'",
                    fieldName, recordId, amount, cleaned);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parses a legacy decimal string (e.g., "5.250") to BigDecimal.
     * Returns BigDecimal.ZERO with a warning log if unparseable.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        String cleaned = NUMERIC_NOISE.matcher(value.trim()).replaceAll("");
        if (cleaned.isEmpty()) {
            log.warn("DATA_ANOMALY: Unparseable decimal in field '{}' for record '{}': raw value='{}'",
                    fieldName, recordId, value);
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("DATA_ANOMALY: NumberFormatException in field '{}' for record '{}': raw value='{}', cleaned='{}'",
                    fieldName, recordId, value, cleaned);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parses a legacy integer string (e.g., "745") to Integer.
     * Returns null with a warning log if unparseable.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String cleaned = value.trim().replaceAll("[^\\d-]", "");
        if (cleaned.isEmpty()) {
            log.warn("DATA_ANOMALY: Unparseable integer in field '{}' for record '{}': raw value='{}'",
                    fieldName, recordId, value);
            return null;
        }
        try {
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.warn("DATA_ANOMALY: NumberFormatException in field '{}' for record '{}': raw value='{}', cleaned='{}'",
                    fieldName, recordId, value, cleaned);
            return null;
        }
    }

    /**
     * Safely parses a legacy date string in MM/DD/YYYY format to a validated date string.
     * Returns the original string if valid, or null with a warning if invalid.
     */
    public String parseAndValidateDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return dateStr.trim();
        } catch (DateTimeParseException e) {
            log.warn("DATA_ANOMALY: Invalid date format in field '{}' for record '{}': value='{}' (expected MM/DD/YYYY)",
                    fieldName, recordId, dateStr);
            return null;
        }
    }

    /**
     * Null-safe string concatenation that returns empty string for null values
     * instead of the literal "null" that Java produces.
     */
    public String safeString(String value) {
        return value != null ? value : "";
    }

    /**
     * Null-safe string with a default fallback.
     */
    public String safeStringOrDefault(String value, String defaultValue) {
        return (value != null && !value.isBlank()) ? value : defaultValue;
    }

    /**
     * Validates that payment components sum to the total amount.
     * Logs a warning if discrepancy exceeds the tolerance threshold ($0.01).
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validatePaymentIntegrity(String paymentId, BigDecimal total,
                                                  BigDecimal principal, BigDecimal interest,
                                                  BigDecimal escrow, BigDecimal lateFee) {
        List<String> warnings = new ArrayList<>();
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal discrepancy = total.subtract(componentSum).abs();

        // Tolerance of $0.01 for rounding
        if (discrepancy.compareTo(new BigDecimal("0.01")) > 0) {
            String msg = String.format(
                    "Payment component sum mismatch for '%s': total=%s, components=%s (P:%s + I:%s + E:%s + LF:%s), discrepancy=%s",
                    paymentId, total, componentSum, principal, interest, escrow, lateFee, discrepancy);
            log.warn("DATA_ANOMALY: {}", msg);
            warnings.add(msg);
        }
        return warnings;
    }

    /**
     * Validates that delinquency days and loan status are consistent.
     * A loan with delinquency > 0 days should not be marked as plain "Active".
     */
    public List<String> validateLoanStatusConsistency(String loanId, String statusCode,
                                                      String delinquencyDaysStr) {
        List<String> warnings = new ArrayList<>();
        Integer delinquencyDays = parseInteger(delinquencyDaysStr, "LN_DLQ_DAYS", loanId);

        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(statusCode)) {
            String msg = String.format(
                    "Loan '%s' has %d delinquency days but status is 'ACT' (Active) — status may be stale",
                    loanId, delinquencyDays);
            log.warn("DATA_ANOMALY: {}", msg);
            warnings.add(msg);
        }
        return warnings;
    }

    /**
     * Validates referential integrity: checks if a referenced ID is non-null and non-blank.
     * Does not perform database lookup — just ensures the FK field has a plausible value.
     */
    public boolean validateReferenceNotEmpty(String refValue, String fieldName, String recordId) {
        if (refValue == null || refValue.isBlank()) {
            log.warn("DATA_ANOMALY: Missing foreign key reference in field '{}' for record '{}'",
                    fieldName, recordId);
            return false;
        }
        return true;
    }
}
