package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.service.ValidationResult.Severity;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Set;

/**
 * Validates legacy CDW records at ingestion time, detecting the data quality
 * anomalies documented in docs/DATA_ANOMALY_REPORT.md.
 *
 * Each validation method appends findings to a {@link ValidationResult} and
 * returns a sanitised/coerced value where a safe default exists.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Expected date format in legacy CDW data
    private static final DateTimeFormatter LEGACY_DATE_FMT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    // Valid status-code sets (ANM-009)
    private static final Set<String> VALID_LOAN_STATUSES   = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PMT_TYPES       = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PMT_STATUSES    = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_BORR_STATUSES   = Set.of("ACT", "INA");
    private static final Set<String> VALID_PROPERTY_TYPES  = Set.of("SFR", "CND", "MFR", "TWN");

    // =========================================================================
    // Borrower validation
    // =========================================================================

    /**
     * Validates a legacy borrower record for null-required fields,
     * numeric-string parsing risks, and invalid status codes.
     */
    public ValidationResult validateBorrower(LegacyBorrower b) {
        ValidationResult result = new ValidationResult();
        String id = b.getBorrowerId();

        // ANM-003: null checks on required business fields
        if (isBlank(b.getFirstName())) {
            result.addFinding(Severity.HIGH, "ANM-003",
                    "Borrower " + id + ": first name is null/blank");
        }
        if (isBlank(b.getLastName())) {
            result.addFinding(Severity.HIGH, "ANM-003",
                    "Borrower " + id + ": last name is null/blank");
        }
        if (isBlank(b.getEmail())) {
            result.addFinding(Severity.MEDIUM, "ANM-003",
                    "Borrower " + id + ": email is null/blank");
        }

        // ANM-004: credit score must be a valid integer
        if (!isBlank(b.getCreditScore()) && !isValidInteger(b.getCreditScore())) {
            result.addFinding(Severity.HIGH, "ANM-004",
                    "Borrower " + id + ": credit score '" + b.getCreditScore() + "' is not a valid integer");
        }

        // ANM-004: annual income must be a parseable amount
        if (!isBlank(b.getAnnualIncome()) && !isValidAmount(b.getAnnualIncome())) {
            result.addFinding(Severity.HIGH, "ANM-004",
                    "Borrower " + id + ": annual income '" + b.getAnnualIncome() + "' is not a valid amount");
        }

        // ANM-007: date fields must parse as MM/DD/YYYY
        validateDateField(result, "Borrower " + id, "dateOfBirth", b.getDateOfBirth());
        validateDateField(result, "Borrower " + id, "createdDate", b.getCreatedDate());
        validateDateField(result, "Borrower " + id, "updatedDate", b.getUpdatedDate());

        // ANM-009: status code validation
        if (!isBlank(b.getStatusCode()) && !VALID_BORR_STATUSES.contains(b.getStatusCode())) {
            result.addFinding(Severity.MEDIUM, "ANM-009",
                    "Borrower " + id + ": unrecognized status code '" + b.getStatusCode() + "'");
        }

        if (result.hasWarnings()) {
            log.warn("Borrower {} has {} validation finding(s)", id, result.getFindings().size());
        }
        return result;
    }

    // =========================================================================
    // Loan account validation
    // =========================================================================

    /**
     * Validates a legacy loan account record. Cross-checks denormalized
     * borrower data and detects the SSN-phone-number corruption (ANM-001).
     */
    public ValidationResult validateLoanAccount(LegacyLoanAccount acct,
                                                 LegacyBorrower borrower) {
        ValidationResult result = new ValidationResult();
        String id = acct.getLoanAccountNumber();

        // ANM-001: SSN last-4 vs phone number last-4
        if (borrower != null && !isBlank(acct.getBorrowerSsnLast4())
                && !isBlank(borrower.getPhoneNumber())) {
            String phoneLast4 = borrower.getPhoneNumber()
                    .replaceAll("[^0-9]", "");  // strip non-digits
            if (phoneLast4.length() >= 4) {
                phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
                if (phoneLast4.equals(acct.getBorrowerSsnLast4())) {
                    result.addFinding(Severity.CRITICAL, "ANM-001",
                            "Loan " + id + ": BORR_SSN_LST4 '" + acct.getBorrowerSsnLast4()
                                    + "' matches phone last-4 — likely populated from phone, not SSN");
                }
            }
        }

        // ANM-003: null checks on critical loan fields
        if (isBlank(acct.getOriginalAmount())) {
            result.addFinding(Severity.HIGH, "ANM-003",
                    "Loan " + id + ": original amount is null/blank");
        }
        if (isBlank(acct.getCurrentBalance())) {
            result.addFinding(Severity.HIGH, "ANM-003",
                    "Loan " + id + ": current balance is null/blank");
        }
        if (isBlank(acct.getInterestRate())) {
            result.addFinding(Severity.HIGH, "ANM-003",
                    "Loan " + id + ": interest rate is null/blank");
        }
        if (isBlank(acct.getStatusCode())) {
            result.addFinding(Severity.HIGH, "ANM-003",
                    "Loan " + id + ": status code is null/blank");
        }

        // ANM-004: numeric string parsing validation
        validateAmountField(result, "Loan " + id, "originalAmount", acct.getOriginalAmount());
        validateAmountField(result, "Loan " + id, "currentBalance", acct.getCurrentBalance());
        validateAmountField(result, "Loan " + id, "monthlyPayment", acct.getMonthlyPayment());
        validateAmountField(result, "Loan " + id, "escrowBalance", acct.getEscrowBalance());
        validateAmountField(result, "Loan " + id, "appraisedValue", acct.getAppraisedValue());
        validateDecimalField(result, "Loan " + id, "interestRate", acct.getInterestRate());
        validateDecimalField(result, "Loan " + id, "ltvPercent", acct.getLtvPercent());
        validateIntegerField(result, "Loan " + id, "termMonths", acct.getTermMonths());
        validateIntegerField(result, "Loan " + id, "delinquencyDays", acct.getDelinquencyDays());

        // ANM-005: orphaned borrower reference
        if (!isBlank(acct.getBorrowerId()) && borrower == null) {
            result.addFinding(Severity.HIGH, "ANM-005",
                    "Loan " + id + ": BORR_ID '" + acct.getBorrowerId()
                            + "' does not exist in CDW_BORR_MSTR");
        }

        // ANM-006: delinquency days vs status consistency
        if (!isBlank(acct.getDelinquencyDays()) && !isBlank(acct.getStatusCode())) {
            int dlqDays = safeParseInt(acct.getDelinquencyDays(), 0);
            if (dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
                result.addFinding(Severity.HIGH, "ANM-006",
                        "Loan " + id + ": " + dlqDays + " delinquency days but status is ACT (Active)");
            }
        }

        // ANM-007: date fields
        validateDateField(result, "Loan " + id, "originationDate", acct.getOriginationDate());
        validateDateField(result, "Loan " + id, "maturityDate", acct.getMaturityDate());
        validateDateField(result, "Loan " + id, "firstPaymentDate", acct.getFirstPaymentDate());
        validateDateField(result, "Loan " + id, "nextPaymentDate", acct.getNextPaymentDate());

        // ANM-008: denormalized name drift check
        if (borrower != null) {
            if (!isBlank(acct.getBorrowerFirstName()) && !isBlank(borrower.getFirstName())
                    && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
                result.addFinding(Severity.MEDIUM, "ANM-008",
                        "Loan " + id + ": denormalized first name '" + acct.getBorrowerFirstName()
                                + "' differs from master '" + borrower.getFirstName() + "'");
            }
            if (!isBlank(acct.getBorrowerLastName()) && !isBlank(borrower.getLastName())
                    && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
                result.addFinding(Severity.MEDIUM, "ANM-008",
                        "Loan " + id + ": denormalized last name '" + acct.getBorrowerLastName()
                                + "' differs from master '" + borrower.getLastName() + "'");
            }
        }

        // ANM-009: status code validation
        if (!isBlank(acct.getStatusCode()) && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            result.addFinding(Severity.MEDIUM, "ANM-009",
                    "Loan " + id + ": unrecognized status code '" + acct.getStatusCode() + "'");
        }

        // ANM-009: property type code validation
        if (!isBlank(acct.getPropertyType()) && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            result.addFinding(Severity.MEDIUM, "ANM-009",
                    "Loan " + id + ": unrecognized property type '" + acct.getPropertyType() + "'");
        }

        if (result.hasWarnings()) {
            log.warn("Loan {} has {} validation finding(s)", id, result.getFindings().size());
        }
        return result;
    }

    // =========================================================================
    // Payment validation
    // =========================================================================

    /**
     * Validates a legacy payment record. Checks component-sum consistency
     * (ANM-002), null amounts, status codes, and date parsing.
     */
    public ValidationResult validatePayment(LegacyPayment pmt) {
        ValidationResult result = new ValidationResult();
        String id = pmt.getPaymentSequenceNumber();

        // ANM-002: component amounts must sum to total
        BigDecimal total     = safeParseAmount(pmt.getTotalAmount());
        BigDecimal principal = safeParseAmount(pmt.getPrincipalAmount());
        BigDecimal interest  = safeParseAmount(pmt.getInterestAmount());
        BigDecimal escrow    = safeParseAmount(pmt.getEscrowAmount());
        BigDecimal lateFee   = safeParseAmount(pmt.getLateFee());
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);

        // Allow a 1-cent tolerance for floating-point rounding
        if (total.subtract(componentSum).abs().compareTo(new BigDecimal("0.01")) > 0) {
            result.addFinding(Severity.CRITICAL, "ANM-002",
                    "Payment " + id + ": component sum (" + componentSum
                            + ") differs from total (" + total + "), discrepancy = "
                            + componentSum.subtract(total));
        }

        // ANM-003: null checks on critical payment fields
        if (isBlank(pmt.getTotalAmount())) {
            result.addFinding(Severity.HIGH, "ANM-003",
                    "Payment " + id + ": total amount is null/blank");
        }
        if (isBlank(pmt.getLoanAccountNumber())) {
            result.addFinding(Severity.HIGH, "ANM-003",
                    "Payment " + id + ": loan account number is null/blank");
        }

        // ANM-004: numeric string validation for all amount fields
        validateAmountField(result, "Payment " + id, "totalAmount", pmt.getTotalAmount());
        validateAmountField(result, "Payment " + id, "principalAmount", pmt.getPrincipalAmount());
        validateAmountField(result, "Payment " + id, "interestAmount", pmt.getInterestAmount());
        validateAmountField(result, "Payment " + id, "escrowAmount", pmt.getEscrowAmount());
        validateAmountField(result, "Payment " + id, "lateFee", pmt.getLateFee());

        // ANM-007: date validation
        validateDateField(result, "Payment " + id, "paymentDate", pmt.getPaymentDate());
        validateDateField(result, "Payment " + id, "receivedDate", pmt.getReceivedDate());
        validateDateField(result, "Payment " + id, "processedDate", pmt.getProcessedDate());

        // ANM-009: type and status code validation
        if (!isBlank(pmt.getTypeCode()) && !VALID_PMT_TYPES.contains(pmt.getTypeCode())) {
            result.addFinding(Severity.MEDIUM, "ANM-009",
                    "Payment " + id + ": unrecognized type code '" + pmt.getTypeCode() + "'");
        }
        if (!isBlank(pmt.getStatusCode()) && !VALID_PMT_STATUSES.contains(pmt.getStatusCode())) {
            result.addFinding(Severity.MEDIUM, "ANM-009",
                    "Payment " + id + ": unrecognized status code '" + pmt.getStatusCode() + "'");
        }

        if (result.hasWarnings()) {
            log.warn("Payment {} has {} validation finding(s)", id, result.getFindings().size());
        }
        return result;
    }

    // =========================================================================
    // Safe parsing helpers — used by both the validator and LoanService
    // =========================================================================

    /**
     * Parses a legacy amount string (e.g. "285,000" or "1,487.02") to BigDecimal.
     * Returns BigDecimal.ZERO for null/blank/unparseable values and logs a warning.
     */
    public BigDecimal safeParseAmount(String amount) {
        if (isBlank(amount)) return BigDecimal.ZERO;
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parses a legacy decimal string (e.g. "5.250") to BigDecimal.
     * Returns BigDecimal.ZERO for null/blank/unparseable values.
     */
    public BigDecimal safeParseDecimal(String value) {
        if (isBlank(value)) return BigDecimal.ZERO;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}': {}", value, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parses a legacy integer string (e.g. "360") to Integer.
     * Returns null for null/blank/unparseable values.
     */
    public Integer safeParseInteger(String value) {
        if (isBlank(value)) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Parses a legacy MM/DD/YYYY date string to LocalDate.
     * Returns null for null/blank/unparseable values.
     */
    public LocalDate safeParseDate(String dateStr) {
        if (isBlank(dateStr)) return null;
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FMT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    /**
     * Returns the input string if non-blank, otherwise returns the fallback.
     * Prevents "null" literal in string concatenation (ANM-003).
     */
    public String safeString(String value, String fallback) {
        return isBlank(value) ? fallback : value;
    }

    // =========================================================================
    // Internal helpers
    // =========================================================================

    private void validateDateField(ValidationResult result, String entity,
                                   String field, String value) {
        if (!isBlank(value)) {
            try {
                LocalDate.parse(value.trim(), LEGACY_DATE_FMT);
            } catch (DateTimeParseException e) {
                result.addFinding(Severity.MEDIUM, "ANM-007",
                        entity + ": " + field + " '" + value + "' is not a valid MM/DD/YYYY date");
            }
        }
    }

    private void validateAmountField(ValidationResult result, String entity,
                                     String field, String value) {
        if (!isBlank(value)) {
            try {
                new BigDecimal(value.replace(",", "").trim());
            } catch (NumberFormatException e) {
                result.addFinding(Severity.HIGH, "ANM-004",
                        entity + ": " + field + " '" + value + "' is not a valid numeric amount");
            }
        }
    }

    private void validateDecimalField(ValidationResult result, String entity,
                                      String field, String value) {
        if (!isBlank(value)) {
            try {
                new BigDecimal(value.trim());
            } catch (NumberFormatException e) {
                result.addFinding(Severity.HIGH, "ANM-004",
                        entity + ": " + field + " '" + value + "' is not a valid decimal");
            }
        }
    }

    private void validateIntegerField(ValidationResult result, String entity,
                                      String field, String value) {
        if (!isBlank(value)) {
            try {
                Integer.parseInt(value.trim());
            } catch (NumberFormatException e) {
                result.addFinding(Severity.HIGH, "ANM-004",
                        entity + ": " + field + " '" + value + "' is not a valid integer");
            }
        }
    }

    private boolean isValidInteger(String value) {
        try {
            Integer.parseInt(value.trim());
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    private boolean isValidAmount(String value) {
        try {
            new BigDecimal(value.replace(",", "").trim());
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    private static int safeParseInt(String value, int fallback) {
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            return fallback;
        }
    }
}
