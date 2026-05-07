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
import java.util.Set;

@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.01");

    public ValidationResult validateBorrower(LegacyBorrower borrower) {
        ValidationResult result = new ValidationResult();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.CRITICAL, "BORR_FST_NM",
                    "First name is null or blank", id));
        }

        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.CRITICAL, "BORR_LST_NM",
                    "Last name is null or blank", id));
        }

        validateDate(borrower.getDateOfBirth(), "BORR_DOB_DT", id, result);
        validateDate(borrower.getCreatedDate(), "BORR_CRET_DT", id, result);
        validateDate(borrower.getUpdatedDate(), "BORR_UPDT_DT", id, result);

        validateCreditScore(borrower.getCreditScore(), id, result);
        validateNumericAmount(borrower.getAnnualIncome(), "BORR_ANN_INCM", id, result);

        return result;
    }

    public ValidationResult validateLoanAccount(LegacyLoanAccount loan) {
        ValidationResult result = new ValidationResult();
        String id = loan.getLoanAccountNumber();

        if (loan.getBorrowerId() == null || loan.getBorrowerId().isBlank()) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.CRITICAL, "BORR_ID",
                    "Borrower ID is null or blank — orphaned loan record", id));
        }

        if (loan.getProductCode() == null || loan.getProductCode().isBlank()) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, "PROD_CD",
                    "Product code is null or blank", id));
        }

        validateNumericAmount(loan.getOriginalAmount(), "LN_ORIG_AMT", id, result);
        validateNumericAmount(loan.getCurrentBalance(), "LN_CURR_BAL", id, result);
        validateNumericAmount(loan.getMonthlyPayment(), "LN_PMT_AMT", id, result);
        validateNumericAmount(loan.getEscrowBalance(), "LN_ESCROW_BAL", id, result);
        validateNumericAmount(loan.getAppraisedValue(), "PROP_APRS_VAL", id, result);
        validateNumericDecimal(loan.getInterestRate(), "LN_INT_RT", id, result);
        validateNumericDecimal(loan.getLtvPercent(), "LN_LTV_PCT", id, result);
        validateNumericInteger(loan.getTermMonths(), "LN_TERM_MOS", id, result);
        validateNumericInteger(loan.getDelinquencyDays(), "LN_DLQ_DAYS", id, result);

        validateDate(loan.getOriginationDate(), "LN_ORIG_DT", id, result);
        validateDate(loan.getMaturityDate(), "LN_MAT_DT", id, result);
        validateDate(loan.getFirstPaymentDate(), "LN_1ST_PMT_DT", id, result);
        validateDate(loan.getNextPaymentDate(), "LN_NXT_PMT_DT", id, result);

        validateStatusCode(loan.getStatusCode(), "LN_STAT_CD", VALID_LOAN_STATUSES, id, result);
        validatePropertyType(loan.getPropertyType(), id, result);
        validateDelinquencyStatusConsistency(loan, id, result);
        validateSsnNotMatchingPhone(loan, id, result);

        return result;
    }

    public ValidationResult validatePayment(LegacyPayment payment) {
        ValidationResult result = new ValidationResult();
        String id = payment.getPaymentSequenceNumber();

        if (payment.getLoanAccountNumber() == null || payment.getLoanAccountNumber().isBlank()) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.CRITICAL, "LN_ACCT_NBR",
                    "Loan account number is null — orphaned payment", id));
        }

        validateNumericAmount(payment.getTotalAmount(), "PMT_AMT", id, result);
        validateNumericAmount(payment.getPrincipalAmount(), "PMT_PRIN_AMT", id, result);
        validateNumericAmount(payment.getInterestAmount(), "PMT_INT_AMT", id, result);
        validateNumericAmount(payment.getEscrowAmount(), "PMT_ESCROW_AMT", id, result);
        validateNumericAmount(payment.getLateFee(), "PMT_LATE_FEE", id, result);

        validateDate(payment.getPaymentDate(), "PMT_DT", id, result);
        validateDate(payment.getReceivedDate(), "PMT_RECV_DT", id, result);
        validateDate(payment.getProcessedDate(), "PMT_PROC_DT", id, result);

        validateStatusCode(payment.getTypeCode(), "PMT_TYP_CD", VALID_PAYMENT_TYPES, id, result);
        validateStatusCode(payment.getStatusCode(), "PMT_STAT_CD", VALID_PAYMENT_STATUSES, id, result);

        validatePaymentComponentSum(payment, id, result);

        return result;
    }

    public void validateReferentialIntegrity(LegacyLoanAccount loan,
                                             boolean borrowerExists,
                                             boolean productExists,
                                             ValidationResult result) {
        String id = loan.getLoanAccountNumber();
        if (!borrowerExists) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.CRITICAL, "BORR_ID",
                    "References non-existent borrower: " + loan.getBorrowerId(), id));
        }
        if (!productExists) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, "PROD_CD",
                    "References non-existent product: " + loan.getProductCode(), id));
        }
    }

    private void validateDate(String dateStr, String field, String recordId, ValidationResult result) {
        if (dateStr == null || dateStr.isBlank()) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.MEDIUM, field,
                    "Date is null or blank", recordId));
            return;
        }
        try {
            LocalDate.parse(dateStr, LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, field,
                    "Date does not match expected MM/DD/YYYY format: '" + dateStr + "'", recordId));
        }
    }

    private void validateCreditScore(String scoreStr, String recordId, ValidationResult result) {
        if (scoreStr == null || scoreStr.isBlank()) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.MEDIUM, "BORR_CRDT_SCR",
                    "Credit score is null or blank", recordId));
            return;
        }
        try {
            int score = Integer.parseInt(scoreStr.trim());
            if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
                result.addWarning(new DataQualityWarning(
                        DataQualityWarning.Severity.MEDIUM, "BORR_CRDT_SCR",
                        "Credit score out of valid range (300-850): " + score, recordId));
            }
        } catch (NumberFormatException e) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, "BORR_CRDT_SCR",
                    "Credit score is not a valid integer: '" + scoreStr + "'", recordId));
        }
    }

    private void validateNumericAmount(String amount, String field, String recordId, ValidationResult result) {
        if (amount == null || amount.isBlank()) {
            return;
        }
        try {
            new BigDecimal(amount.replace(",", ""));
        } catch (NumberFormatException e) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, field,
                    "Cannot parse as numeric amount: '" + amount + "'", recordId));
        }
    }

    private void validateNumericDecimal(String value, String field, String recordId, ValidationResult result) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, field,
                    "Cannot parse as decimal: '" + value + "'", recordId));
        }
    }

    private void validateNumericInteger(String value, String field, String recordId, ValidationResult result) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, field,
                    "Cannot parse as integer: '" + value + "'", recordId));
        }
    }

    private void validateStatusCode(String code, String field, Set<String> validCodes,
                                     String recordId, ValidationResult result) {
        if (code == null || code.isBlank()) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.MEDIUM, field,
                    "Status code is null or blank", recordId));
            return;
        }
        if (!validCodes.contains(code)) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.MEDIUM, field,
                    "Invalid status code: '" + code + "'. Valid values: " + validCodes, recordId));
        }
    }

    private void validatePropertyType(String code, String recordId, ValidationResult result) {
        if (code == null || code.isBlank()) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.MEDIUM, "PROP_TYP_CD",
                    "Property type is null or blank", recordId));
            return;
        }
        if (!VALID_PROPERTY_TYPES.contains(code)) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.MEDIUM, "PROP_TYP_CD",
                    "Invalid property type code: '" + code + "'", recordId));
        }
    }

    private void validateDelinquencyStatusConsistency(LegacyLoanAccount loan, String recordId,
                                                       ValidationResult result) {
        String dlqStr = loan.getDelinquencyDays();
        String status = loan.getStatusCode();
        if (dlqStr == null || dlqStr.isBlank() || status == null) {
            return;
        }
        try {
            int dlqDays = Integer.parseInt(dlqStr.trim());
            if (dlqDays > 0 && "ACT".equals(status)) {
                result.addWarning(new DataQualityWarning(
                        DataQualityWarning.Severity.HIGH, "LN_DLQ_DAYS/LN_STAT_CD",
                        "Loan has " + dlqDays + " delinquency days but status is ACT (Active). "
                                + "Expected DFT or FRB status.", recordId));
            }
        } catch (NumberFormatException e) {
            // Already caught by validateNumericInteger
        }
    }

    private void validateSsnNotMatchingPhone(LegacyLoanAccount loan, String recordId,
                                              ValidationResult result) {
        // This validates the denormalized SSN_LST4 against known corruption pattern
        // where SSN last-4 was incorrectly populated from phone number last-4
        String ssnLast4 = loan.getBorrowerSsnLast4();
        if (ssnLast4 == null || ssnLast4.isBlank()) {
            return;
        }
        // Flag if the value looks like it could be from a phone number
        // In production, this would cross-reference against BORR_PH_NBR
        if (ssnLast4.matches("\\d{4}")) {
            // Validation is deferred to cross-table check
            log.debug("SSN_LST4 '{}' for record {} flagged for cross-reference validation", ssnLast4, recordId);
        }
    }

    public void validateSsnAgainstPhone(String ssnLast4, String phoneNumber, String recordId,
                                         ValidationResult result) {
        if (ssnLast4 == null || phoneNumber == null) {
            return;
        }
        String phoneLast4 = phoneNumber.replaceAll("[^0-9]", "");
        if (phoneLast4.length() >= 4) {
            phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
            if (ssnLast4.equals(phoneLast4)) {
                result.addWarning(new DataQualityWarning(
                        DataQualityWarning.Severity.CRITICAL, "BORR_SSN_LST4",
                        "SSN last-4 '" + ssnLast4 + "' matches phone number last-4 — "
                                + "likely data corruption from ETL process", recordId));
            }
        }
    }

    private void validatePaymentComponentSum(LegacyPayment payment, String recordId,
                                              ValidationResult result) {
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (total == null || principal == null || interest == null
                || escrow == null || lateFee == null) {
            return;
        }

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal difference = componentSum.subtract(total).abs();

        if (difference.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            result.addWarning(new DataQualityWarning(
                    DataQualityWarning.Severity.CRITICAL,
                    "PMT_AMT",
                    "Payment components (P:" + principal + " + I:" + interest
                            + " + E:" + escrow + " + L:" + lateFee + " = " + componentSum
                            + ") do not sum to total (" + total + "). Difference: "
                            + difference.setScale(2, RoundingMode.HALF_UP),
                    recordId));
        }
    }

    private BigDecimal safeParseAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(amount.replace(",", ""));
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
