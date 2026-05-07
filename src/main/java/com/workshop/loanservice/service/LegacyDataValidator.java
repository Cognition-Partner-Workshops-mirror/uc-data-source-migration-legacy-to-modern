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
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Validates and sanitizes data read from legacy CDW tables.
 * Catches anomalies at ingestion time: malformed numerics, invalid dates,
 * unrecognized status codes, null required fields, and payment sum mismatches.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/uuuu")
            .withResolverStyle(ResolverStyle.STRICT);

    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_BORROWER_STATUS_CODES = Set.of("ACT", "INA", "SUS", "DEC");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.02");

    /**
     * Parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Returns the fallback value if parsing fails.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId, BigDecimal fallback) {
        if (amount == null || amount.isBlank()) {
            return fallback;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            if (cleaned.startsWith("(") && cleaned.endsWith(")")) {
                cleaned = "-" + cleaned.substring(1, cleaned.length() - 1);
            }
            BigDecimal result = new BigDecimal(cleaned);
            if (result.compareTo(BigDecimal.ZERO) < 0) {
                log.warn("Negative amount in {} for record {}: '{}'", fieldName, recordId, amount);
            }
            return result;
        } catch (NumberFormatException e) {
            log.error("Failed to parse amount in {} for record {}: '{}' — using fallback {}",
                    fieldName, recordId, amount, fallback);
            return fallback;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., "5.250") to BigDecimal.
     * Returns the fallback value if parsing fails.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId, BigDecimal fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.error("Failed to parse decimal in {} for record {}: '{}' — using fallback {}",
                    fieldName, recordId, value, fallback);
            return fallback;
        }
    }

    /**
     * Parse a legacy integer string to Integer.
     * Returns the fallback value if parsing fails.
     */
    public Integer parseInteger(String value, String fieldName, String recordId, Integer fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.error("Failed to parse integer in {} for record {}: '{}' — using fallback {}",
                    fieldName, recordId, value, fallback);
            return fallback;
        }
    }

    /**
     * Parse and validate a legacy date string in MM/DD/YYYY format.
     * Returns null if parsing fails.
     */
    public LocalDate parseDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.error("Failed to parse date in {} for record {}: '{}' — expected MM/DD/YYYY",
                    fieldName, recordId, dateStr);
            return null;
        }
    }

    /**
     * Validate a credit score is within FICO range [300, 850].
     * Returns null if out of range.
     */
    public Integer validateCreditScore(String scoreStr, String recordId) {
        Integer score = parseInteger(scoreStr, "creditScore", recordId, null);
        if (score == null) {
            return null;
        }
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            log.warn("Credit score out of range [{}, {}] for record {}: {}",
                    CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, recordId, score);
            return null;
        }
        return score;
    }

    /**
     * Validate a status code against a known set.
     * Returns the code if valid, or null with a warning if not.
     */
    public String validateStatusCode(String code, Set<String> validCodes, String fieldName, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Missing {} for record {}", fieldName, recordId);
            return null;
        }
        String trimmed = code.trim();
        if (!validCodes.contains(trimmed)) {
            log.warn("Unrecognized {} for record {}: '{}' — valid codes: {}",
                    fieldName, recordId, trimmed, validCodes);
            return trimmed;
        }
        return trimmed;
    }

    /**
     * Validate that a required string field is not null or blank.
     * Returns the value if present, or a default with a warning.
     */
    public String requireNonBlank(String value, String fieldName, String recordId, String defaultValue) {
        if (value == null || value.isBlank()) {
            log.warn("Required field {} is null/blank for record {} — using default '{}'",
                    fieldName, recordId, defaultValue);
            return defaultValue;
        }
        return value;
    }

    /**
     * Validate a borrower record. Returns a list of validation warnings.
     */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add("Missing first name for borrower " + id);
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add("Missing last name for borrower " + id);
        }

        Integer creditScore = validateCreditScore(borrower.getCreditScore(), id);
        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank() && creditScore == null) {
            warnings.add("Invalid credit score for borrower " + id + ": " + borrower.getCreditScore());
        }

        if (parseDate(borrower.getDateOfBirth(), "dateOfBirth", id) == null
                && borrower.getDateOfBirth() != null && !borrower.getDateOfBirth().isBlank()) {
            warnings.add("Invalid date of birth for borrower " + id + ": " + borrower.getDateOfBirth());
        }

        String status = validateStatusCode(borrower.getStatusCode(), VALID_BORROWER_STATUS_CODES, "borrowerStatus", id);
        if (status == null) {
            warnings.add("Missing status code for borrower " + id);
        }

        if (parseAmount(borrower.getAnnualIncome(), "annualIncome", id, null) == null
                && borrower.getAnnualIncome() != null && !borrower.getAnnualIncome().isBlank()) {
            warnings.add("Invalid annual income for borrower " + id + ": " + borrower.getAnnualIncome());
        }

        return warnings;
    }

    /**
     * Validate a loan account record. Returns a list of validation warnings.
     */
    public List<String> validateLoanAccount(LegacyLoanAccount acct, Set<String> validBorrowerIds, Set<String> validProductCodes) {
        List<String> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (acct.getBorrowerId() == null || acct.getBorrowerId().isBlank()) {
            warnings.add("Missing borrower ID for loan " + id);
        } else if (!validBorrowerIds.contains(acct.getBorrowerId())) {
            warnings.add("Orphaned loan " + id + ": borrower ID '" + acct.getBorrowerId() + "' not found");
        }

        if (acct.getProductCode() == null || acct.getProductCode().isBlank()) {
            warnings.add("Missing product code for loan " + id);
        } else if (!validProductCodes.contains(acct.getProductCode())) {
            warnings.add("Orphaned loan " + id + ": product code '" + acct.getProductCode() + "' not found");
        }

        String status = validateStatusCode(acct.getStatusCode(), VALID_LOAN_STATUS_CODES, "loanStatus", id);
        if (status == null) {
            warnings.add("Missing status code for loan " + id);
        }

        if (acct.getPropertyType() != null && !acct.getPropertyType().isBlank()) {
            validateStatusCode(acct.getPropertyType(), VALID_PROPERTY_TYPE_CODES, "propertyType", id);
        }

        if (parseAmount(acct.getOriginalAmount(), "originalAmount", id, null) == null
                && acct.getOriginalAmount() != null && !acct.getOriginalAmount().isBlank()) {
            warnings.add("Invalid original amount for loan " + id + ": " + acct.getOriginalAmount());
        }

        if (parseDate(acct.getOriginationDate(), "originationDate", id) == null
                && acct.getOriginationDate() != null && !acct.getOriginationDate().isBlank()) {
            warnings.add("Invalid origination date for loan " + id + ": " + acct.getOriginationDate());
        }

        return warnings;
    }

    /**
     * Validate a payment record. Returns a list of validation warnings.
     */
    public List<String> validatePayment(LegacyPayment pmt, Set<String> validLoanAccountNumbers) {
        List<String> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (pmt.getLoanAccountNumber() == null || pmt.getLoanAccountNumber().isBlank()) {
            warnings.add("Missing loan account number for payment " + id);
        } else if (!validLoanAccountNumbers.contains(pmt.getLoanAccountNumber())) {
            warnings.add("Orphaned payment " + id + ": loan account '" + pmt.getLoanAccountNumber() + "' not found");
        }

        validateStatusCode(pmt.getStatusCode(), VALID_PAYMENT_STATUS_CODES, "paymentStatus", id);
        validateStatusCode(pmt.getTypeCode(), VALID_PAYMENT_TYPE_CODES, "paymentType", id);

        BigDecimal total = parseAmount(pmt.getTotalAmount(), "totalAmount", id, BigDecimal.ZERO);
        BigDecimal principal = parseAmount(pmt.getPrincipalAmount(), "principalAmount", id, BigDecimal.ZERO);
        BigDecimal interest = parseAmount(pmt.getInterestAmount(), "interestAmount", id, BigDecimal.ZERO);
        BigDecimal escrow = parseAmount(pmt.getEscrowAmount(), "escrowAmount", id, BigDecimal.ZERO);
        BigDecimal lateFee = parseAmount(pmt.getLateFee(), "lateFee", id, BigDecimal.ZERO);

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal delta = componentSum.subtract(total).abs();
        if (delta.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            warnings.add("Payment " + id + " component mismatch: total=" + total
                    + ", components sum=" + componentSum + ", delta=" + delta);
        }

        if (pmt.getPaymentDate() != null && !pmt.getPaymentDate().isBlank()
                && pmt.getReceivedDate() != null && !pmt.getReceivedDate().isBlank()
                && pmt.getProcessedDate() != null && !pmt.getProcessedDate().isBlank()) {
            LocalDate paymentDate = parseDate(pmt.getPaymentDate(), "paymentDate", id);
            LocalDate receivedDate = parseDate(pmt.getReceivedDate(), "receivedDate", id);
            LocalDate processedDate = parseDate(pmt.getProcessedDate(), "processedDate", id);

            if (receivedDate != null && processedDate != null && receivedDate.isAfter(processedDate)) {
                warnings.add("Payment " + id + ": received date (" + pmt.getReceivedDate()
                        + ") is after processed date (" + pmt.getProcessedDate() + ")");
            }

            if (paymentDate != null && receivedDate != null && receivedDate.isAfter(paymentDate)) {
                BigDecimal fee = parseAmount(pmt.getLateFee(), "lateFee", id, BigDecimal.ZERO);
                if (fee.compareTo(BigDecimal.ZERO) == 0) {
                    warnings.add("Payment " + id + ": received late (due " + pmt.getPaymentDate()
                            + ", received " + pmt.getReceivedDate() + ") but no late fee assessed");
                }
            }
        }

        return warnings;
    }

    public Set<String> getValidLoanStatusCodes() {
        return VALID_LOAN_STATUS_CODES;
    }

    public Set<String> getValidPaymentStatusCodes() {
        return VALID_PAYMENT_STATUS_CODES;
    }

    public Set<String> getValidPaymentTypeCodes() {
        return VALID_PAYMENT_TYPE_CODES;
    }

    public Set<String> getValidBorrowerStatusCodes() {
        return VALID_BORROWER_STATUS_CODES;
    }
}
