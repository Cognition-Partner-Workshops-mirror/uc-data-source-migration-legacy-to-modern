package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Validates legacy CDW data at ingestion time, catching known anomaly patterns
 * before they propagate into API responses.
 *
 * Anomaly types addressed:
 * - ANO-001: Payment amount component mismatch
 * - ANO-003: Null values in required fields
 * - ANO-004: Delinquency/status inconsistency
 * - ANO-006: Malformed numeric strings
 * - ANO-007: Invalid date formats
 */
@Component
public class DataQualityValidator {

    private static final Logger log = LoggerFactory.getLogger(DataQualityValidator.class);

    // Expected date format for all legacy date fields — strict mode rejects invalid dates like 02/30
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/uuuu")
            .withResolverStyle(ResolverStyle.STRICT);

    // Tolerance for payment component sum vs total comparison (in dollars)
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.01");

    // Valid status codes for each entity type
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA", "DEC", "BKR");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    /**
     * Validate a borrower record and return a list of warnings.
     * Throws DataQualityException for critical failures (null required fields).
     */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        // ANO-003: Null required fields
        if (isBlank(borrower.getFirstName())) {
            throw new DataQualityException("ANO-003", id,
                    "Borrower " + id + " has null/blank first name");
        }
        if (isBlank(borrower.getLastName())) {
            throw new DataQualityException("ANO-003", id,
                    "Borrower " + id + " has null/blank last name");
        }
        if (isBlank(borrower.getBorrowerId())) {
            throw new DataQualityException("ANO-003", id,
                    "Borrower record has null/blank borrower ID");
        }

        // ANO-006: Validate numeric fields parse correctly
        if (!isBlank(borrower.getCreditScore())) {
            Integer score = safeParseInteger(borrower.getCreditScore());
            if (score == null) {
                warnings.add("Borrower " + id + ": credit score '" + borrower.getCreditScore()
                        + "' is not a valid integer");
            } else if (score < 300 || score > 850) {
                // Standard FICO range validation
                warnings.add("Borrower " + id + ": credit score " + score
                        + " is outside valid FICO range (300-850)");
            }
        }

        if (!isBlank(borrower.getAnnualIncome())) {
            BigDecimal income = safeParseAmount(borrower.getAnnualIncome());
            if (income == null) {
                warnings.add("Borrower " + id + ": annual income '"
                        + borrower.getAnnualIncome() + "' is not a valid amount");
            } else if (income.compareTo(BigDecimal.ZERO) < 0) {
                warnings.add("Borrower " + id + ": annual income is negative: " + income);
            }
        }

        // ANO-007: Validate date formats
        if (!isBlank(borrower.getDateOfBirth())) {
            LocalDate dob = safeParseLegacyDate(borrower.getDateOfBirth());
            if (dob == null) {
                warnings.add("Borrower " + id + ": DOB '" + borrower.getDateOfBirth()
                        + "' is not a valid MM/DD/YYYY date");
            }
        }
        if (!isBlank(borrower.getCreatedDate())) {
            if (safeParseLegacyDate(borrower.getCreatedDate()) == null) {
                warnings.add("Borrower " + id + ": created date '"
                        + borrower.getCreatedDate() + "' is not a valid MM/DD/YYYY date");
            }
        }

        // Validate status code
        if (!isBlank(borrower.getStatusCode())
                && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            warnings.add("Borrower " + id + ": unknown status code '"
                    + borrower.getStatusCode() + "'");
        }

