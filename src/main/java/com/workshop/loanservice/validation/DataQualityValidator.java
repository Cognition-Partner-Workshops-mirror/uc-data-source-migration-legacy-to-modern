package com.workshop.loanservice.validation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Validates and coerces legacy data warehouse values, catching anomalies
 * that would otherwise cause runtime failures or silent data corruption.
 */
public class DataQualityValidator {

    private static final Logger log = LoggerFactory.getLogger(DataQualityValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PRODUCT_STATUSES = Set.of("ACT", "INA");

    private DataQualityValidator() {
    }

    /**
     * Safely parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Strips commas, currency symbols, and whitespace.
     * Returns null if the value cannot be parsed, and logs a warning.
     */
    public static BigDecimal parseAmount(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("DATA_QUALITY: Null/blank amount in field '{}' for record '{}', defaulting to ZERO", fieldName, recordId);
            return BigDecimal.ZERO;
        }
        String cleaned = value.trim()
                .replace(",", "")
                .replace("$", "")
                .replace(" ", "");
        try {
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.error("DATA_QUALITY: Unparseable amount '{}' in field '{}' for record '{}': {}",
                    value, fieldName, recordId, e.getMessage());
            return null;
        }
    }

    /**
     * Safely parse a legacy decimal string (e.g., "5.250" for interest rate) to BigDecimal.
     * Uses the same robust cleaning as parseAmount.
     */
    public static BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        return parseAmount(value, fieldName, recordId);
    }

    /**
     * Safely parse a legacy integer string (e.g., "745" for credit score) to Integer.
     * Returns null and logs a warning if the value is not a valid integer.
     */
    public static Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String cleaned = value.trim().replace(",", "");
        try {
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.error("DATA_QUALITY: Unparseable integer '{}' in field '{}' for record '{}': {}",
                    value, fieldName, recordId, e.getMessage());
            return null;
        }
    }

    /**
     * Parse a legacy MM/dd/yyyy date string to LocalDate.
     * Returns null if the format is invalid.
     */
    public static LocalDate parseDate(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("DATA_QUALITY: Null/blank date in field '{}' for record '{}'", fieldName, recordId);
            return null;
        }
        try {
            return LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.error("DATA_QUALITY: Unparseable date '{}' in field '{}' for record '{}': {}",
                    value, fieldName, recordId, e.getMessage());
            return null;
        }
    }

    /**
     * Validate that a credit score is within the valid FICO range (300–850).
     * Returns the score if valid, null if out of range or unparseable.
     */
    public static Integer validateCreditScore(String value, String recordId) {
        Integer score = parseInteger(value, "creditScore", recordId);
        if (score != null && (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX)) {
            log.warn("DATA_QUALITY: Credit score {} out of valid range ({}-{}) for record '{}'",
                    score, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, recordId);
            return score;
        }
        return score;
    }

    /**
     * Validate that payment component amounts sum to the total.
     * Returns a list of warnings (empty if valid).
     */
    public static List<String> validatePaymentIntegrity(
            BigDecimal total, BigDecimal principal, BigDecimal interest,
            BigDecimal escrow, BigDecimal lateFee, String paymentId) {

        List<String> warnings = new ArrayList<>();

        if (total == null || principal == null || interest == null || escrow == null || lateFee == null) {
            warnings.add("One or more payment amounts could not be parsed");
            return warnings;
        }

        BigDecimal computedSum = principal.add(interest).add(escrow).add(lateFee);
        if (total.compareTo(computedSum) != 0) {
            BigDecimal delta = computedSum.subtract(total);
            String msg = String.format(
                    "Payment %s: component sum (%s) != stated total (%s), delta = %s",
                    paymentId, computedSum.toPlainString(), total.toPlainString(), delta.toPlainString());
            log.warn("DATA_QUALITY: {}", msg);
            warnings.add(msg);
        }

        return warnings;
    }

    /**
     * Validate a status code against a set of known valid codes.
     * Logs a warning for unknown codes but does not reject them.
     */
    public static boolean isValidStatusCode(String code, Set<String> validCodes,
                                            String fieldName, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("DATA_QUALITY: Null/blank status code in field '{}' for record '{}'", fieldName, recordId);
            return false;
        }
        if (!validCodes.contains(code)) {
            log.warn("DATA_QUALITY: Unknown status code '{}' in field '{}' for record '{}'. Valid codes: {}",
                    code, fieldName, recordId, validCodes);
            return false;
        }
        return true;
    }

    /**
     * Validate that a required string field is not null or blank.
     */
    public static boolean isRequiredFieldPresent(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("DATA_QUALITY: Required field '{}' is null/blank for record '{}'", fieldName, recordId);
            return false;
        }
        return true;
    }

    /**
     * Validate loan delinquency days vs status consistency.
     * A loan with delinquency days > 0 and status ACT is suspicious.
     */
    public static List<String> validateLoanStatusConsistency(
            String statusCode, String delinquencyDaysStr, String loanId) {

        List<String> warnings = new ArrayList<>();
        Integer dlqDays = parseInteger(delinquencyDaysStr, "delinquencyDays", loanId);

        if (dlqDays != null && dlqDays > 0 && "ACT".equals(statusCode)) {
            String msg = String.format(
                    "Loan %s: %d delinquency days but status is ACT (Active)", loanId, dlqDays);
            log.warn("DATA_QUALITY: {}", msg);
            warnings.add(msg);
        }

        return warnings;
    }

    /**
     * Validate LTV percentage is within a reasonable range (0–200%).
     */
    public static List<String> validateLtvPercent(String ltvStr, String loanId) {
        List<String> warnings = new ArrayList<>();
        BigDecimal ltv = parseDecimal(ltvStr, "ltvPercent", loanId);

        if (ltv != null) {
            if (ltv.compareTo(BigDecimal.ZERO) < 0 || ltv.compareTo(new BigDecimal("200")) > 0) {
                String msg = String.format("Loan %s: LTV %s%% is outside reasonable range (0-200%%)",
                        loanId, ltv.toPlainString());
                log.warn("DATA_QUALITY: {}", msg);
                warnings.add(msg);
            }
        }

        return warnings;
    }

    public static Set<String> getValidLoanStatuses() {
        return VALID_LOAN_STATUSES;
    }

    public static Set<String> getValidPaymentStatuses() {
        return VALID_PAYMENT_STATUSES;
    }

    public static Set<String> getValidPaymentTypes() {
        return VALID_PAYMENT_TYPES;
    }

    public static Set<String> getValidBorrowerStatuses() {
        return VALID_BORROWER_STATUSES;
    }

    public static Set<String> getValidProductStatuses() {
        return VALID_PRODUCT_STATUSES;
    }
}
