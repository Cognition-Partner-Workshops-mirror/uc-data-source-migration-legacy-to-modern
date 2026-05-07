package com.workshop.loanservice.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;

/**
 * Validates and coerces legacy CDW data fields.
 * Handles the known quality issues in the legacy data warehouse:
 * - Numeric values stored as formatted strings with commas
 * - Dates stored as MM/DD/YYYY strings
 * - Missing or malformed values
 * - Cross-field consistency checks
 */
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    /**
     * Parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Returns BigDecimal.ZERO for null, blank, or unparseable values.
     */
    public static BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            if (cleaned.startsWith("(") && cleaned.endsWith(")")) {
                cleaned = "-" + cleaned.substring(1, cleaned.length() - 1);
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Unparseable amount in {} for record {}: '{}' — defaulting to ZERO",
                    fieldName, recordId, amount);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., "4.750") to BigDecimal.
     * Returns BigDecimal.ZERO for null, blank, or unparseable values.
     */
    public static BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal in {} for record {}: '{}' — defaulting to ZERO",
                    fieldName, recordId, value);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., "745") to Integer.
     * Returns null for null, blank, or unparseable values.
     */
    public static Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer in {} for record {}: '{}' — defaulting to null",
                    fieldName, recordId, value);
            return null;
        }
    }

    /**
     * Parse a legacy MM/DD/YYYY date string to ISO 8601 (yyyy-MM-dd) string.
     * Returns the original string if unparseable (with a warning).
     */
    public static String parseDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate date = LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return date.toString();
        } catch (DateTimeParseException e) {
            log.warn("Unparseable date in {} for record {}: '{}' — returning raw value",
                    fieldName, recordId, dateStr);
            return dateStr;
        }
    }

    /**
     * Parse a legacy MM/DD/YYYY date string to LocalDate.
     * Returns null if unparseable.
     */
    public static LocalDate parseDateToLocalDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Unparseable date in {} for record {}: '{}' — returning null",
                    fieldName, recordId, dateStr);
            return null;
        }
    }

    /**
     * Validate that a payment's component amounts sum to its total.
     * Returns a list of warning messages (empty if valid).
     */
    public static List<String> validatePaymentComponents(String paymentId,
                                                          BigDecimal total,
                                                          BigDecimal principal,
                                                          BigDecimal interest,
                                                          BigDecimal escrow,
                                                          BigDecimal lateFee) {
        List<String> warnings = new ArrayList<>();
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        if (total.compareTo(componentSum) != 0) {
            BigDecimal delta = total.subtract(componentSum);
            String msg = String.format(
                    "Payment %s: total (%s) != components sum (%s), delta = %s",
                    paymentId, total, componentSum, delta);
            log.warn("Payment component mismatch: {}", msg);
            warnings.add(msg);
        }
        return warnings;
    }

    /**
     * Validate cross-field consistency between delinquency days and loan status.
     * Returns a list of warning messages (empty if consistent).
     */
    public static List<String> validateLoanStatusConsistency(String loanAccountNumber,
                                                              String statusCode,
                                                              String delinquencyDaysStr) {
        List<String> warnings = new ArrayList<>();
        Integer delinquencyDays = parseInteger(delinquencyDaysStr, "LN_DLQ_DAYS", loanAccountNumber);
        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(statusCode)) {
            String msg = String.format(
                    "Loan %s: %d delinquency days but status is ACT (Active) — possible stale status",
                    loanAccountNumber, delinquencyDays);
            log.warn("Status consistency issue: {}", msg);
            warnings.add(msg);
        }
        return warnings;
    }

    /**
     * Validate that a borrower ID referenced by a loan account exists.
     * Returns a warning message if the borrower is not found, null otherwise.
     */
    public static String validateBorrowerReference(String loanAccountNumber,
                                                    String borrowerId,
                                                    boolean borrowerExists) {
        if (!borrowerExists) {
            String msg = String.format(
                    "Loan %s references non-existent borrower %s — orphaned record",
                    loanAccountNumber, borrowerId);
            log.warn("Referential integrity violation: {}", msg);
            return msg;
        }
        return null;
    }

    /**
     * Validate that a product code referenced by a loan account exists.
     * Returns a warning message if the product is not found, null otherwise.
     */
    public static String validateProductReference(String loanAccountNumber,
                                                   String productCode,
                                                   boolean productExists) {
        if (!productExists) {
            String msg = String.format(
                    "Loan %s references non-existent product %s — orphaned record",
                    loanAccountNumber, productCode);
            log.warn("Referential integrity violation: {}", msg);
            return msg;
        }
        return null;
    }

    /**
     * Validate consistency between denormalized borrower name in loan account
     * and the master borrower record.
     */
    public static String validateDenormalizedBorrowerName(String loanAccountNumber,
                                                           String acctFirstName,
                                                           String acctLastName,
                                                           String masterFirstName,
                                                           String masterLastName) {
        boolean firstMatch = (acctFirstName == null && masterFirstName == null)
                || (acctFirstName != null && acctFirstName.equals(masterFirstName));
        boolean lastMatch = (acctLastName == null && masterLastName == null)
                || (acctLastName != null && acctLastName.equals(masterLastName));
        if (!firstMatch || !lastMatch) {
            String msg = String.format(
                    "Loan %s: denormalized name '%s %s' differs from master '%s %s'",
                    loanAccountNumber, acctFirstName, acctLastName, masterFirstName, masterLastName);
            log.warn("Denormalized data drift: {}", msg);
            return msg;
        }
        return null;
    }

    /**
     * Validate that a received date is not unreasonably after the payment due date.
     * Returns a warning if receivedDate > paymentDate and no late fee was charged.
     */
    public static String validatePaymentTiming(String paymentId,
                                                String paymentDateStr,
                                                String receivedDateStr,
                                                BigDecimal lateFee) {
        LocalDate paymentDate = parseDateToLocalDate(paymentDateStr, "PMT_DT", paymentId);
        LocalDate receivedDate = parseDateToLocalDate(receivedDateStr, "PMT_RECV_DT", paymentId);
        if (paymentDate != null && receivedDate != null && receivedDate.isAfter(paymentDate)) {
            long daysLate = java.time.temporal.ChronoUnit.DAYS.between(paymentDate, receivedDate);
            if (lateFee.compareTo(BigDecimal.ZERO) == 0 && daysLate > 3) {
                String msg = String.format(
                        "Payment %s: received %d days after due date but no late fee charged",
                        paymentId, daysLate);
                log.warn("Payment timing anomaly: {}", msg);
                return msg;
            }
        }
        return null;
    }
}
