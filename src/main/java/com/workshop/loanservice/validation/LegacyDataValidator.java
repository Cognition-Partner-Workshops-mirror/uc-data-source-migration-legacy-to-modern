package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.ValidationResult.Severity;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Validates legacy CDW records at ingestion time, detecting known
 * data quality anomalies before they cause runtime failures.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final Pattern NUMERIC_AMOUNT_PATTERN = Pattern.compile("^-?[\\d,]+(\\.[\\d]+)?$");
    private static final Pattern INTEGER_PATTERN = Pattern.compile("^-?\\d+$");
    private static final Pattern DECIMAL_PATTERN = Pattern.compile("^-?\\d+(\\.\\d+)?$");
    private static final Pattern DATE_PATTERN = Pattern.compile("^\\d{2}/\\d{2}/\\d{4}$");
    private static final Pattern SSN_LAST4_PATTERN = Pattern.compile("^\\d{4}$");

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");

    private static final BigDecimal COMPONENT_SUM_TOLERANCE = new BigDecimal("0.01");

    public ValidationResult validateBorrower(LegacyBorrower borrower) {
        ValidationResult result = new ValidationResult();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            result.addWarning(Severity.HIGH, "BORR_FST_NM",
                    "Required field is null or blank", borrower.getFirstName());
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            result.addWarning(Severity.HIGH, "BORR_LST_NM",
                    "Required field is null or blank", borrower.getLastName());
        }

        validateNumericString(result, "BORR_CRDT_SCR", borrower.getCreditScore(), true);
        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            try {
                int score = Integer.parseInt(borrower.getCreditScore().trim());
                if (score < 300 || score > 850) {
                    result.addWarning(Severity.MEDIUM, "BORR_CRDT_SCR",
                            "Credit score outside valid range (300-850)", borrower.getCreditScore());
                }
            } catch (NumberFormatException ignored) {
                // Already caught by validateNumericString
            }
        }

        validateAmountString(result, "BORR_ANN_INCM", borrower.getAnnualIncome(), false);
        validateDateString(result, "BORR_DOB_DT", borrower.getDateOfBirth());
        validateDateString(result, "BORR_CRET_DT", borrower.getCreatedDate());
        validateDateString(result, "BORR_UPDT_DT", borrower.getUpdatedDate());

        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            result.addWarning(Severity.MEDIUM, "BORR_STAT_CD",
                    "Invalid status code; expected one of " + VALID_BORROWER_STATUSES,
                    borrower.getStatusCode());
        }

        if (result.hasWarnings()) {
            log.warn("Borrower {} has {} validation warnings", borrower.getBorrowerId(),
                    result.getWarnings().size());
        }
        return result;
    }

    public ValidationResult validateLoanAccount(LegacyLoanAccount account, LegacyBorrower borrower) {
        ValidationResult result = new ValidationResult();

        if (account.getBorrowerId() == null || account.getBorrowerId().isBlank()) {
            result.addWarning(Severity.HIGH, "BORR_ID",
                    "Loan account has no borrower reference", null);
        }
        if (account.getProductCode() == null || account.getProductCode().isBlank()) {
            result.addWarning(Severity.HIGH, "PROD_CD",
                    "Loan account has no product code", null);
        }

        // ANM-001: SSN Last-4 vs phone number check
        if (account.getBorrowerSsnLast4() != null && borrower != null && borrower.getPhoneNumber() != null) {
            String phoneLast4 = extractLast4Digits(borrower.getPhoneNumber());
            if (phoneLast4 != null && phoneLast4.equals(account.getBorrowerSsnLast4())) {
                result.addWarning(Severity.CRITICAL, "BORR_SSN_LST4",
                        "SSN last-4 matches phone number suffix — likely ETL column mapping error",
                        account.getBorrowerSsnLast4());
            }
        }
        if (account.getBorrowerSsnLast4() != null && !SSN_LAST4_PATTERN.matcher(account.getBorrowerSsnLast4()).matches()) {
            result.addWarning(Severity.HIGH, "BORR_SSN_LST4",
                    "SSN last-4 is not exactly 4 digits", account.getBorrowerSsnLast4());
        }

        // Denormalized data drift check (ANM-007)
        if (borrower != null) {
            if (account.getBorrowerFirstName() != null && !account.getBorrowerFirstName().equals(borrower.getFirstName())) {
                result.addWarning(Severity.MEDIUM, "BORR_FST_NM",
                        "Denormalized first name differs from master: '" + borrower.getFirstName() + "'",
                        account.getBorrowerFirstName());
            }
            if (account.getBorrowerLastName() != null && !account.getBorrowerLastName().equals(borrower.getLastName())) {
                result.addWarning(Severity.MEDIUM, "BORR_LST_NM",
                        "Denormalized last name differs from master: '" + borrower.getLastName() + "'",
                        account.getBorrowerLastName());
            }
        }

        validateAmountString(result, "LN_ORIG_AMT", account.getOriginalAmount(), true);
        validateAmountString(result, "LN_CURR_BAL", account.getCurrentBalance(), true);
        validateDecimalString(result, "LN_INT_RT", account.getInterestRate(), true);
        validateAmountString(result, "LN_PMT_AMT", account.getMonthlyPayment(), true);
        validateNumericString(result, "LN_TERM_MOS", account.getTermMonths(), true);
        validateNumericString(result, "LN_DLQ_DAYS", account.getDelinquencyDays(), false);
        validateAmountString(result, "LN_ESCROW_BAL", account.getEscrowBalance(), false);
        validateDecimalString(result, "LN_LTV_PCT", account.getLtvPercent(), false);

        validateDateString(result, "LN_ORIG_DT", account.getOriginationDate());
        validateDateString(result, "LN_MAT_DT", account.getMaturityDate());
        validateDateString(result, "LN_1ST_PMT_DT", account.getFirstPaymentDate());
        validateDateString(result, "LN_NXT_PMT_DT", account.getNextPaymentDate());

        // ANM-005: Delinquency vs status inconsistency
        if (account.getDelinquencyDays() != null && account.getStatusCode() != null) {
            try {
                int dlqDays = Integer.parseInt(account.getDelinquencyDays().trim());
                if (dlqDays > 0 && "ACT".equals(account.getStatusCode())) {
                    result.addWarning(Severity.MEDIUM, "LN_STAT_CD",
                            "Loan is " + dlqDays + " days delinquent but status is ACT (Active)",
                            account.getStatusCode());
                }
            } catch (NumberFormatException ignored) {
                // Already caught by validateNumericString
            }
        }

        if (account.getStatusCode() != null && !VALID_LOAN_STATUSES.contains(account.getStatusCode())) {
            result.addWarning(Severity.MEDIUM, "LN_STAT_CD",
                    "Invalid loan status code; expected one of " + VALID_LOAN_STATUSES,
                    account.getStatusCode());
        }
        if (account.getPropertyType() != null && !VALID_PROPERTY_TYPES.contains(account.getPropertyType())) {
            result.addWarning(Severity.LOW, "PROP_TYP_CD",
                    "Unknown property type code", account.getPropertyType());
        }

        if (result.hasWarnings()) {
            log.warn("Loan account {} has {} validation warnings", account.getLoanAccountNumber(),
                    result.getWarnings().size());
        }
        return result;
    }

    public ValidationResult validatePayment(LegacyPayment payment) {
        ValidationResult result = new ValidationResult();

        if (payment.getLoanAccountNumber() == null || payment.getLoanAccountNumber().isBlank()) {
            result.addWarning(Severity.HIGH, "LN_ACCT_NBR",
                    "Payment has no loan account reference", null);
        }

        validateAmountString(result, "PMT_AMT", payment.getTotalAmount(), true);
        validateAmountString(result, "PMT_PRIN_AMT", payment.getPrincipalAmount(), true);
        validateAmountString(result, "PMT_INT_AMT", payment.getInterestAmount(), true);
        validateAmountString(result, "PMT_ESCROW_AMT", payment.getEscrowAmount(), false);
        validateAmountString(result, "PMT_LATE_FEE", payment.getLateFee(), false);

        validateDateString(result, "PMT_DT", payment.getPaymentDate());
        validateDateString(result, "PMT_RECV_DT", payment.getReceivedDate());
        validateDateString(result, "PMT_PROC_DT", payment.getProcessedDate());

        if (payment.getTypeCode() != null && !VALID_PAYMENT_TYPES.contains(payment.getTypeCode())) {
            result.addWarning(Severity.MEDIUM, "PMT_TYP_CD",
                    "Invalid payment type code; expected one of " + VALID_PAYMENT_TYPES,
                    payment.getTypeCode());
        }
        if (payment.getStatusCode() != null && !VALID_PAYMENT_STATUSES.contains(payment.getStatusCode())) {
            result.addWarning(Severity.MEDIUM, "PMT_STAT_CD",
                    "Invalid payment status code; expected one of " + VALID_PAYMENT_STATUSES,
                    payment.getStatusCode());
        }

        // ANM-002: Payment component sum validation
        validatePaymentComponentSum(result, payment);

        if (result.hasWarnings()) {
            log.warn("Payment {} has {} validation warnings", payment.getPaymentSequenceNumber(),
                    result.getWarnings().size());
        }
        return result;
    }

    private void validatePaymentComponentSum(ValidationResult result, LegacyPayment payment) {
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (total == null || principal == null || interest == null) {
            return; // Cannot validate if core amounts are unparseable
        }

        BigDecimal componentSum = principal.add(interest);
        if (escrow != null) {
            componentSum = componentSum.add(escrow);
        }
        if (lateFee != null) {
            componentSum = componentSum.add(lateFee);
        }

        BigDecimal difference = componentSum.subtract(total).abs();
        if (difference.compareTo(COMPONENT_SUM_TOLERANCE) > 0) {
            result.addWarning(Severity.CRITICAL, "PMT_AMT",
                    "Payment components sum to " + componentSum + " but total is " + total
                            + " (difference: " + difference + ")",
                    payment.getTotalAmount());
        }
    }

    // --- Parsing helpers with safe error handling ---

    public BigDecimal safeParseAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        String cleaned = amount.replace(",", "").replace("$", "").trim();
        if (!NUMERIC_AMOUNT_PATTERN.matcher(amount.trim()).matches()
                && !DECIMAL_PATTERN.matcher(cleaned).matches()) {
            return null;
        }
        try {
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public BigDecimal safeParseDecimal(String value) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        String cleaned = value.replace("%", "").trim();
        try {
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public Integer safeParseInteger(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String trimmed = value.trim();
        if (!INTEGER_PATTERN.matcher(trimmed).matches()) {
            return null;
        }
        try {
            return Integer.parseInt(trimmed);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public LocalDate safeParseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        if (!DATE_PATTERN.matcher(dateStr.trim()).matches()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    // --- Private validation methods ---

    private void validateAmountString(ValidationResult result, String field, String value, boolean required) {
        if (value == null || value.isBlank()) {
            if (required) {
                result.addWarning(Severity.HIGH, field, "Required amount field is null or blank", value);
            }
            return;
        }
        if (!NUMERIC_AMOUNT_PATTERN.matcher(value.trim()).matches()) {
            result.addWarning(Severity.HIGH, field,
                    "Value cannot be parsed as a numeric amount", value);
        }
    }

    private void validateDecimalString(ValidationResult result, String field, String value, boolean required) {
        if (value == null || value.isBlank()) {
            if (required) {
                result.addWarning(Severity.HIGH, field, "Required decimal field is null or blank", value);
            }
            return;
        }
        String cleaned = value.replace("%", "").trim();
        if (!DECIMAL_PATTERN.matcher(cleaned).matches()) {
            result.addWarning(Severity.HIGH, field,
                    "Value cannot be parsed as a decimal number", value);
        }
    }

    private void validateNumericString(ValidationResult result, String field, String value, boolean required) {
        if (value == null || value.isBlank()) {
            if (required) {
                result.addWarning(Severity.HIGH, field, "Required integer field is null or blank", value);
            }
            return;
        }
        if (!INTEGER_PATTERN.matcher(value.trim()).matches()) {
            result.addWarning(Severity.HIGH, field,
                    "Value cannot be parsed as an integer", value);
        }
    }

    private void validateDateString(ValidationResult result, String field, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        if (!DATE_PATTERN.matcher(value.trim()).matches()) {
            result.addWarning(Severity.MEDIUM, field,
                    "Date does not match expected MM/DD/YYYY format", value);
            return;
        }
        try {
            LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            result.addWarning(Severity.MEDIUM, field,
                    "Date value is not a valid calendar date", value);
        }
    }

    private String extractLast4Digits(String phoneNumber) {
        if (phoneNumber == null) return null;
        String digitsOnly = phoneNumber.replaceAll("[^\\d]", "");
        if (digitsOnly.length() < 4) return null;
        return digitsOnly.substring(digitsOnly.length() - 4);
    }
}
