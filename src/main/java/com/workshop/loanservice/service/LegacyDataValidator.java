package com.workshop.loanservice.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Set;

/**
 * Validates and coerces legacy CDW data at ingestion time.
 * Handles the known data quality issues in the legacy warehouse:
 * - Numeric strings with commas, dollar signs, or garbage content
 * - Date strings in MM/DD/YYYY format (or inconsistent formats)
 * - Null values in required fields
 * - Cross-field consistency checks (payment component sums, status vs delinquency)
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");

    /**
     * Parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Handles commas, dollar signs, whitespace, and parenthesized negatives.
     * Returns fallback on any parse failure.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.trim()
                    .replace(",", "")
                    .replace("$", "");
            if (cleaned.startsWith("(") && cleaned.endsWith(")")) {
                cleaned = "-" + cleaned.substring(1, cleaned.length() - 1);
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("DATA_QUALITY: Failed to parse amount field '{}' value '{}' for record '{}'. Defaulting to ZERO.",
                    fieldName, amount, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., "5.250") to BigDecimal.
     * Returns fallback on any parse failure.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim().replace(",", "").replace("$", ""));
        } catch (NumberFormatException e) {
            log.warn("DATA_QUALITY: Failed to parse decimal field '{}' value '{}' for record '{}'. Defaulting to ZERO.",
                    fieldName, value, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., "745") to Integer.
     * Returns null on any parse failure.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim().replace(",", ""));
        } catch (NumberFormatException e) {
            log.warn("DATA_QUALITY: Failed to parse integer field '{}' value '{}' for record '{}'. Defaulting to null.",
                    fieldName, value, recordId);
            return null;
        }
    }

    /**
     * Parse a legacy date string (MM/DD/YYYY) to ISO 8601 format (yyyy-MM-dd).
     * Returns the raw string if parsing fails, with a warning log.
     */
    public String parseLegacyDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate parsed = LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return parsed.toString();
        } catch (DateTimeParseException e) {
            log.warn("DATA_QUALITY: Failed to parse date field '{}' value '{}' for record '{}'. Returning raw value.",
                    fieldName, dateStr, recordId);
            return dateStr;
        }
    }

    /**
     * Null-safe string value with fallback.
     */
    public String safeString(String value, String fallback) {
        return (value != null && !value.isBlank()) ? value : fallback;
    }

    /**
     * Build a name string from nullable parts, avoiding "null" literals.
     */
    public String buildFullName(String firstName, String middleInitial, String lastName) {
        String first = safeString(firstName, "[Unknown]");
        String last = safeString(lastName, "[Unknown]");
        String middle = (middleInitial != null && !middleInitial.isBlank())
                ? " " + middleInitial + "."
                : "";
        return first + middle + " " + last;
    }

    /**
     * Build a name from first and last, avoiding "null" literals.
     */
    public String buildSimpleName(String firstName, String lastName) {
        String first = safeString(firstName, "[Unknown]");
        String last = safeString(lastName, "[Unknown]");
        return first + " " + last;
    }

    /**
     * Build an address string from nullable parts, omitting null segments.
     */
    public String buildAddress(String addressLine, String city, String state, String zip) {
        StringBuilder sb = new StringBuilder();
        if (addressLine != null && !addressLine.isBlank()) {
            sb.append(addressLine);
        }
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
        return sb.length() > 0 ? sb.toString() : "[No Address]";
    }

    /**
     * Validate that payment components sum to the total.
     * Returns true if valid, false if mismatch detected.
     */
    public boolean validatePaymentComponentSum(String paymentId,
                                                BigDecimal total,
                                                BigDecimal principal,
                                                BigDecimal interest,
                                                BigDecimal escrow,
                                                BigDecimal lateFee) {
        BigDecimal computedSum = principal.add(interest).add(escrow).add(lateFee);
        if (computedSum.compareTo(total) != 0) {
            log.warn("DATA_QUALITY: Payment '{}' component sum mismatch. Total={}, Components sum={} " +
                            "(principal={}, interest={}, escrow={}, lateFee={}). Delta={}.",
                    paymentId, total, computedSum, principal, interest, escrow, lateFee,
                    computedSum.subtract(total));
            return false;
        }
        return true;
    }

    /**
     * Validate loan status is consistent with delinquency days.
     */
    public void validateStatusDelinquencyConsistency(String loanAccountNumber,
                                                      String statusCode,
                                                      String delinquencyDaysStr) {
        Integer delinquencyDays = parseInteger(delinquencyDaysStr, "LN_DLQ_DAYS", loanAccountNumber);
        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(statusCode)) {
            log.warn("DATA_QUALITY: Loan '{}' has {} delinquency days but status is 'ACT' (Active). " +
                            "Expected a non-active status for delinquent loans.",
                    loanAccountNumber, delinquencyDays);
        }
    }

    /**
     * Validate that a status code is in the known set.
     */
    public boolean isValidLoanStatus(String code) {
        return code != null && VALID_LOAN_STATUSES.contains(code);
    }

    public boolean isValidPaymentStatus(String code) {
        return code != null && VALID_PAYMENT_STATUSES.contains(code);
    }

    public boolean isValidPaymentType(String code) {
        return code != null && VALID_PAYMENT_TYPES.contains(code);
    }

    public boolean isValidPropertyType(String code) {
        return code != null && VALID_PROPERTY_TYPES.contains(code);
    }

    public boolean isValidBorrowerStatus(String code) {
        return code != null && VALID_BORROWER_STATUSES.contains(code);
    }

    /**
     * Validate a status code against a known set. Log a warning for unknown codes.
     */
    public void validateStatusCode(String code, String statusType, String recordId, Set<String> validCodes) {
        if (code != null && !validCodes.contains(code)) {
            log.warn("DATA_QUALITY: Unknown {} code '{}' for record '{}'. Valid codes: {}.",
                    statusType, code, recordId, validCodes);
        }
    }

    /**
     * Validate credit score is in a reasonable range (300-850).
     */
    public Integer validateCreditScore(String creditScoreStr, String recordId) {
        Integer score = parseInteger(creditScoreStr, "BORR_CRDT_SCR", recordId);
        if (score != null && (score < 300 || score > 850)) {
            log.warn("DATA_QUALITY: Borrower '{}' has credit score {} which is outside the valid range (300-850).",
                    recordId, score);
        }
        return score;
    }
}
