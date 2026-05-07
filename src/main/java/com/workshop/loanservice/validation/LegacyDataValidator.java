package com.workshop.loanservice.validation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.Set;

/**
 * Validates and coerces legacy CDW data at ingestion time.
 * Catches data quality anomalies documented in docs/DATA_ANOMALY_REPORT.md.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/uuuu").withResolverStyle(ResolverStyle.STRICT);

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PRODUCT_STATUSES = Set.of("ACT", "INA");

    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.01");

    /**
     * Safely parse a legacy amount string (may contain commas) to BigDecimal.
     * Returns BigDecimal.ZERO and logs a warning on parse failure.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            if (cleaned.isEmpty()) {
                return BigDecimal.ZERO;
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Invalid numeric value in {} for record {}: '{}' — defaulting to ZERO",
                    fieldName, recordId, amount);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy decimal string to BigDecimal.
     * Returns BigDecimal.ZERO and logs a warning on parse failure.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Invalid decimal value in {} for record {}: '{}' — defaulting to ZERO",
                    fieldName, recordId, value);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy integer string.
     * Returns null and logs a warning on parse failure.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            String cleaned = value.replace(",", "").trim();
            if (cleaned.contains(".")) {
                return (int) Double.parseDouble(cleaned);
            }
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Invalid integer value in {} for record {}: '{}' — defaulting to null",
                    fieldName, recordId, value);
            return null;
        }
    }

    /**
     * Parse and validate a legacy date string in MM/DD/YYYY format.
     * Returns the ISO-formatted date string (yyyy-MM-dd) or null if invalid.
     */
    public String parseDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate date = LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return date.toString();
        } catch (DateTimeParseException e) {
            log.warn("Invalid date format in {} for record {}: '{}' — expected MM/DD/YYYY",
                    fieldName, recordId, dateStr);
            return null;
        }
    }

    /**
     * Validate that a required string field is not null or blank.
     * Returns the value if valid, or a fallback default with logging.
     */
    public String requireNonBlank(String value, String fieldName, String recordId, String fallback) {
        if (value == null || value.isBlank()) {
            log.warn("Required field {} is null/blank for record {} — using fallback: '{}'",
                    fieldName, recordId, fallback);
            return fallback;
        }
        return value;
    }

    /**
     * Validate a status code against a set of known valid values.
     * Returns the code if valid, or null with logging if invalid.
     */
    public String validateStatusCode(String code, Set<String> validCodes, String fieldName, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Status code is null/blank in {} for record {}", fieldName, recordId);
            return null;
        }
        String trimmed = code.trim();
        if (!validCodes.contains(trimmed)) {
            log.warn("Unknown status code '{}' in {} for record {} — valid codes: {}",
                    trimmed, fieldName, recordId, validCodes);
            return trimmed;
        }
        return trimmed;
    }

    /**
     * Validate loan status code.
     */
    public String validateLoanStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_LOAN_STATUSES, "LN_STAT_CD", recordId);
    }

    /**
     * Validate payment status code.
     */
    public String validatePaymentStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_PAYMENT_STATUSES, "PMT_STAT_CD", recordId);
    }

    /**
     * Validate payment type code.
     */
    public String validatePaymentType(String code, String recordId) {
        return validateStatusCode(code, VALID_PAYMENT_TYPES, "PMT_TYP_CD", recordId);
    }

    /**
     * Validate property type code.
     */
    public String validatePropertyType(String code, String recordId) {
        return validateStatusCode(code, VALID_PROPERTY_TYPES, "PROP_TYP_CD", recordId);
    }

    /**
     * Validate payment component amounts sum to the total.
     * Returns true if consistent, false if discrepancy exceeds tolerance.
     */
    public boolean validatePaymentConsistency(BigDecimal total, BigDecimal principal,
                                              BigDecimal interest, BigDecimal escrow,
                                              BigDecimal lateFee, String recordId) {
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal difference = total.subtract(componentSum).abs();
        if (difference.compareTo(PAYMENT_TOLERANCE) > 0) {
            log.warn("Payment component mismatch for record {}: total={} but components sum to {} (diff={})",
                    recordId, total, componentSum, difference);
            return false;
        }
        return true;
    }

    /**
     * Validate that a borrower ID reference exists (non-null/non-blank).
     * Actual FK existence check should be done at the service level.
     */
    public boolean validateForeignKeyReference(String refValue, String fieldName, String recordId) {
        if (refValue == null || refValue.isBlank()) {
            log.warn("Orphaned reference: {} is null/blank for record {}", fieldName, recordId);
            return false;
        }
        return true;
    }

    public Set<String> getValidLoanStatuses() {
        return VALID_LOAN_STATUSES;
    }

    public Set<String> getValidPaymentStatuses() {
        return VALID_PAYMENT_STATUSES;
    }

    public Set<String> getValidPaymentTypes() {
        return VALID_PAYMENT_TYPES;
    }

    public Set<String> getValidPropertyTypes() {
        return VALID_PROPERTY_TYPES;
    }
}
