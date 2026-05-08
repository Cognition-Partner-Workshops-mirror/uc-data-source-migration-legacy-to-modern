package com.workshop.loanservice.validation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Validates and sanitizes data ingested from legacy CDW tables.
 *
 * Catches known anomaly types identified in docs/DATA_ANOMALY_REPORT.md:
 * - Numeric strings with commas (ANO-004)
 * - Invalid date formats (ANO-010)
 * - Payment component mismatches (ANO-002)
 * - Delinquency/status inconsistencies (ANO-006)
 * - Referential integrity violations (ANO-003)
 * - SSN/phone confusion (ANO-001)
 * - Null required fields (ANO-007)
 */
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Expected date format for all legacy date strings
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    // Valid status codes per table
    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUS_CODES = Set.of("ACT", "INA");

    // Tolerance for payment component sum validation (in dollars)
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.02");

    // Tolerance for LTV percent validation
    private static final BigDecimal LTV_TOLERANCE = new BigDecimal("0.5");

    // Credit score valid range
    private static final int MIN_CREDIT_SCORE = 300;
    private static final int MAX_CREDIT_SCORE = 850;

    /**
     * Parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Strips commas, trims whitespace, and handles malformed input gracefully.
     *
     * @param amount the raw string from the legacy table
     * @param fieldName name of the field for logging context
     * @param recordId ID of the record for logging context
     * @return parsed BigDecimal, or BigDecimal.ZERO as fallback for null/blank/malformed values
     */
    public static BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            log.warn("Null or blank amount for field '{}' on record '{}', defaulting to ZERO", fieldName, recordId);
            return BigDecimal.ZERO;
        }
        try {
            // Strip commas, dollar signs, whitespace, and trailing dashes (mainframe artifacts)
            String cleaned = amount.trim()
                    .replace(",", "")
                    .replace("$", "")
                    .replaceAll("-$", "");
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.error("Failed to parse amount '{}' for field '{}' on record '{}': {}",
                    amount, fieldName, recordId, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., "4.750" or "82.5") to BigDecimal.
     * Also strips commas in case a decimal field has comma formatting.
     *
     * @param value the raw string from the legacy table
     * @param fieldName name of the field for logging context
     * @param recordId ID of the record for logging context
     * @return parsed BigDecimal, or BigDecimal.ZERO as fallback
     */
    public static BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("Null or blank decimal for field '{}' on record '{}', defaulting to ZERO", fieldName, recordId);
            return BigDecimal.ZERO;
        }
        try {
            // Strip commas and percent signs in case they appear
            String cleaned = value.trim()
                    .replace(",", "")
                    .replace("%", "");
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.error("Failed to parse decimal '{}' for field '{}' on record '{}': {}",
                    value, fieldName, recordId, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., "745" or "360") to Integer.
     * Handles commas and non-numeric values gracefully.
     *
     * @param value the raw string from the legacy table
     * @param fieldName name of the field for logging context
     * @param recordId ID of the record for logging context
     * @return parsed Integer, or null as fallback for null/blank/malformed values
     */
    public static Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("Null or blank integer for field '{}' on record '{}', defaulting to null", fieldName, recordId);
            return null;
        }
        try {
            // Strip commas in case an integer field has comma formatting
            String cleaned = value.trim().replace(",", "");
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.error("Failed to parse integer '{}' for field '{}' on record '{}': {}",
                    value, fieldName, recordId, e.getMessage());
            return null;
        }
    }

    /**
     * Validate and parse a legacy date string in MM/DD/YYYY format.
     *
     * @param dateStr the raw date string
     * @param fieldName name of the field for logging context
     * @param recordId ID of the record for logging context
     * @return parsed LocalDate, or null if the string is null/blank/malformed
     */
    public static LocalDate parseDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            log.warn("Null or blank date for field '{}' on record '{}', defaulting to null", fieldName, recordId);
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.error("Invalid date format '{}' for field '{}' on record '{}' (expected MM/DD/YYYY): {}",
                    dateStr, fieldName, recordId, e.getMessage());
            return null;
        }
    }

    /**
     * Validate that a status code is in the allowed set.
     *
     * @param code the status code to validate
     * @param validCodes set of allowed codes
     * @param fieldName name of the field for logging context
     * @param recordId ID of the record for logging context
     * @return the code if valid, or "UNKNOWN" as fallback
     */
    public static String validateStatusCode(String code, Set<String> validCodes, String fieldName, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Null or blank status code for field '{}' on record '{}', defaulting to UNKNOWN", fieldName, recordId);
            return "UNKNOWN";
        }
        String trimmed = code.trim();
        if (!validCodes.contains(trimmed)) {
            log.error("Invalid status code '{}' for field '{}' on record '{}'. Valid codes: {}",
                    trimmed, fieldName, recordId, validCodes);
            return trimmed; // Return as-is but log the error
        }
        return trimmed;
    }

    /**
     * Validate that payment components sum to the total amount (ANO-002).
     * Returns a list of warnings (empty if valid).
     *
     * @param totalAmount the reported total payment
     * @param principalAmount the principal component
     * @param interestAmount the interest component
     * @param escrowAmount the escrow component
     * @param paymentId the payment record ID for logging
     * @return list of validation warnings
     */
    public static List<String> validatePaymentComponents(BigDecimal totalAmount, BigDecimal principalAmount,
                                                         BigDecimal interestAmount, BigDecimal escrowAmount,
                                                         String paymentId) {
        List<String> warnings = new ArrayList<>();

        // Sum the components: principal + interest + escrow
        BigDecimal componentSum = principalAmount.add(interestAmount).add(escrowAmount);
        BigDecimal difference = componentSum.subtract(totalAmount).abs();

        if (difference.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            String msg = String.format(
                    "Payment '%s': component sum (%.2f) != total (%.2f), difference = %.2f",
                    paymentId, componentSum, totalAmount, difference);
            log.error(msg);
            warnings.add(msg);
        }

        return warnings;
    }

    /**
     * Validate that a credit score is within a reasonable range (ANO-004/ANO-007).
     *
     * @param creditScore the parsed credit score
     * @param borrowerId the borrower ID for logging
     * @return the credit score if valid, or null if out of range
     */
    public static Integer validateCreditScore(Integer creditScore, String borrowerId) {
        if (creditScore == null) {
            log.warn("Null credit score for borrower '{}'", borrowerId);
            return null;
        }
        if (creditScore < MIN_CREDIT_SCORE || creditScore > MAX_CREDIT_SCORE) {
            log.error("Credit score {} out of valid range [{}-{}] for borrower '{}'",
                    creditScore, MIN_CREDIT_SCORE, MAX_CREDIT_SCORE, borrowerId);
            return null;
        }
        return creditScore;
    }

    /**
     * Validate delinquency days vs loan status consistency (ANO-006).
     * Returns a warning message if inconsistent, or null if consistent.
     *
     * @param delinquencyDays the number of delinquency days
     * @param statusCode the loan status code
     * @param loanAccountNumber the loan account ID for logging
     * @return warning message if inconsistent, null otherwise
     */
    public static String validateDelinquencyStatus(Integer delinquencyDays, String statusCode, String loanAccountNumber) {
        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(statusCode)) {
            String msg = String.format(
                    "Loan '%s' has %d delinquency days but status is 'ACT' — expected DFT or DLQ status",
                    loanAccountNumber, delinquencyDays);
            log.warn(msg);
            return msg;
        }
        return null;
    }

    /**
     * Detect SSN last-4 / phone number confusion (ANO-001).
     * Returns a warning if the SSN last-4 matches the phone number suffix.
     *
     * @param ssnLast4 the SSN last-4 field
     * @param phoneNumber the borrower phone number
     * @param recordId the record ID for logging
     * @return warning message if suspicious, null otherwise
     */
    public static String validateSsnNotPhoneSuffix(String ssnLast4, String phoneNumber, String recordId) {
        if (ssnLast4 == null || phoneNumber == null) {
            return null;
        }
        // Extract last 4 digits of phone number
        String phoneDigitsOnly = phoneNumber.replaceAll("[^0-9]", "");
        if (phoneDigitsOnly.length() >= 4) {
            String phoneLast4 = phoneDigitsOnly.substring(phoneDigitsOnly.length() - 4);
            if (ssnLast4.equals(phoneLast4)) {
                String msg = String.format(
                        "Record '%s': SSN last-4 '%s' matches phone suffix '%s' — likely data corruption (ANO-001)",
                        recordId, ssnLast4, phoneLast4);
                log.error(msg);
                return msg;
            }
        }
        return null;
    }

    /**
     * Validate that a required string field is not null or blank.
     *
     * @param value the field value
     * @param fieldName name of the field for logging
     * @param recordId the record ID for logging
     * @param defaultValue the fallback value if null/blank
     * @return the original value if present, or defaultValue if null/blank
     */
    public static String requireNonBlank(String value, String fieldName, String recordId, String defaultValue) {
        if (value == null || value.isBlank()) {
            log.warn("Required field '{}' is null/blank on record '{}', defaulting to '{}'",
                    fieldName, recordId, defaultValue);
            return defaultValue;
        }
        return value;
    }

    /**
     * Validate LTV percent against the computed value from original amount and appraised value (ANO-009).
     *
     * @param storedLtv the LTV percentage stored in the legacy table
     * @param originalAmount the loan original amount
     * @param appraisedValue the property appraised value
     * @param loanAccountNumber the loan account ID for logging
     * @return warning message if discrepancy exceeds tolerance, null otherwise
     */
    public static String validateLtvPercent(BigDecimal storedLtv, BigDecimal originalAmount,
                                            BigDecimal appraisedValue, String loanAccountNumber) {
        if (storedLtv == null || originalAmount == null || appraisedValue == null
                || appraisedValue.compareTo(BigDecimal.ZERO) == 0) {
            return null;
        }
        BigDecimal computedLtv = originalAmount.divide(appraisedValue, 4, RoundingMode.HALF_UP)
                .multiply(new BigDecimal("100"))
                .setScale(2, RoundingMode.HALF_UP);
        BigDecimal difference = storedLtv.subtract(computedLtv).abs();

        if (difference.compareTo(LTV_TOLERANCE) > 0) {
            String msg = String.format(
                    "Loan '%s': stored LTV (%.2f%%) differs from computed LTV (%.2f%%) by %.2f%%",
                    loanAccountNumber, storedLtv, computedLtv, difference);
            log.warn(msg);
            return msg;
        }
        return null;
    }

    // Expose valid code sets for use in service layer
    public static Set<String> getValidLoanStatusCodes() { return VALID_LOAN_STATUS_CODES; }
    public static Set<String> getValidPaymentTypeCodes() { return VALID_PAYMENT_TYPE_CODES; }
    public static Set<String> getValidPaymentStatusCodes() { return VALID_PAYMENT_STATUS_CODES; }
    public static Set<String> getValidPropertyTypeCodes() { return VALID_PROPERTY_TYPE_CODES; }
    public static Set<String> getValidBorrowerStatusCodes() { return VALID_BORROWER_STATUS_CODES; }
}
