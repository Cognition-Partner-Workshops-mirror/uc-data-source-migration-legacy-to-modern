package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Validates and sanitizes data from legacy CDW tables.
 * Catches known anomalies at ingestion time and provides safe fallbacks.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final Pattern NUMERIC_AMOUNT_PATTERN = Pattern.compile("[^0-9.\\-]");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    /**
     * Parse a legacy amount string (with commas, possible dollar signs, etc.) to BigDecimal.
     * Returns BigDecimal.ZERO for null, blank, or unparseable values.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        String sanitized = NUMERIC_AMOUNT_PATTERN.matcher(amount).replaceAll("");
        if (sanitized.isEmpty()) {
            log.warn("Unparseable amount in {}.{}: '{}' for record {}", fieldName, recordId, amount, recordId);
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            log.warn("Unparseable amount in {}: '{}' for record {}", fieldName, amount, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string to BigDecimal.
     * Returns BigDecimal.ZERO for null, blank, or unparseable values.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        String sanitized = NUMERIC_AMOUNT_PATTERN.matcher(value.trim()).replaceAll("");
        if (sanitized.isEmpty()) {
            log.warn("Unparseable decimal in {}: '{}' for record {}", fieldName, value, recordId);
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal in {}: '{}' for record {}", fieldName, value, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string safely.
     * Returns null for null, blank, or unparseable values.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String trimmed = value.trim().replaceAll("[^0-9\\-]", "");
        if (trimmed.isEmpty()) {
            log.warn("Unparseable integer in {}: '{}' for record {}", fieldName, value, recordId);
            return null;
        }
        try {
            return Integer.parseInt(trimmed);
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer in {}: '{}' for record {}", fieldName, value, recordId);
            return null;
        }
    }

    /**
     * Parse and validate a credit score. Must be numeric and within FICO range (300-850).
     * Returns null for invalid values.
     */
    public Integer parseCreditScore(String value, String recordId) {
        Integer score = parseInteger(value, "creditScore", recordId);
        if (score == null) {
            return null;
        }
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            log.warn("Credit score out of range (300-850) for record {}: {}", recordId, score);
            return null;
        }
        return score;
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format to ISO-8601 (yyyy-MM-dd).
     * Returns the original string (or "N/A") if unparseable.
     */
    public String parseLegacyDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate date = LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return date.toString();
        } catch (DateTimeParseException e) {
            log.warn("Unparseable date in {}: '{}' for record {}", fieldName, dateStr, recordId);
            return dateStr;
        }
    }

    /**
     * Validate a loan status code against known valid values.
     */
    public String validateLoanStatus(String statusCode, String recordId) {
        if (statusCode == null || statusCode.isBlank()) {
            log.warn("Null/blank loan status for record {}, defaulting to 'ACT'", recordId);
            return "ACT";
        }
        String trimmed = statusCode.trim();
        if (!VALID_LOAN_STATUSES.contains(trimmed)) {
            log.warn("Invalid loan status '{}' for record {}, keeping as-is", trimmed, recordId);
        }
        return trimmed;
    }

    /**
     * Validate a payment status code.
     */
    public String validatePaymentStatus(String statusCode, String recordId) {
        if (statusCode == null || statusCode.isBlank()) {
            log.warn("Null/blank payment status for record {}, defaulting to 'PND'", recordId);
            return "PND";
        }
        String trimmed = statusCode.trim();
        if (!VALID_PAYMENT_STATUSES.contains(trimmed)) {
            log.warn("Invalid payment status '{}' for record {}", trimmed, recordId);
        }
        return trimmed;
    }

    /**
     * Validate a payment type code.
     */
    public String validatePaymentType(String typeCode, String recordId) {
        if (typeCode == null || typeCode.isBlank()) {
            log.warn("Null/blank payment type for record {}, defaulting to 'REG'", recordId);
            return "REG";
        }
        String trimmed = typeCode.trim();
        if (!VALID_PAYMENT_TYPES.contains(trimmed)) {
            log.warn("Invalid payment type '{}' for record {}", trimmed, recordId);
        }
        return trimmed;
    }

    /**
     * Validate a property type code.
     */
    public String validatePropertyType(String propertyType, String recordId) {
        if (propertyType == null || propertyType.isBlank()) {
            return null;
        }
        String trimmed = propertyType.trim();
        if (!VALID_PROPERTY_TYPES.contains(trimmed)) {
            log.warn("Invalid property type '{}' for record {}", trimmed, recordId);
        }
        return trimmed;
    }

    /**
     * Validate referential integrity: check that a borrower ID exists in the provided set.
     */
    public boolean validateBorrowerReference(String borrowerId, Set<String> knownBorrowerIds, String loanId) {
        if (borrowerId == null || borrowerId.isBlank()) {
            log.warn("Null/blank borrower ID in loan account {}", loanId);
            return false;
        }
        if (!knownBorrowerIds.contains(borrowerId)) {
            log.warn("Orphaned borrower reference: loan {} references non-existent borrower {}", loanId, borrowerId);
            return false;
        }
        return true;
    }

    /**
     * Validate referential integrity: check that a product code exists in the provided set.
     */
    public boolean validateProductReference(String productCode, Set<String> knownProductCodes, String loanId) {
        if (productCode == null || productCode.isBlank()) {
            log.warn("Null/blank product code in loan account {}", loanId);
            return false;
        }
        if (!knownProductCodes.contains(productCode)) {
            log.warn("Orphaned product reference: loan {} references non-existent product {}", loanId, productCode);
            return false;
        }
        return true;
    }

    /**
     * Validate referential integrity: check that a loan account number exists in the provided set.
     */
    public boolean validateLoanAccountReference(String loanAccountNumber, Set<String> knownLoanIds, String paymentId) {
        if (loanAccountNumber == null || loanAccountNumber.isBlank()) {
            log.warn("Null/blank loan account number in payment {}", paymentId);
            return false;
        }
        if (!knownLoanIds.contains(loanAccountNumber)) {
            log.warn("Orphaned loan reference: payment {} references non-existent loan {}", paymentId, loanAccountNumber);
            return false;
        }
        return true;
    }

    /**
     * Validate that payment component amounts sum to the total (within tolerance).
     */
    public boolean validatePaymentAmounts(BigDecimal total, BigDecimal principal, BigDecimal interest,
                                          BigDecimal escrow, BigDecimal lateFee, String paymentId) {
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal difference = total.subtract(componentSum).abs();
        if (difference.compareTo(new BigDecimal("0.02")) > 0) {
            log.warn("Payment amount mismatch for {}: total={}, components sum={}, diff={}",
                    paymentId, total, componentSum, difference);
            return false;
        }
        return true;
    }

    /**
     * Check for denormalized data divergence between loan account and borrower master.
     */
    public List<String> checkDenormalizedDataDivergence(LegacyLoanAccount acct, LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        if (borrower == null) {
            return warnings;
        }
        String loanId = acct.getLoanAccountNumber();
        if (acct.getBorrowerFirstName() != null && borrower.getFirstName() != null
                && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
            String msg = String.format("First name mismatch for loan %s: loan='%s', borrower='%s'",
                    loanId, acct.getBorrowerFirstName(), borrower.getFirstName());
            warnings.add(msg);
            log.warn(msg);
        }
        if (acct.getBorrowerLastName() != null && borrower.getLastName() != null
                && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
            String msg = String.format("Last name mismatch for loan %s: loan='%s', borrower='%s'",
                    loanId, acct.getBorrowerLastName(), borrower.getLastName());
            warnings.add(msg);
            log.warn(msg);
        }
        return warnings;
    }

    /**
     * Cross-validate delinquency days against loan status.
     */
    public void validateDelinquencyConsistency(String delinquencyDays, String statusCode, String loanId) {
        Integer days = parseInteger(delinquencyDays, "delinquencyDays", loanId);
        if (days != null && days > 0 && "ACT".equals(statusCode)) {
            log.warn("Loan {} has {} delinquency days but status is ACT (Active) — status may need review",
                    loanId, days);
        }
    }

    /**
     * Validate late payment consistency: if received after due date, check for late fee.
     */
    public void validateLatePaymentConsistency(String paymentDate, String receivedDate,
                                                BigDecimal lateFee, String paymentId) {
        if (paymentDate == null || receivedDate == null || paymentDate.isBlank() || receivedDate.isBlank()) {
            return;
        }
        try {
            LocalDate due = LocalDate.parse(paymentDate.trim(), LEGACY_DATE_FORMAT);
            LocalDate received = LocalDate.parse(receivedDate.trim(), LEGACY_DATE_FORMAT);
            if (received.isAfter(due) && lateFee.compareTo(BigDecimal.ZERO) == 0) {
                log.warn("Payment {} received after due date ({} vs {}) but has no late fee",
                        paymentId, receivedDate, paymentDate);
            }
        } catch (DateTimeParseException e) {
            // Date parsing already warned about in parseLegacyDate
        }
    }

    /**
     * Build a safe borrower name from potentially null fields.
     */
    public String safeBorrowerName(String firstName, String lastName) {
        String first = (firstName != null) ? firstName : "Unknown";
        String last = (lastName != null) ? lastName : "Unknown";
        return first + " " + last;
    }
}
