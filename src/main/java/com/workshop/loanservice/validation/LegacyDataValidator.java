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

@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.01");

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    public ValidationResult validateBorrower(LegacyBorrower borrower) {
        ValidationResult result = new ValidationResult();
        String id = borrower.getBorrowerId();
        String table = "CDW_BORR_MSTR";

        validateRequiredField(result, table, id, "BORR_ID", borrower.getBorrowerId());
        validateRequiredField(result, table, id, "BORR_FST_NM", borrower.getFirstName());
        validateRequiredField(result, table, id, "BORR_LST_NM", borrower.getLastName());

        validateDateFormat(result, table, id, "BORR_DOB_DT", borrower.getDateOfBirth());
        validateDateFormat(result, table, id, "BORR_CRET_DT", borrower.getCreatedDate());
        validateDateFormat(result, table, id, "BORR_UPDT_DT", borrower.getUpdatedDate());

        validateCreditScore(result, table, id, borrower.getCreditScore());
        validateNumericString(result, table, id, "BORR_ANN_INCM", borrower.getAnnualIncome(), true);

        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            result.addWarning(Severity.MEDIUM, table, id, "BORR_STAT_CD",
                    "Unknown borrower status code", borrower.getStatusCode());
        }

        return result;
    }

    public ValidationResult validateLoanAccount(LegacyLoanAccount loan,
                                                 Set<String> validBorrowerIds,
                                                 Set<String> validProductCodes) {
        ValidationResult result = new ValidationResult();
        String id = loan.getLoanAccountNumber();
        String table = "CDW_LN_ACCT";

        validateRequiredField(result, table, id, "LN_ACCT_NBR", loan.getLoanAccountNumber());
        validateRequiredField(result, table, id, "BORR_ID", loan.getBorrowerId());

        if (loan.getBorrowerId() != null && !validBorrowerIds.contains(loan.getBorrowerId())) {
            result.addWarning(Severity.HIGH, table, id, "BORR_ID",
                    "Orphaned record: borrower ID not found in CDW_BORR_MSTR", loan.getBorrowerId());
        }

        if (loan.getProductCode() != null && !validProductCodes.contains(loan.getProductCode())) {
            result.addWarning(Severity.HIGH, table, id, "PROD_CD",
                    "Orphaned record: product code not found in CDW_LN_PROD", loan.getProductCode());
        }

        validateNumericString(result, table, id, "LN_ORIG_AMT", loan.getOriginalAmount(), true);
        validateNumericString(result, table, id, "LN_CURR_BAL", loan.getCurrentBalance(), true);
        validateNumericString(result, table, id, "LN_INT_RT", loan.getInterestRate(), false);
        validateNumericString(result, table, id, "LN_PMT_AMT", loan.getMonthlyPayment(), true);
        validateNumericString(result, table, id, "LN_ESCROW_BAL", loan.getEscrowBalance(), true);
        validateNumericString(result, table, id, "LN_LTV_PCT", loan.getLtvPercent(), false);
        validateNumericString(result, table, id, "PROP_APRS_VAL", loan.getAppraisedValue(), true);

        validateDateFormat(result, table, id, "LN_ORIG_DT", loan.getOriginationDate());
        validateDateFormat(result, table, id, "LN_MAT_DT", loan.getMaturityDate());
        validateDateFormat(result, table, id, "LN_1ST_PMT_DT", loan.getFirstPaymentDate());
        validateDateFormat(result, table, id, "LN_NXT_PMT_DT", loan.getNextPaymentDate());
        validateDateFormat(result, table, id, "LN_CRET_DT", loan.getCreatedDate());
        validateDateFormat(result, table, id, "LN_UPDT_DT", loan.getUpdatedDate());

        if (loan.getStatusCode() != null && !VALID_LOAN_STATUSES.contains(loan.getStatusCode())) {
            result.addWarning(Severity.MEDIUM, table, id, "LN_STAT_CD",
                    "Unknown loan status code", loan.getStatusCode());
        }

        if (loan.getPropertyType() != null && !VALID_PROPERTY_TYPES.contains(loan.getPropertyType())) {
            result.addWarning(Severity.MEDIUM, table, id, "PROP_TYP_CD",
                    "Unknown property type code", loan.getPropertyType());
        }

        return result;
    }

    public ValidationResult validateLoanAccountDenormalizedData(LegacyLoanAccount loan,
                                                                 LegacyBorrower borrower) {
        ValidationResult result = new ValidationResult();
        String id = loan.getLoanAccountNumber();
        String table = "CDW_LN_ACCT";

        if (borrower == null) {
            return result;
        }

        if (loan.getBorrowerFirstName() != null && !loan.getBorrowerFirstName().equals(borrower.getFirstName())) {
            result.addWarning(Severity.MEDIUM, table, id, "BORR_FST_NM",
                    "Denormalized first name differs from master: master='" + borrower.getFirstName() + "'",
                    loan.getBorrowerFirstName());
        }

        if (loan.getBorrowerLastName() != null && !loan.getBorrowerLastName().equals(borrower.getLastName())) {
            result.addWarning(Severity.MEDIUM, table, id, "BORR_LST_NM",
                    "Denormalized last name differs from master: master='" + borrower.getLastName() + "'",
                    loan.getBorrowerLastName());
        }

        if (loan.getBorrowerSsnLast4() != null && borrower.getPhoneNumber() != null) {
            String phoneLast4 = borrower.getPhoneNumber().replaceAll("[^0-9]", "");
            if (phoneLast4.length() >= 4) {
                phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
                if (loan.getBorrowerSsnLast4().equals(phoneLast4)) {
                    result.addWarning(Severity.HIGH, table, id, "BORR_SSN_LST4",
                            "SSN last-4 matches phone number last-4 digits, indicating possible data corruption",
                            loan.getBorrowerSsnLast4());
                }
            }
        }

        return result;
    }

    public ValidationResult validatePayment(LegacyPayment payment, Set<String> validLoanAccountNumbers) {
        ValidationResult result = new ValidationResult();
        String id = payment.getPaymentSequenceNumber();
        String table = "CDW_PMT_HIST";

        validateRequiredField(result, table, id, "PMT_SEQ_NBR", payment.getPaymentSequenceNumber());
        validateRequiredField(result, table, id, "LN_ACCT_NBR", payment.getLoanAccountNumber());

        if (payment.getLoanAccountNumber() != null
                && !validLoanAccountNumbers.contains(payment.getLoanAccountNumber())) {
            result.addWarning(Severity.HIGH, table, id, "LN_ACCT_NBR",
                    "Orphaned record: loan account number not found in CDW_LN_ACCT",
                    payment.getLoanAccountNumber());
        }

        validateNumericString(result, table, id, "PMT_AMT", payment.getTotalAmount(), true);
        validateNumericString(result, table, id, "PMT_PRIN_AMT", payment.getPrincipalAmount(), true);
        validateNumericString(result, table, id, "PMT_INT_AMT", payment.getInterestAmount(), true);
        validateNumericString(result, table, id, "PMT_ESCROW_AMT", payment.getEscrowAmount(), true);
        validateNumericString(result, table, id, "PMT_LATE_FEE", payment.getLateFee(), true);

        validateDateFormat(result, table, id, "PMT_DT", payment.getPaymentDate());
        validateDateFormat(result, table, id, "PMT_RECV_DT", payment.getReceivedDate());
        validateDateFormat(result, table, id, "PMT_PROC_DT", payment.getProcessedDate());
        validateDateFormat(result, table, id, "PMT_CRET_DT", payment.getCreatedDate());
        validateDateFormat(result, table, id, "PMT_UPDT_DT", payment.getUpdatedDate());

        if (payment.getTypeCode() != null && !VALID_PAYMENT_TYPES.contains(payment.getTypeCode())) {
            result.addWarning(Severity.MEDIUM, table, id, "PMT_TYP_CD",
                    "Unknown payment type code", payment.getTypeCode());
        }

        if (payment.getStatusCode() != null && !VALID_PAYMENT_STATUSES.contains(payment.getStatusCode())) {
            result.addWarning(Severity.MEDIUM, table, id, "PMT_STAT_CD",
                    "Unknown payment status code", payment.getStatusCode());
        }

        validatePaymentComponents(result, id, payment);

        return result;
    }

    // --- Reusable safe-parsing methods ---

    public BigDecimal safeParseAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal safeParseDecimal(String value) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}': {}", value, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    public Integer safeParseInteger(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    public LocalDate safeParseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    public String safeFormatDate(String legacyDate) {
        LocalDate parsed = safeParseLegacyDate(legacyDate);
        return parsed != null ? parsed.toString() : legacyDate;
    }

    // --- Private validation helpers ---

    private void validateRequiredField(ValidationResult result, String table, String recordId,
                                       String field, String value) {
        if (value == null || value.isBlank()) {
            result.addWarning(Severity.CRITICAL, table, recordId, field,
                    "Required field is null or blank", value);
        }
    }

    private void validateDateFormat(ValidationResult result, String table, String recordId,
                                     String field, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            result.addWarning(Severity.HIGH, table, recordId, field,
                    "Invalid date format (expected MM/DD/YYYY): " + e.getMessage(), value);
        }
    }

    private void validateNumericString(ValidationResult result, String table, String recordId,
                                        String field, String value, boolean hasCommas) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            String cleaned = hasCommas ? value.replace(",", "").replace("$", "").trim() : value.trim();
            new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            result.addWarning(Severity.CRITICAL, table, recordId, field,
                    "Non-numeric value in numeric field", value);
        }
    }

    private void validateCreditScore(ValidationResult result, String table, String recordId,
                                      String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            int score = Integer.parseInt(value.trim());
            if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
                result.addWarning(Severity.MEDIUM, table, recordId, "BORR_CRDT_SCR",
                        "Credit score outside valid FICO range (" + CREDIT_SCORE_MIN + "-" + CREDIT_SCORE_MAX + ")",
                        value);
            }
        } catch (NumberFormatException e) {
            result.addWarning(Severity.CRITICAL, table, recordId, "BORR_CRDT_SCR",
                    "Non-numeric credit score", value);
        }
    }

    private void validatePaymentComponents(ValidationResult result, String recordId,
                                            LegacyPayment payment) {
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal discrepancy = componentSum.subtract(total).abs();

        if (discrepancy.compareTo(PAYMENT_TOLERANCE) > 0) {
            result.addWarning(Severity.CRITICAL, "CDW_PMT_HIST", recordId, "PMT_AMT",
                    "Payment component mismatch: total=" + total + " but components sum to "
                            + componentSum + " (discrepancy=" + discrepancy + ")",
                    payment.getTotalAmount());
        }
    }
}
