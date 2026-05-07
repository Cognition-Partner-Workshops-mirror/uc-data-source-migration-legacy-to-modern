package com.workshop.loanservice.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.regex.Pattern;

/**
 * Validates and coerces legacy CDW data fields that arrive as loosely-typed
 * VARCHAR strings.  Every method returns a safe value (or null) and logs
 * a warning when the input is malformed.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FMT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final Pattern NUMERIC_CHARS = Pattern.compile("^[\\d,.-]+$");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    // -- amounts / decimals ------------------------------------------------

    /**
     * Parse a legacy amount string such as {@code "285,000"} or
     * {@code "1,487.02"} into a {@link BigDecimal}.
     * <p>Strips commas, currency symbols, and surrounding whitespace.
     * Returns {@link BigDecimal#ZERO} for null / blank / unparseable values.
     */
    public BigDecimal parseAmount(String raw, String fieldName, String recordId) {
        if (raw == null || raw.isBlank()) {
            return BigDecimal.ZERO;
        }
        String cleaned = raw.trim().replace(",", "").replace("$", "");
        try {
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Unparseable amount in {} for {}: '{}' — defaulting to 0",
                    fieldName, recordId, raw);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a plain decimal string (no commas expected) such as
     * {@code "5.250"} into a {@link BigDecimal}.
     */
    public BigDecimal parseDecimal(String raw, String fieldName, String recordId) {
        if (raw == null || raw.isBlank()) {
            return BigDecimal.ZERO;
        }
        String cleaned = raw.trim().replace(",", "");
        try {
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal in {} for {}: '{}' — defaulting to 0",
                    fieldName, recordId, raw);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a string integer (e.g. credit score, term months).
     * Returns {@code null} for null / blank / unparseable values.
     */
    public Integer parseInteger(String raw, String fieldName, String recordId) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        String cleaned = raw.trim().replace(",", "");
        try {
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer in {} for {}: '{}' — defaulting to null",
                    fieldName, recordId, raw);
            return null;
        }
    }

    // -- credit score ------------------------------------------------------

    /**
     * Parse and validate a FICO credit score (300-850 range).
     * Returns {@code null} for out-of-range or unparseable values.
     */
    public Integer parseCreditScore(String raw, String recordId) {
        Integer score = parseInteger(raw, "creditScore", recordId);
        if (score != null && (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX)) {
            log.warn("Credit score out of range ({}-{}) for {}: {} — defaulting to null",
                    CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, recordId, score);
            return null;
        }
        return score;
    }

    // -- dates -------------------------------------------------------------

    /**
     * Parse a legacy {@code MM/DD/YYYY} date string and return an ISO-8601
     * formatted string ({@code yyyy-MM-dd}).  Returns {@code null} for
     * null / blank / unparseable values.
     */
    public String parseLegacyDate(String raw, String fieldName, String recordId) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            LocalDate date = LocalDate.parse(raw.trim(), LEGACY_DATE_FMT);
            return date.toString(); // ISO-8601
        } catch (DateTimeParseException e) {
            log.warn("Unparseable date in {} for {}: '{}' — defaulting to null",
                    fieldName, recordId, raw);
            return null;
        }
    }

    // -- required-field checks ---------------------------------------------

    /**
     * Return the value if non-null/non-blank, otherwise log a warning and
     * return the supplied fallback.
     */
    public String requireNonBlank(String raw, String fieldName,
                                  String recordId, String fallback) {
        if (raw == null || raw.isBlank()) {
            log.warn("Missing required field {} for {} — using fallback '{}'",
                    fieldName, recordId, fallback);
            return fallback;
        }
        return raw;
    }

    // -- referential integrity ---------------------------------------------

    /**
     * Log a warning when a foreign-key lookup returns null and return
     * {@code false} to let callers decide how to handle the orphan.
     */
    public boolean validateReference(Object resolved, String fkField,
                                     String fkValue, String recordId) {
        if (resolved == null) {
            log.warn("Orphaned reference: {}.{}='{}' does not resolve to a valid record",
                    recordId, fkField, fkValue);
            return false;
        }
        return true;
    }

    // -- cross-field consistency -------------------------------------------

    /**
     * Validate that payment component amounts sum to the stated total.
     * Logs a warning if the discrepancy exceeds 0.01.
     */
    public void validatePaymentSum(BigDecimal total, BigDecimal principal,
                                   BigDecimal interest, BigDecimal escrow,
                                   BigDecimal lateFee, String paymentId) {
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        if (total.subtract(componentSum).abs().compareTo(new BigDecimal("0.01")) > 0) {
            log.warn("Payment component mismatch for {}: total={} but components sum to {} (diff={})",
                    paymentId, total, componentSum, total.subtract(componentSum));
        }
    }

    /**
     * Warn when delinquency days are positive but the loan status is Active.
     */
    public void validateDelinquencyConsistency(String statusCode,
                                               Integer delinquencyDays,
                                               String loanId) {
        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(statusCode)) {
            log.warn("Loan {} is Active but has {} delinquency days — possible status inconsistency",
                    loanId, delinquencyDays);
        }
    }
}
