package com.workshop.loanservice.validation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Set;

/**
 * Validates and safely converts legacy CDW string-typed fields
 * into proper Java types. Handles all known data quality anomalies
 * documented in docs/DATA_ANOMALY_REPORT.md.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final List<DateTimeFormatter> DATE_FORMATTERS = List.of(
            DateTimeFormatter.ofPattern("MM/dd/yyyy"),
            DateTimeFormatter.ofPattern("M/d/yyyy"),
            DateTimeFormatter.ofPattern("yyyy-MM-dd"),
            DateTimeFormatter.ofPattern("MM-dd-yyyy")
    );

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA", "DEC", "SUS");
    private static final Set<String> VALID_PRODUCT_STATUSES = Set.of("ACT", "INA", "EXP");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    /**
     * Safely parses a legacy amount string (e.g. "285,000" or "1,487.02") to BigDecimal.
     * Strips commas, currency symbols, and whitespace before parsing.
     * Returns defaultValue on any parse failure.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId, BigDecimal defaultValue) {
        if (amount == null || amount.isBlank()) {
            return defaultValue;
        }
        String cleaned = amount.trim()
                .replace(",", "")
                .replace("$", "")
                .replace(" ", "");
        try {
            BigDecimal result = new BigDecimal(cleaned);
            if (result.compareTo(BigDecimal.ZERO) < 0) {
                log.warn("Negative amount in {}.{} for record {}: '{}'", fieldName, recordId, recordId, amount);
            }
            return result;
        } catch (NumberFormatException e) {
            log.error("Failed to parse amount {}.{} for record {}: '{}' — using default {}",
                    fieldName, recordId, recordId, amount, defaultValue);
            return defaultValue;
        }
    }

    /**
     * Overload with BigDecimal.ZERO as default.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        return parseAmount(amount, fieldName, recordId, BigDecimal.ZERO);
    }

    /**
     * Safely parses a legacy decimal string (e.g. "5.250") to BigDecimal.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId, BigDecimal defaultValue) {
        if (value == null || value.isBlank()) {
            return defaultValue;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.error("Failed to parse decimal {}.{} for record {}: '{}' — using default {}",
                    fieldName, recordId, recordId, value, defaultValue);
            return defaultValue;
        }
    }

    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        return parseDecimal(value, fieldName, recordId, BigDecimal.ZERO);
    }

    /**
     * Safely parses a legacy integer string to Integer.
     * Returns null on parse failure.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.error("Failed to parse integer {} for record {}: '{}'", fieldName, recordId, value);
            return null;
        }
    }

    /**
     * Parses a credit score string and validates it is within the FICO range (300-850).
     * Returns null if invalid or out of range.
     */
    public Integer parseCreditScore(String value, String recordId) {
        Integer score = parseInteger(value, "creditScore", recordId);
        if (score != null && (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX)) {
            log.warn("Credit score out of range [{}-{}] for record {}: {}",
                    CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, recordId, score);
            return null;
        }
        return score;
    }

    /**
     * Parses a legacy date string (MM/DD/YYYY or other formats) to ISO-8601 (yyyy-MM-dd).
     * Tries multiple formats and returns the original string if none match.
     */
    public String parseAndFormatDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        for (DateTimeFormatter formatter : DATE_FORMATTERS) {
            try {
                LocalDate date = LocalDate.parse(dateStr.trim(), formatter);
                return date.toString(); // ISO-8601
            } catch (DateTimeParseException ignored) {
                // try next formatter
            }
        }
        log.warn("Unable to parse date {} for record {}: '{}' — returning original value",
                fieldName, recordId, dateStr);
        return dateStr;
    }

    /**
     * Validates a status code against an allowed set.
     * Returns the code if valid, logs a warning and returns the code unchanged if not.
     */
    public String validateStatusCode(String code, Set<String> allowedValues, String fieldName, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Null/blank {} for record {}", fieldName, recordId);
            return null;
        }
        String trimmed = code.trim();
        if (!allowedValues.contains(trimmed)) {
            log.warn("Unrecognized {} '{}' for record {} — allowed: {}",
                    fieldName, trimmed, recordId, allowedValues);
        }
        return trimmed;
    }

    public String validateLoanStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_LOAN_STATUSES, "loanStatus", recordId);
    }

    public String validateBorrowerStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_BORROWER_STATUSES, "borrowerStatus", recordId);
    }

    public String validateProductStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_PRODUCT_STATUSES, "productStatus", recordId);
    }

    public String validatePaymentType(String code, String recordId) {
        return validateStatusCode(code, VALID_PAYMENT_TYPES, "paymentType", recordId);
    }

    public String validatePaymentStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_PAYMENT_STATUSES, "paymentStatus", recordId);
    }

    public String validatePropertyType(String code, String recordId) {
        return validateStatusCode(code, VALID_PROPERTY_TYPES, "propertyType", recordId);
    }

    /**
     * Validates that payment component amounts sum to the total.
     * Returns true if balanced, false with a warning log if not.
     */
    public boolean validatePaymentBalance(String paymentId, BigDecimal total,
                                           BigDecimal principal, BigDecimal interest,
                                           BigDecimal escrow, BigDecimal lateFee) {
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        if (total.compareTo(componentSum) != 0) {
            BigDecimal diff = total.subtract(componentSum).abs();
            log.warn("Payment {} components don't sum to total: total={}, components={} (principal={} + interest={} + escrow={} + lateFee={}), diff={}",
                    paymentId, total, componentSum, principal, interest, escrow, lateFee, diff);
            return false;
        }
        return true;
    }

    /**
     * Validates delinquency days vs loan status consistency.
     */
    public void validateDelinquencyConsistency(String loanId, String statusCode, Integer delinquencyDays) {
        if (delinquencyDays == null) return;
        if (delinquencyDays > 0 && "ACT".equals(statusCode)) {
            log.warn("Loan {} is Active but has {} delinquency days", loanId, delinquencyDays);
        }
        if (delinquencyDays > 90 && !"DFT".equals(statusCode)) {
            log.warn("Loan {} has {} delinquency days but status is '{}', expected 'DFT'",
                    loanId, delinquencyDays, statusCode);
        }
    }

    /**
     * Validates LTV percentage against computed value from amount and appraisal.
     */
    public void validateLtv(String loanId, BigDecimal storedLtv, BigDecimal loanAmount, BigDecimal appraisedValue) {
        if (storedLtv == null || loanAmount == null || appraisedValue == null) return;
        if (appraisedValue.compareTo(BigDecimal.ZERO) == 0) {
            log.warn("Loan {} has zero appraised value — cannot validate LTV", loanId);
            return;
        }
        BigDecimal computedLtv = loanAmount.divide(appraisedValue, 4, java.math.RoundingMode.HALF_UP)
                .multiply(new BigDecimal("100"))
                .setScale(1, java.math.RoundingMode.HALF_UP);
        BigDecimal diff = storedLtv.subtract(computedLtv).abs();
        if (diff.compareTo(new BigDecimal("1.0")) > 0) {
            log.warn("Loan {} LTV mismatch: stored={}, computed={} (amount={}, appraisal={})",
                    loanId, storedLtv, computedLtv, loanAmount, appraisedValue);
        }
    }

    /**
     * Builds a null-safe composite string from parts, skipping nulls/blanks.
     */
    public String buildAddress(String address, String city, String state, String zip) {
        StringBuilder sb = new StringBuilder();
        if (address != null && !address.isBlank()) sb.append(address);
        if (city != null && !city.isBlank()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(city);
        }
        if (state != null && !state.isBlank()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(state);
        }
        if (zip != null && !zip.isBlank()) {
            if (sb.length() > 0) sb.append(" ");
            sb.append(zip);
        }
        return sb.length() > 0 ? sb.toString() : "Unknown";
    }

    public Set<String> getValidLoanStatuses() { return VALID_LOAN_STATUSES; }
    public Set<String> getValidPaymentTypes() { return VALID_PAYMENT_TYPES; }
    public Set<String> getValidPaymentStatuses() { return VALID_PAYMENT_STATUSES; }
    public Set<String> getValidPropertyTypes() { return VALID_PROPERTY_TYPES; }
}
