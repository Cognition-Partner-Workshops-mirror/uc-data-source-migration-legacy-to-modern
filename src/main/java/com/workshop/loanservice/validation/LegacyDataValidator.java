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
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Validates and sanitizes data read from legacy CDW tables.
 * Catches known anomaly patterns at ingestion time and provides
 * safe defaults with logged warnings.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final Pattern NUMERIC_CLEANUP = Pattern.compile("[^\\d.\\-]");
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.01");
    private static final BigDecimal LTV_TOLERANCE = new BigDecimal("0.5");

    /**
     * Parse a legacy amount string (e.g., "285,000" or "1,487.02") into BigDecimal.
     * Strips non-numeric characters and handles malformed input gracefully.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        String sanitized = NUMERIC_CLEANUP.matcher(amount).replaceAll("");
        if (sanitized.isEmpty()) {
            log.warn("Non-numeric amount in {} for record {}: '{}'", fieldName, recordId, amount);
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            log.warn("Unparseable amount in {} for record {}: '{}' (sanitized: '{}')",
                    fieldName, recordId, amount, sanitized);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., "5.250") into BigDecimal.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        String sanitized = NUMERIC_CLEANUP.matcher(value.trim()).replaceAll("");
        if (sanitized.isEmpty()) {
            log.warn("Non-numeric decimal in {} for record {}: '{}'", fieldName, recordId, value);
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal in {} for record {}: '{}' (sanitized: '{}')",
                    fieldName, recordId, value, sanitized);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., "745") into Integer.
     * Returns null for unparseable values.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String sanitized = value.trim().replaceAll("[^\\d\\-]", "");
        if (sanitized.isEmpty()) {
            log.warn("Non-numeric integer in {} for record {}: '{}'", fieldName, recordId, value);
            return null;
        }
        try {
            return Integer.parseInt(sanitized);
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer in {} for record {}: '{}' (sanitized: '{}')",
                    fieldName, recordId, value, sanitized);
            return null;
        }
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format into an ISO-8601 string.
     * Returns null for unparseable dates.
     */
    public String parseDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate date = LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return date.toString();
        } catch (DateTimeParseException e) {
            log.warn("Unparseable date in {} for record {}: '{}'", fieldName, recordId, dateStr);
            return null;
        }
    }

    /**
     * Build a safe borrower name, handling null first/last names.
     */
    public String buildBorrowerName(String firstName, String lastName, String middleInitial) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName : "[Unknown]";
        String last = (lastName != null && !lastName.isBlank()) ? lastName : "[Unknown]";
        String middle = (middleInitial != null && !middleInitial.isBlank())
                ? " " + middleInitial + "."
                : "";
        return first + middle + " " + last;
    }

    /**
     * Validate that payment component amounts sum to the total.
     * Returns a list of warnings (empty if valid).
     */
    public List<String> validatePaymentComponents(String paymentId,
                                                   BigDecimal total,
                                                   BigDecimal principal,
                                                   BigDecimal interest,
                                                   BigDecimal escrow,
                                                   BigDecimal lateFee) {
        List<String> warnings = new ArrayList<>();
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal difference = total.subtract(componentSum).abs();

        if (difference.compareTo(PAYMENT_TOLERANCE) > 0) {
            String msg = String.format(
                    "Payment %s: component sum (%.2f) != total (%.2f), difference: %.2f",
                    paymentId, componentSum, total, difference);
            log.warn(msg);
            warnings.add(msg);
        }
        return warnings;
    }

    /**
     * Validate that a late fee is consistent with payment status.
     * Returns a warning if a late fee exists but status doesn't reflect it.
     */
    public List<String> validateLateFeeConsistency(String paymentId,
                                                    BigDecimal lateFee,
                                                    String statusCode) {
        List<String> warnings = new ArrayList<>();
        if (lateFee != null && lateFee.compareTo(BigDecimal.ZERO) > 0
                && "PST".equals(statusCode)) {
            String msg = String.format(
                    "Payment %s: has late fee of %.2f but status is PST (Posted) with no late indicator",
                    paymentId, lateFee);
            log.warn(msg);
            warnings.add(msg);
        }
        return warnings;
    }

    /**
     * Validate that delinquency days are consistent with loan status.
     * Returns a warning if delinquent but status is ACT.
     */
    public List<String> validateDelinquencyStatus(String loanAccountNumber,
                                                   String delinquencyDaysStr,
                                                   String statusCode) {
        List<String> warnings = new ArrayList<>();
        Integer days = parseInteger(delinquencyDaysStr, "LN_DLQ_DAYS", loanAccountNumber);
        if (days != null && days > 0 && "ACT".equals(statusCode)) {
            String msg = String.format(
                    "Loan %s: %d delinquency days but status is ACT (Active)",
                    loanAccountNumber, days);
            log.warn(msg);
            warnings.add(msg);
        }
        return warnings;
    }

    /**
     * Validate stored LTV against computed LTV from original amount and appraised value.
     * Returns a warning if the discrepancy exceeds the tolerance.
     */
    public List<String> validateLtv(String loanAccountNumber,
                                     String ltvStr,
                                     String originalAmountStr,
                                     String appraisedValueStr) {
        List<String> warnings = new ArrayList<>();
        BigDecimal storedLtv = parseDecimal(ltvStr, "LN_LTV_PCT", loanAccountNumber);
        BigDecimal originalAmount = parseAmount(originalAmountStr, "LN_ORIG_AMT", loanAccountNumber);
        BigDecimal appraisedValue = parseAmount(appraisedValueStr, "PROP_APRS_VAL", loanAccountNumber);

        if (appraisedValue.compareTo(BigDecimal.ZERO) > 0 && storedLtv.compareTo(BigDecimal.ZERO) > 0) {
            BigDecimal computedLtv = originalAmount
                    .multiply(new BigDecimal("100"))
                    .divide(appraisedValue, 2, RoundingMode.HALF_UP);
            BigDecimal diff = storedLtv.subtract(computedLtv).abs();
            if (diff.compareTo(LTV_TOLERANCE) > 0) {
                String msg = String.format(
                        "Loan %s: stored LTV (%.2f) differs from computed (%.2f) by %.2f",
                        loanAccountNumber, storedLtv, computedLtv, diff);
                log.warn(msg);
                warnings.add(msg);
            }
        }
        return warnings;
    }

    /**
     * Detect if SSN last-4 matches phone last-4 (indicates corrupted SSN data).
     */
    public List<String> validateSsnNotFromPhone(String recordId,
                                                 String ssnLast4,
                                                 String phoneNumber) {
        List<String> warnings = new ArrayList<>();
        if (ssnLast4 != null && phoneNumber != null && phoneNumber.length() >= 4) {
            String phoneLast4 = phoneNumber.replaceAll("[^\\d]", "");
            if (phoneLast4.length() >= 4) {
                phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
                if (ssnLast4.equals(phoneLast4)) {
                    String msg = String.format(
                            "Record %s: SSN last-4 (%s) matches phone last-4 — possible data corruption",
                            recordId, ssnLast4);
                    log.warn(msg);
                    warnings.add(msg);
                }
            }
        }
        return warnings;
    }

    /**
     * Validate a borrower record for common anomalies.
     */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add(String.format("Borrower %s: missing first name", id));
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add(String.format("Borrower %s: missing last name", id));
        }
        if (borrower.getSsnEncrypted() == null || borrower.getSsnEncrypted().isBlank()) {
            warnings.add(String.format("Borrower %s: missing encrypted SSN", id));
        }

        Integer creditScore = parseInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", id);
        if (creditScore != null && (creditScore < 300 || creditScore > 850)) {
            warnings.add(String.format("Borrower %s: credit score %d outside valid range (300-850)", id, creditScore));
        }

        if (borrower.getDateOfBirth() != null && !borrower.getDateOfBirth().isBlank()) {
            if (parseDate(borrower.getDateOfBirth(), "BORR_DOB_DT", id) == null) {
                warnings.add(String.format("Borrower %s: unparseable date of birth '%s'", id, borrower.getDateOfBirth()));
            }
        }

        if (borrower.getStatusCode() == null || borrower.getStatusCode().isBlank()) {
            warnings.add(String.format("Borrower %s: missing status code", id));
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    /**
     * Validate a loan account record for common anomalies.
     */
    public List<String> validateLoanAccount(LegacyLoanAccount account) {
        List<String> warnings = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        if (account.getBorrowerId() == null || account.getBorrowerId().isBlank()) {
            warnings.add(String.format("Loan %s: missing borrower ID", id));
        }
        if (account.getProductCode() == null || account.getProductCode().isBlank()) {
            warnings.add(String.format("Loan %s: missing product code", id));
        }
        if (account.getStatusCode() == null || account.getStatusCode().isBlank()) {
            warnings.add(String.format("Loan %s: missing status code", id));
        }

        warnings.addAll(validateDelinquencyStatus(id, account.getDelinquencyDays(), account.getStatusCode()));
        warnings.addAll(validateLtv(id, account.getLtvPercent(), account.getOriginalAmount(), account.getAppraisedValue()));

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    /**
     * Validate a payment record for common anomalies.
     */
    public List<String> validatePayment(LegacyPayment payment) {
        List<String> warnings = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        BigDecimal total = parseAmount(payment.getTotalAmount(), "PMT_AMT", id);
        BigDecimal principal = parseAmount(payment.getPrincipalAmount(), "PMT_PRIN_AMT", id);
        BigDecimal interest = parseAmount(payment.getInterestAmount(), "PMT_INT_AMT", id);
        BigDecimal escrow = parseAmount(payment.getEscrowAmount(), "PMT_ESCROW_AMT", id);
        BigDecimal lateFee = parseAmount(payment.getLateFee(), "PMT_LATE_FEE", id);

        warnings.addAll(validatePaymentComponents(id, total, principal, interest, escrow, lateFee));
        warnings.addAll(validateLateFeeConsistency(id, lateFee, payment.getStatusCode()));

        if (payment.getLoanAccountNumber() == null || payment.getLoanAccountNumber().isBlank()) {
            warnings.add(String.format("Payment %s: missing loan account number", id));
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }
}
