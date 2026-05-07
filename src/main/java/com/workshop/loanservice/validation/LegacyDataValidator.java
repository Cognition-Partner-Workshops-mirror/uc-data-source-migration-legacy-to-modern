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

/**
 * Validates legacy CDW data at ingestion time, catching known anomalies
 * before they propagate to the API layer.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/uuuu")
            .withResolverStyle(ResolverStyle.STRICT);
    private static final int MIN_CREDIT_SCORE = 300;
    private static final int MAX_CREDIT_SCORE = 850;
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.01");

    /**
     * Parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Strips commas, dollar signs, whitespace, and other non-numeric characters.
     * Returns BigDecimal.ZERO for null, blank, or unparseable values.
     */
    public BigDecimal parseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.trim()
                    .replace(",", "")
                    .replace("$", "")
                    .replaceAll("[^\\d.\\-]", "");
            if (cleaned.isEmpty()) {
                log.warn("Amount string '{}' contained no numeric characters, defaulting to ZERO", amount);
                return BigDecimal.ZERO;
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse legacy amount '{}': {}", amount, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., "4.750") to BigDecimal.
     * Returns BigDecimal.ZERO for null, blank, or unparseable values.
     */
    public BigDecimal parseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = value.trim().replaceAll("[^\\d.\\-]", "");
            if (cleaned.isEmpty()) {
                log.warn("Decimal string '{}' contained no numeric characters, defaulting to ZERO", value);
                return BigDecimal.ZERO;
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse legacy decimal '{}': {}", value, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., credit score "745") to Integer.
     * Returns null for null, blank, or unparseable values.
     */
    public Integer parseLegacyInteger(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            String cleaned = value.trim().replaceAll("[^\\d\\-]", "");
            if (cleaned.isEmpty()) {
                log.warn("Integer string '{}' contained no numeric characters", value);
                return null;
            }
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse legacy integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format to LocalDate.
     * Returns null for null, blank, or unparseable values.
     */
    public LocalDate parseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse legacy date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    /**
     * Validate a credit score is within the FICO range (300-850).
     * Returns the score if valid, null if out of range or unparseable.
     */
    public Integer validateCreditScore(String creditScoreStr) {
        Integer score = parseLegacyInteger(creditScoreStr);
        if (score == null) {
            return null;
        }
        if (score < MIN_CREDIT_SCORE || score > MAX_CREDIT_SCORE) {
            log.warn("Credit score {} is outside valid FICO range ({}-{})", score, MIN_CREDIT_SCORE, MAX_CREDIT_SCORE);
            return null;
        }
        return score;
    }

    /**
     * Validate that payment component amounts sum to the total.
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validatePaymentAmounts(LegacyPayment payment) {
        List<String> warnings = new ArrayList<>();

        BigDecimal total = parseLegacyAmount(payment.getTotalAmount());
        BigDecimal principal = parseLegacyAmount(payment.getPrincipalAmount());
        BigDecimal interest = parseLegacyAmount(payment.getInterestAmount());
        BigDecimal escrow = parseLegacyAmount(payment.getEscrowAmount());
        BigDecimal lateFee = parseLegacyAmount(payment.getLateFee());

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal difference = componentSum.subtract(total).abs();

        if (difference.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            String msg = String.format(
                    "Payment %s: component sum (%.2f) != total (%.2f), difference: %.2f",
                    payment.getPaymentSequenceNumber(),
                    componentSum, total, difference);
            log.warn(msg);
            warnings.add(msg);
        }

        return warnings;
    }

    /**
     * Validate loan status consistency with delinquency days.
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validateLoanStatusConsistency(LegacyLoanAccount account) {
        List<String> warnings = new ArrayList<>();

        Integer delinquencyDays = parseLegacyInteger(account.getDelinquencyDays());
        String statusCode = account.getStatusCode();

        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(statusCode)) {
            String msg = String.format(
                    "Loan %s: status is ACT but delinquency days is %d",
                    account.getLoanAccountNumber(), delinquencyDays);
            log.warn(msg);
            warnings.add(msg);
        }

        return warnings;
    }

    /**
     * Validate that a borrower's required fields are present.
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add("Borrower " + borrower.getBorrowerId() + ": missing first name");
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add("Borrower " + borrower.getBorrowerId() + ": missing last name");
        }
        if (borrower.getEmail() == null || borrower.getEmail().isBlank()) {
            warnings.add("Borrower " + borrower.getBorrowerId() + ": missing email");
        }

        Integer creditScore = validateCreditScore(borrower.getCreditScore());
        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank() && creditScore == null) {
            warnings.add("Borrower " + borrower.getBorrowerId() + ": invalid credit score '" + borrower.getCreditScore() + "'");
        }

        LocalDate dob = parseLegacyDate(borrower.getDateOfBirth());
        if (borrower.getDateOfBirth() != null && !borrower.getDateOfBirth().isBlank() && dob == null) {
            warnings.add("Borrower " + borrower.getBorrowerId() + ": invalid date of birth '" + borrower.getDateOfBirth() + "'");
        }

        for (String warning : warnings) {
            log.warn(warning);
        }

        return warnings;
    }

    /**
     * Validate referential integrity: check that a loan account's borrower ID
     * and product code reference existing entities.
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validateLoanReferences(LegacyLoanAccount account,
                                                boolean borrowerExists,
                                                boolean productExists) {
        List<String> warnings = new ArrayList<>();

        if (!borrowerExists) {
            String msg = String.format("Loan %s: borrower ID '%s' not found in CDW_BORR_MSTR",
                    account.getLoanAccountNumber(), account.getBorrowerId());
            log.warn(msg);
            warnings.add(msg);
        }

        if (!productExists) {
            String msg = String.format("Loan %s: product code '%s' not found in CDW_LN_PROD",
                    account.getLoanAccountNumber(), account.getProductCode());
            log.warn(msg);
            warnings.add(msg);
        }

        return warnings;
    }

    /**
     * Validate denormalized borrower name consistency between loan account
     * and borrower master.
     * Returns a list of warnings (empty if consistent).
     */
    public List<String> validateDenormalizedBorrowerData(LegacyLoanAccount account,
                                                          LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();

        if (borrower == null) {
            return warnings;
        }

        if (!safeEquals(account.getBorrowerFirstName(), borrower.getFirstName())) {
            String msg = String.format(
                    "Loan %s: denormalized first name '%s' != borrower master '%s'",
                    account.getLoanAccountNumber(), account.getBorrowerFirstName(), borrower.getFirstName());
            log.warn(msg);
            warnings.add(msg);
        }

        if (!safeEquals(account.getBorrowerLastName(), borrower.getLastName())) {
            String msg = String.format(
                    "Loan %s: denormalized last name '%s' != borrower master '%s'",
                    account.getLoanAccountNumber(), account.getBorrowerLastName(), borrower.getLastName());
            log.warn(msg);
            warnings.add(msg);
        }

        return warnings;
    }

    /**
     * Safe string formatting for borrower full name, handling null middle initial.
     */
    public String formatBorrowerName(String firstName, String middleInitial, String lastName) {
        String first = firstName != null ? firstName : "";
        String last = lastName != null ? lastName : "";
        if (middleInitial != null && !middleInitial.isBlank()) {
            return first + " " + middleInitial + ". " + last;
        }
        return (first + " " + last).trim();
    }

    private boolean safeEquals(String a, String b) {
        if (a == null && b == null) return true;
        if (a == null || b == null) return false;
        return a.equals(b);
    }
}
