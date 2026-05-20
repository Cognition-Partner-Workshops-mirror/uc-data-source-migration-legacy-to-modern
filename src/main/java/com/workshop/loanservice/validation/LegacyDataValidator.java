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
 * Validates and safely parses legacy CDW data fields.
 *
 * Legacy data warehouse fields are stored as VARCHAR with known quality issues:
 * - Monetary amounts with comma separators and possible dollar signs
 * - Dates as MM/DD/YYYY strings that may be invalid or malformed
 * - Status codes that may not match any known value
 * - Integer fields that may contain non-numeric placeholders
 *
 * This validator provides safe parsing with fallback defaults and warning logs,
 * ensuring that one bad record does not crash the entire API response.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Expected date format in legacy CDW (strict mode rejects invalid dates like 02/30)
    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/uuuu")
                    .withResolverStyle(ResolverStyle.STRICT);

    // Valid loan status codes recognized by the system
    private static final Set<String> VALID_LOAN_STATUS_CODES =
            Set.of("ACT", "CLO", "DFT", "FRB");

    // Valid payment status codes recognized by the system
    private static final Set<String> VALID_PAYMENT_STATUS_CODES =
            Set.of("PST", "REV", "NSF", "PND");

    // Valid payment type codes recognized by the system
    private static final Set<String> VALID_PAYMENT_TYPE_CODES =
            Set.of("REG", "EXT", "PRT", "PRE");

    // FICO credit score valid range
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    /**
     * Parse a legacy monetary amount string (e.g., "285,000" or "$1,487.02") to BigDecimal.
     * Handles commas, dollar signs, spaces, and accounting-format negatives like "(1,200.00)".
     * Returns BigDecimal.ZERO with a warning log for unparseable values.
     */
    public BigDecimal parseAmount(String amount, String fieldContext) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            // Strip common non-numeric characters: $, spaces, commas
            String cleaned = amount.trim()
                    .replace(",", "")
                    .replace("$", "")
                    .replace(" ", "");

            // Handle accounting-format negatives: (1200.00) → -1200.00
            if (cleaned.startsWith("(") && cleaned.endsWith(")")) {
                cleaned = "-" + cleaned.substring(1, cleaned.length() - 1);
            }

            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}' for field [{}]: {}",
                    amount, fieldContext, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., "5.250") to BigDecimal.
     * Similar to parseAmount but without comma handling (for rates, percentages).
     * Returns BigDecimal.ZERO with a warning log for unparseable values.
     */
    public BigDecimal parseDecimal(String value, String fieldContext) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}' for field [{}]: {}",
                    value, fieldContext, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., "360" for term months) to Integer.
     * Returns null with a warning log for unparseable values.
     */
    public Integer parseInteger(String value, String fieldContext) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}' for field [{}]: {}",
                    value, fieldContext, e.getMessage());
            return null;
        }
    }

    /**
     * Parse and validate a legacy credit score string.
     * Returns null if the value is non-numeric or outside the valid FICO range (300-850).
     */
    public Integer parseCreditScore(String value, String borrowerContext) {
        Integer score = parseInteger(value, "creditScore:" + borrowerContext);
        if (score == null) {
            return null;
        }
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            log.warn("Credit score {} out of valid FICO range [{}-{}] for borrower [{}]",
                    score, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, borrowerContext);
            return null;
        }
        return score;
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format to ISO-8601 string (yyyy-MM-dd).
     * Returns the original string with a warning log if parsing fails, so that API consumers
     * at least get the raw data rather than nothing.
     */
    public String parseDateToIso(String dateStr, String fieldContext) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate date = LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return date.toString(); // ISO-8601: yyyy-MM-dd
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}' for field [{}]: {}",
                    dateStr, fieldContext, e.getMessage());
            // Return the raw string so API consumers at least have the data
            return dateStr;
        }
    }

    /**
     * Validate that a loan status code is recognized.
     * Returns true if valid, false with a warning log otherwise.
     */
    public boolean isValidLoanStatus(String statusCode, String loanContext) {
        if (statusCode == null || statusCode.isBlank()) {
            log.warn("Null/blank loan status code for loan [{}]", loanContext);
            return false;
        }
        if (!VALID_LOAN_STATUS_CODES.contains(statusCode)) {
            log.warn("Unrecognized loan status code '{}' for loan [{}]", statusCode, loanContext);
            return false;
        }
        return true;
    }

    /**
     * Validate that a payment status code is recognized.
     * Returns true if valid, false with a warning log otherwise.
     */
    public boolean isValidPaymentStatus(String statusCode, String paymentContext) {
        if (statusCode == null || statusCode.isBlank()) {
            log.warn("Null/blank payment status code for payment [{}]", paymentContext);
            return false;
        }
        if (!VALID_PAYMENT_STATUS_CODES.contains(statusCode)) {
            log.warn("Unrecognized payment status code '{}' for payment [{}]",
                    statusCode, paymentContext);
            return false;
        }
        return true;
    }

    /**
     * Validate that a payment type code is recognized.
     * Returns true if valid, false with a warning log otherwise.
     */
    public boolean isValidPaymentType(String typeCode, String paymentContext) {
        if (typeCode == null || typeCode.isBlank()) {
            log.warn("Null/blank payment type code for payment [{}]", paymentContext);
            return false;
        }
        if (!VALID_PAYMENT_TYPE_CODES.contains(typeCode)) {
            log.warn("Unrecognized payment type code '{}' for payment [{}]",
                    typeCode, paymentContext);
            return false;
        }
        return true;
    }

    /**
     * Validate payment component consistency: total should equal sum of components.
     * Logs a warning if mismatch detected but does not throw.
     *
     * @return true if components sum correctly, false if mismatch detected
     */
    public boolean validatePaymentComponents(String paymentId,
                                             BigDecimal total,
                                             BigDecimal principal,
                                             BigDecimal interest,
                                             BigDecimal escrow,
                                             BigDecimal lateFee) {
        BigDecimal computedTotal = principal.add(interest).add(escrow).add(lateFee);
        if (computedTotal.compareTo(total) != 0) {
            log.warn("Payment [{}] component mismatch: stated total={}, computed total={} " +
                            "(principal={} + interest={} + escrow={} + lateFee={}), delta={}",
                    paymentId, total, computedTotal,
                    principal, interest, escrow, lateFee,
                    computedTotal.subtract(total));
            return false;
        }
        return true;
    }

    /**
     * Safely concatenate address components, skipping null/blank values.
     * Returns a clean address string without literal "null" text.
     */
    public String formatAddress(String street, String city, String state, String zip) {
        StringBuilder sb = new StringBuilder();
        if (street != null && !street.isBlank()) {
            sb.append(street);
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
        return sb.length() > 0 ? sb.toString() : "Address not available";
    }

    /**
     * Validate that a referenced entity ID exists (non-null, non-blank).
     * Used to detect potential orphaned references.
     */
    public boolean isValidReference(String referenceId, String fieldContext) {
        if (referenceId == null || referenceId.isBlank()) {
            log.warn("Null/blank reference ID for field [{}]", fieldContext);
            return false;
        }
        return true;
    }
}