        logWarnings(warnings);
        return warnings;
    }

    /**
     * Validate a loan account record and return a list of warnings.
     * Throws DataQualityException for critical failures.
     */
    public List<String> validateLoanAccount(LegacyLoanAccount account) {
        List<String> warnings = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        // ANO-003: Null required fields
        if (isBlank(account.getBorrowerId())) {
            throw new DataQualityException("ANO-003", id,
                    "Loan " + id + " has null/blank borrower ID");
        }
        if (isBlank(account.getProductCode())) {
            throw new DataQualityException("ANO-003", id,
                    "Loan " + id + " has null/blank product code");
        }

        // ANO-006: Validate numeric amount fields
        validateAmountField(account.getOriginalAmount(), "original amount", id, warnings, true);
        validateAmountField(account.getCurrentBalance(), "current balance", id, warnings, true);
        validateAmountField(account.getMonthlyPayment(), "monthly payment", id, warnings, true);

        if (!isBlank(account.getInterestRate())) {
            BigDecimal rate = safeParseDecimal(account.getInterestRate());
            if (rate == null) {
                warnings.add("Loan " + id + ": interest rate '" + account.getInterestRate()
                        + "' is not a valid decimal");
            } else if (rate.compareTo(BigDecimal.ZERO) < 0
                    || rate.compareTo(new BigDecimal("100")) > 0) {
                warnings.add("Loan " + id + ": interest rate " + rate
                        + " is outside valid range (0-100)");
            }
        } else {
            // Interest rate is a required field for loan accounts
            throw new DataQualityException("ANO-003", id,
                    "Loan " + id + " has null/blank interest rate");
        }

        // ANO-004: Delinquency/status consistency check
        if (!isBlank(account.getDelinquencyDays()) && !isBlank(account.getStatusCode())) {
            Integer dlqDays = safeParseInteger(account.getDelinquencyDays());
            if (dlqDays != null && dlqDays > 0 && "ACT".equals(account.getStatusCode())) {
                warnings.add("Loan " + id + ": " + dlqDays
                        + " days delinquent but status is ACT (Active) — potential misclassification");
            }
        }

        // ANO-007: Validate date fields
        validateDateField(account.getOriginationDate(), "origination date", id, warnings);
        validateDateField(account.getMaturityDate(), "maturity date", id, warnings);

        // Validate status code
        if (!isBlank(account.getStatusCode())
                && !VALID_LOAN_STATUSES.contains(account.getStatusCode())) {
            warnings.add("Loan " + id + ": unknown status code '"
                    + account.getStatusCode() + "'");
        }

        // Validate property type code
        if (!isBlank(account.getPropertyType())
                && !VALID_PROPERTY_TYPES.contains(account.getPropertyType())) {
            warnings.add("Loan " + id + ": unknown property type code '"
                    + account.getPropertyType() + "'");
        }

        logWarnings(warnings);
        return warnings;
    }

    /**
     * Validate a payment record and return a list of warnings.
     * Performs ANO-001 component sum check.
     * Throws DataQualityException for critical failures.
     */
    public List<String> validatePayment(LegacyPayment payment) {
        List<String> warnings = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        // ANO-003: Null required fields
        if (isBlank(payment.getLoanAccountNumber())) {
            throw new DataQualityException("ANO-003", id,
                    "Payment " + id + " has null/blank loan account number");
        }
        if (isBlank(payment.getTotalAmount())) {
            throw new DataQualityException("ANO-003", id,
                    "Payment " + id + " has null/blank total amount");
        }
        if (isBlank(payment.getPaymentDate())) {
            throw new DataQualityException("ANO-003", id,
                    "Payment " + id + " has null/blank payment date");
        }

        // ANO-006: Validate numeric fields
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (total == null) {
            warnings.add("Payment " + id + ": total amount '" + payment.getTotalAmount()
                    + "' is not a valid amount");
        }
        if (!isBlank(payment.getPrincipalAmount()) && principal == null) {
            warnings.add("Payment " + id + ": principal amount '"
                    + payment.getPrincipalAmount() + "' is not a valid amount");
        }
        if (!isBlank(payment.getInterestAmount()) && interest == null) {
            warnings.add("Payment " + id + ": interest amount '"
                    + payment.getInterestAmount() + "' is not a valid amount");
        }

        // ANO-001: Payment component sum validation
        if (total != null && principal != null && interest != null) {
            BigDecimal escrowSafe = escrow != null ? escrow : BigDecimal.ZERO;
            BigDecimal lateFeeSafe = lateFee != null ? lateFee : BigDecimal.ZERO;
            BigDecimal componentSum = principal.add(interest).add(escrowSafe).add(lateFeeSafe);
            BigDecimal difference = componentSum.subtract(total).abs();

            if (difference.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
                warnings.add("Payment " + id + ": component sum ("
                        + componentSum.setScale(2, RoundingMode.HALF_UP)
                        + ") does not match total (" + total.setScale(2, RoundingMode.HALF_UP)
                        + "), difference: $" + difference.setScale(2, RoundingMode.HALF_UP));
            }
        }

        // ANO-007: Validate date fields
        validateDateField(payment.getPaymentDate(), "payment date", id, warnings);
        validateDateField(payment.getReceivedDate(), "received date", id, warnings);
        validateDateField(payment.getProcessedDate(), "processed date", id, warnings);

        // Validate type and status codes
        if (!isBlank(payment.getTypeCode())
                && !VALID_PAYMENT_TYPES.contains(payment.getTypeCode())) {
            warnings.add("Payment " + id + ": unknown type code '"
                    + payment.getTypeCode() + "'");
        }
        if (!isBlank(payment.getStatusCode())
                && !VALID_PAYMENT_STATUSES.contains(payment.getStatusCode())) {
            warnings.add("Payment " + id + ": unknown status code '"
                    + payment.getStatusCode() + "'");
        }

        logWarnings(warnings);
        return warnings;
    }

    // =========================================================================
    // Helper methods for safe parsing with error handling
    // =========================================================================

    /**
     * Parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Returns null if the value cannot be parsed (instead of throwing).
     */
    public BigDecimal safeParseAmount(String amount) {
        if (isBlank(amount)) {
            return null;
        }
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
            return null;
        }
    }

    /**
     * Parse a legacy decimal string to BigDecimal with error handling.
     * Returns null if the value cannot be parsed.
     */
    public BigDecimal safeParseDecimal(String value) {
        if (isBlank(value)) {
            return null;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Parse a legacy integer string with error handling.
     * Returns null if the value cannot be parsed.
     */
    public Integer safeParseInteger(String value) {
        if (isBlank(value)) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Parse a legacy date string (MM/DD/YYYY) to LocalDate with error handling.
     * Returns null if the value cannot be parsed.
     */
    public LocalDate safeParseLegacyDate(String dateStr) {
        if (isBlank(dateStr)) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    // =========================================================================
    // Internal helpers
    // =========================================================================

    private void validateAmountField(String value, String fieldName, String recordId,
                                     List<String> warnings, boolean required) {
        if (isBlank(value)) {
            if (required) {
                throw new DataQualityException("ANO-003", recordId,
                        "Record " + recordId + " has null/blank " + fieldName);
            }
            return;
        }
        BigDecimal parsed = safeParseAmount(value);
        if (parsed == null) {
            warnings.add("Record " + recordId + ": " + fieldName + " '" + value
                    + "' is not a valid amount");
        } else if (parsed.compareTo(BigDecimal.ZERO) < 0) {
            warnings.add("Record " + recordId + ": " + fieldName + " is negative: " + parsed);
        }
    }

    private void validateDateField(String value, String fieldName, String recordId,
                                   List<String> warnings) {
        if (!isBlank(value) && safeParseLegacyDate(value) == null) {
            warnings.add("Record " + recordId + ": " + fieldName + " '" + value
                    + "' is not a valid MM/DD/YYYY date");
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private void logWarnings(List<String> warnings) {
        for (String warning : warnings) {
            log.warn("[DATA_QUALITY] {}", warning);
        }
    }
}
