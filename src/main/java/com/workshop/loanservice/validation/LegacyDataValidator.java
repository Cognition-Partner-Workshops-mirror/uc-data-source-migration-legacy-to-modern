package com.workshop.loanservice.validation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Validates and coerces legacy CDW data at ingestion time.
 * Catches the anomalies documented in docs/DATA_ANOMALY_REPORT.md.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.01");

    private static final BigDecimal LTV_TOLERANCE = new BigDecimal("0.5");

    /**
     * Parse a legacy amount string (e.g., "285,000" or "$1,487.02") into BigDecimal.
     * Strips commas, dollar signs, and whitespace. Returns BigDecimal.ZERO for
     * null/blank input and logs a warning for unparseable values.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            log.warn("ANM-002: Null/blank amount in field '{}' for record '{}', defaulting to ZERO",
                    fieldName, recordId);
            return BigDecimal.ZERO;
        }
        String sanitized = amount.replace(",", "")
                .replace("$", "")
                .replace(" ", "")
                .trim();
        try {
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            log.error("ANM-001: Unparseable amount '{}' in field '{}' for record '{}', defaulting to ZERO",
                    amount, fieldName, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., "5.250") into BigDecimal.
     * Strips commas and whitespace.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("ANM-002: Null/blank decimal in field '{}' for record '{}', defaulting to ZERO",
                    fieldName, recordId);
            return BigDecimal.ZERO;
        }
        String sanitized = value.replace(",", "").trim();
        try {
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            log.error("ANM-001: Unparseable decimal '{}' in field '{}' for record '{}', defaulting to ZERO",
                    value, fieldName, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., "360") into Integer.
     * Returns null for null/blank input and for unparseable values.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("ANM-002: Null/blank integer in field '{}' for record '{}'",
                    fieldName, recordId);
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.error("ANM-001: Unparseable integer '{}' in field '{}' for record '{}'",
                    value, fieldName, recordId);
            return null;
        }
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format into LocalDate.
     * Returns null for null/blank or unparseable values.
     */
    public LocalDate parseDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            log.warn("ANM-004: Null/blank date in field '{}' for record '{}'",
                    fieldName, recordId);
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.error("ANM-004: Unparseable date '{}' in field '{}' for record '{}' (expected MM/DD/YYYY)",
                    dateStr, fieldName, recordId);
            return null;
        }
    }

    /**
     * Format a LocalDate to ISO-8601 string, or return "N/A" if null.
     */
    public String formatDateIso(LocalDate date) {
        return date != null ? date.toString() : "N/A";
    }

    /**
     * Validate a credit score is within FICO range (300-850).
     * Returns null for invalid scores.
     */
    public Integer validateCreditScore(String value, String recordId) {
        Integer score = parseInteger(value, "creditScore", recordId);
        if (score == null) {
            return null;
        }
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            log.warn("ANM-009: Credit score {} out of FICO range ({}-{}) for record '{}'",
                    score, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, recordId);
            return null;
        }
        return score;
    }

    /**
     * Validate that a required string field is non-null and non-blank.
     * Returns a fallback value if the field is missing.
     */
    public String validateRequiredString(String value, String fieldName, String recordId, String fallback) {
        if (value == null || value.isBlank()) {
            log.warn("ANM-002: Required field '{}' is null/blank for record '{}', using fallback '{}'",
                    fieldName, recordId, fallback);
            return fallback;
        }
        return value;
    }

    /**
     * Validate payment component amounts sum to the total.
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validatePaymentSum(BigDecimal total, BigDecimal principal,
                                           BigDecimal interest, BigDecimal escrow,
                                           BigDecimal lateFee, String paymentId) {
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal diff = componentSum.subtract(total).abs();
        if (diff.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            String msg = String.format(
                    "ANM-006: Payment '%s' component sum (%s) differs from total (%s) by %s",
                    paymentId, componentSum.setScale(2, RoundingMode.HALF_UP),
                    total.setScale(2, RoundingMode.HALF_UP),
                    diff.setScale(2, RoundingMode.HALF_UP));
            log.warn(msg);
            return List.of(msg);
        }
        return Collections.emptyList();
    }

    /**
     * Validate delinquency days are consistent with status code.
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validateDelinquencyStatus(String delinquencyDays, String statusCode,
                                                   String loanAccountNumber) {
        Integer days = parseInteger(delinquencyDays, "delinquencyDays", loanAccountNumber);
        if (days != null && days > 0 && "ACT".equals(statusCode)) {
            String msg = String.format(
                    "ANM-008: Loan '%s' has %d delinquency days but status is ACT (Active)",
                    loanAccountNumber, days);
            log.warn(msg);
            return List.of(msg);
        }
        return Collections.emptyList();
    }

    /**
     * Validate LTV percent against original amount and appraised value.
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validateLtvPercent(String ltvPercentStr, String originalAmountStr,
                                            String appraisedValueStr, String loanAccountNumber) {
        BigDecimal ltv = parseDecimal(ltvPercentStr, "ltvPercent", loanAccountNumber);
        BigDecimal originalAmount = parseAmount(originalAmountStr, "originalAmount", loanAccountNumber);
        BigDecimal appraisedValue = parseAmount(appraisedValueStr, "appraisedValue", loanAccountNumber);

        if (appraisedValue.compareTo(BigDecimal.ZERO) == 0) {
            return Collections.emptyList();
        }

        BigDecimal calculatedLtv = originalAmount
                .multiply(new BigDecimal("100"))
                .divide(appraisedValue, 2, RoundingMode.HALF_UP);

        BigDecimal diff = calculatedLtv.subtract(ltv).abs();
        if (diff.compareTo(LTV_TOLERANCE) > 0) {
            String msg = String.format(
                    "ANM-011: Loan '%s' stored LTV (%.1f%%) differs from calculated (%.1f%%) by %.1f%%",
                    loanAccountNumber, ltv.doubleValue(), calculatedLtv.doubleValue(), diff.doubleValue());
            log.warn(msg);
            return List.of(msg);
        }
        return Collections.emptyList();
    }

    /**
     * Validate payment date ordering (received date should be >= payment date).
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validatePaymentDateOrder(String paymentDateStr, String receivedDateStr,
                                                  String paymentId) {
        LocalDate paymentDate = parseDate(paymentDateStr, "paymentDate", paymentId);
        LocalDate receivedDate = parseDate(receivedDateStr, "receivedDate", paymentId);

        if (paymentDate == null || receivedDate == null) {
            return Collections.emptyList();
        }

        long dayGap = java.time.temporal.ChronoUnit.DAYS.between(paymentDate, receivedDate);
        if (dayGap > 5) {
            String msg = String.format(
                    "ANM-012: Payment '%s' received %d days after payment date (%s vs %s)",
                    paymentId, dayGap, paymentDateStr, receivedDateStr);
            log.warn(msg);
            return List.of(msg);
        }
        return Collections.emptyList();
    }

    /**
     * Validate referential integrity: check if a foreign key value exists in a collection.
     */
    public boolean validateForeignKey(String fkValue, java.util.Set<String> validKeys,
                                       String fkFieldName, String recordId) {
        if (fkValue == null || fkValue.isBlank()) {
            log.warn("ANM-003: Null foreign key '{}' in record '{}'", fkFieldName, recordId);
            return false;
        }
        if (!validKeys.contains(fkValue)) {
            log.warn("ANM-003: Orphaned foreign key '{}' = '{}' in record '{}' — referenced record does not exist",
                    fkFieldName, fkValue, recordId);
            return false;
        }
        return true;
    }
}
