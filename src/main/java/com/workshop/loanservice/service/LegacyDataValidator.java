package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.Set;

@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/uuuu")
            .withResolverStyle(ResolverStyle.STRICT);
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.01");

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    private final LegacyBorrowerRepository borrowerRepository;
    private final LegacyLoanProductRepository productRepository;
    private final LegacyLoanAccountRepository loanAccountRepository;

    public LegacyDataValidator(LegacyBorrowerRepository borrowerRepository,
                               LegacyLoanProductRepository productRepository,
                               LegacyLoanAccountRepository loanAccountRepository) {
        this.borrowerRepository = borrowerRepository;
        this.productRepository = productRepository;
        this.loanAccountRepository = loanAccountRepository;
    }

    public ValidationResult validateBorrower(LegacyBorrower borrower) {
        ValidationResult result = new ValidationResult(borrower.getBorrowerId());

        validateRequiredField(result, "BORR_FST_NM", borrower.getFirstName());
        validateRequiredField(result, "BORR_LST_NM", borrower.getLastName());
        validateRequiredField(result, "BORR_STAT_CD", borrower.getStatusCode());

        validateDate(result, "BORR_DOB_DT", borrower.getDateOfBirth());
        validateDate(result, "BORR_CRET_DT", borrower.getCreatedDate());
        validateDate(result, "BORR_UPDT_DT", borrower.getUpdatedDate());

        validateInteger(result, "BORR_CRDT_SCR", borrower.getCreditScore());
        validateAmount(result, "BORR_ANN_INCM", borrower.getAnnualIncome());

        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            Integer score = safeParseInteger(borrower.getCreditScore());
            if (score != null && (score < 300 || score > 850)) {
                result.addWarning("BORR_CRDT_SCR: value " + borrower.getCreditScore()
                        + " outside valid range [300-850]");
            }
        }

        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            result.addWarning("BORR_STAT_CD: unrecognized status code '" + borrower.getStatusCode() + "'");
        }

        logResult(result);
        return result;
    }

    public ValidationResult validateLoanAccount(LegacyLoanAccount acct) {
        ValidationResult result = new ValidationResult(acct.getLoanAccountNumber());

        validateRequiredField(result, "BORR_ID", acct.getBorrowerId());
        validateRequiredField(result, "PROD_CD", acct.getProductCode());
        validateRequiredField(result, "LN_STAT_CD", acct.getStatusCode());

        validateAmount(result, "LN_ORIG_AMT", acct.getOriginalAmount());
        validateAmount(result, "LN_CURR_BAL", acct.getCurrentBalance());
        validateDecimal(result, "LN_INT_RT", acct.getInterestRate());
        validateInteger(result, "LN_TERM_MOS", acct.getTermMonths());
        validateAmount(result, "LN_PMT_AMT", acct.getMonthlyPayment());
        validateAmount(result, "LN_ESCROW_BAL", acct.getEscrowBalance());
        validateDecimal(result, "LN_LTV_PCT", acct.getLtvPercent());
        validateInteger(result, "LN_DLQ_DAYS", acct.getDelinquencyDays());
        validateAmount(result, "PROP_APRS_VAL", acct.getAppraisedValue());

        validateDate(result, "LN_ORIG_DT", acct.getOriginationDate());
        validateDate(result, "LN_MAT_DT", acct.getMaturityDate());
        validateDate(result, "LN_1ST_PMT_DT", acct.getFirstPaymentDate());
        validateDate(result, "LN_NXT_PMT_DT", acct.getNextPaymentDate());
        validateDate(result, "LN_CRET_DT", acct.getCreatedDate());
        validateDate(result, "LN_UPDT_DT", acct.getUpdatedDate());

        if (acct.getStatusCode() != null && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            result.addWarning("LN_STAT_CD: unrecognized status code '" + acct.getStatusCode() + "'");
        }

        if (acct.getPropertyType() != null && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            result.addWarning("PROP_TYP_CD: unrecognized property type '" + acct.getPropertyType() + "'");
        }

        validateDelinquencyStatusConsistency(result, acct);
        validateReferentialIntegrity(result, acct);
        validateDenormalizedBorrowerData(result, acct);

        logResult(result);
        return result;
    }

    public ValidationResult validatePayment(LegacyPayment pmt) {
        ValidationResult result = new ValidationResult(pmt.getPaymentSequenceNumber());

        validateRequiredField(result, "LN_ACCT_NBR", pmt.getLoanAccountNumber());
        validateRequiredField(result, "PMT_AMT", pmt.getTotalAmount());

        validateAmount(result, "PMT_AMT", pmt.getTotalAmount());
        validateAmount(result, "PMT_PRIN_AMT", pmt.getPrincipalAmount());
        validateAmount(result, "PMT_INT_AMT", pmt.getInterestAmount());
        validateAmount(result, "PMT_ESCROW_AMT", pmt.getEscrowAmount());
        validateAmount(result, "PMT_LATE_FEE", pmt.getLateFee());

        validateDate(result, "PMT_DT", pmt.getPaymentDate());
        validateDate(result, "PMT_RECV_DT", pmt.getReceivedDate());
        validateDate(result, "PMT_PROC_DT", pmt.getProcessedDate());
        validateDate(result, "PMT_CRET_DT", pmt.getCreatedDate());
        validateDate(result, "PMT_UPDT_DT", pmt.getUpdatedDate());

        if (pmt.getStatusCode() != null && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            result.addWarning("PMT_STAT_CD: unrecognized status code '" + pmt.getStatusCode() + "'");
        }

        if (pmt.getTypeCode() != null && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            result.addWarning("PMT_TYP_CD: unrecognized payment type '" + pmt.getTypeCode() + "'");
        }

        validatePaymentComponentSum(result, pmt);
        validatePaymentDateOrder(result, pmt);
        validatePaymentReferentialIntegrity(result, pmt);

        logResult(result);
        return result;
    }

    // =========================================================================
    // Field-level validators
    // =========================================================================

    private void validateRequiredField(ValidationResult result, String fieldName, String value) {
        if (value == null || value.isBlank()) {
            result.addError(fieldName + ": required field is null or blank");
        }
    }

    private void validateDate(ValidationResult result, String fieldName, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            LocalDate.parse(value, LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            result.addError(fieldName + ": invalid date format '" + value
                    + "' (expected MM/DD/YYYY)");
        }
    }

    private void validateAmount(ValidationResult result, String fieldName, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            new BigDecimal(value.replace(",", ""));
        } catch (NumberFormatException e) {
            result.addError(fieldName + ": cannot parse amount '" + value + "'");
        }
    }

    private void validateDecimal(ValidationResult result, String fieldName, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            result.addError(fieldName + ": cannot parse decimal '" + value + "'");
        }
    }

    private void validateInteger(ValidationResult result, String fieldName, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            result.addError(fieldName + ": cannot parse integer '" + value + "'");
        }
    }

    // =========================================================================
    // Cross-field validators
    // =========================================================================

    private void validatePaymentComponentSum(ValidationResult result, LegacyPayment pmt) {
        BigDecimal total = safeParseAmount(pmt.getTotalAmount());
        BigDecimal principal = safeParseAmount(pmt.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(pmt.getInterestAmount());
        BigDecimal escrow = safeParseAmount(pmt.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(pmt.getLateFee());

        if (total == null) {
            return;
        }

        BigDecimal componentSum = (principal != null ? principal : BigDecimal.ZERO)
                .add(interest != null ? interest : BigDecimal.ZERO)
                .add(escrow != null ? escrow : BigDecimal.ZERO)
                .add(lateFee != null ? lateFee : BigDecimal.ZERO);

        BigDecimal delta = total.subtract(componentSum).abs();
        if (delta.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            result.addError("PMT_AMT: total (" + pmt.getTotalAmount()
                    + ") does not match component sum (" + componentSum
                    + "), delta=" + delta);
        }
    }

    private void validatePaymentDateOrder(ValidationResult result, LegacyPayment pmt) {
        LocalDate paymentDate = safeParseDate(pmt.getPaymentDate());
        LocalDate receivedDate = safeParseDate(pmt.getReceivedDate());

        if (paymentDate != null && receivedDate != null) {
            long dayGap = java.time.temporal.ChronoUnit.DAYS.between(paymentDate, receivedDate);
            if (dayGap > 15) {
                result.addWarning("PMT_RECV_DT: received date (" + pmt.getReceivedDate()
                        + ") is " + dayGap + " days after payment date (" + pmt.getPaymentDate()
                        + "), exceeds 15-day grace period");
            }
        }
    }

    private void validateDelinquencyStatusConsistency(ValidationResult result, LegacyLoanAccount acct) {
        Integer dlqDays = safeParseInteger(acct.getDelinquencyDays());
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            result.addWarning("LN_DLQ_DAYS/LN_STAT_CD: loan has " + dlqDays
                    + " delinquency days but status is ACT (Active)");
        }
    }

    private void validateReferentialIntegrity(ValidationResult result, LegacyLoanAccount acct) {
        if (acct.getBorrowerId() != null && !acct.getBorrowerId().isBlank()) {
            boolean exists = borrowerRepository.existsById(acct.getBorrowerId());
            if (!exists) {
                result.addError("BORR_ID: references non-existent borrower '"
                        + acct.getBorrowerId() + "'");
            }
        }

        if (acct.getProductCode() != null && !acct.getProductCode().isBlank()) {
            boolean exists = productRepository.existsById(acct.getProductCode());
            if (!exists) {
                result.addError("PROD_CD: references non-existent product '"
                        + acct.getProductCode() + "'");
            }
        }
    }

    private void validateDenormalizedBorrowerData(ValidationResult result, LegacyLoanAccount acct) {
        if (acct.getBorrowerId() == null || acct.getBorrowerId().isBlank()) {
            return;
        }
        borrowerRepository.findById(acct.getBorrowerId()).ifPresent(borrower -> {
            if (acct.getBorrowerFirstName() != null
                    && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
                result.addWarning("BORR_FST_NM: denormalized value '"
                        + acct.getBorrowerFirstName() + "' differs from master '"
                        + borrower.getFirstName() + "'");
            }
            if (acct.getBorrowerLastName() != null
                    && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
                result.addWarning("BORR_LST_NM: denormalized value '"
                        + acct.getBorrowerLastName() + "' differs from master '"
                        + borrower.getLastName() + "'");
            }
        });
    }

    private void validatePaymentReferentialIntegrity(ValidationResult result, LegacyPayment pmt) {
        if (pmt.getLoanAccountNumber() != null && !pmt.getLoanAccountNumber().isBlank()) {
            boolean exists = loanAccountRepository.existsById(pmt.getLoanAccountNumber());
            if (!exists) {
                result.addError("LN_ACCT_NBR: references non-existent loan '"
                        + pmt.getLoanAccountNumber() + "'");
            }
        }
    }

    // =========================================================================
    // Safe parse utilities (return null on failure instead of throwing)
    // =========================================================================

    public BigDecimal safeParseAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(amount.replace(",", ""));
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount: '{}'", amount);
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
            log.warn("Failed to parse decimal: '{}'", value);
            return BigDecimal.ZERO;
        }
    }

    public Integer safeParseInteger(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer: '{}'", value);
            return null;
        }
    }

    public LocalDate safeParseDate(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(value, LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date: '{}'", value);
            return null;
        }
    }

    private void logResult(ValidationResult result) {
        if (result.hasErrors()) {
            log.error("Validation ERRORS for record {}: {}", result.getRecordId(), result.getErrors());
        }
        if (result.hasWarnings()) {
            log.warn("Validation WARNINGS for record {}: {}", result.getRecordId(), result.getWarnings());
        }
    }
}
