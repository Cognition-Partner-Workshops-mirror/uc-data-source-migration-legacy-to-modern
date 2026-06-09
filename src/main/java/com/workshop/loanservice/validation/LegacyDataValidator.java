package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Set;

/**
 * Validates legacy data entities at ingestion time to detect known
 * CDW data quality anomalies before they propagate to API responses.
 *
 * Catches: null required fields, unparseable numerics, invalid dates,
 * status/delinquency inconsistencies, payment component mismatches,
 * and referential integrity gaps.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Valid status codes per entity type
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA", "DEC", "SUS");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB", "DLQ");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");

    // Tolerance for payment component sum comparison (handles floating-point rounding)
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.02");

    /**
     * Validates a legacy borrower record for required fields, numeric parsing,
     * date format, and valid status codes.
     */
    public DataQualityResult validateBorrower(LegacyBorrower borrower) {
        DataQualityResult result = new DataQualityResult("Borrower", borrower.getBorrowerId());

        // Required field checks
        validateRequiredField(result, "firstName", borrower.getFirstName());
        validateRequiredField(result, "lastName", borrower.getLastName());
        validateRequiredField(result, "borrowerId", borrower.getBorrowerId());

        // Numeric parsing validation
        validateNumericField(result, "creditScore", borrower.getCreditScore(), false);
        validateAmountField(result, "annualIncome", borrower.getAnnualIncome());

        // Credit score range validation
        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            Integer score = safeParseInteger(borrower.getCreditScore());
            if (score != null && (score < 300 || score > 850)) {
                result.addError("creditScore",
                        "Credit score " + score + " is outside valid range [300-850]");
            }
        }

        // Date format validation
        validateDateField(result, "dateOfBirth", borrower.getDateOfBirth());
        validateDateField(result, "createdDate", borrower.getCreatedDate());
        validateDateField(result, "updatedDate", borrower.getUpdatedDate());

        // Status code validation
        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            result.addWarning("statusCode",
                    "Unknown borrower status code: '" + borrower.getStatusCode() + "'");
        }

        logResult(result);
        return result;
    }

    /**
     * Validates a legacy loan account for required fields, numeric parsing,
     * date formats, status/delinquency consistency, and referential integrity markers.
     */
    public DataQualityResult validateLoanAccount(LegacyLoanAccount loan) {
        DataQualityResult result = new DataQualityResult("LoanAccount", loan.getLoanAccountNumber());

        // Required field checks
        validateRequiredField(result, "loanAccountNumber", loan.getLoanAccountNumber());
        validateRequiredField(result, "borrowerId", loan.getBorrowerId());
        validateRequiredField(result, "productCode", loan.getProductCode());

        // Numeric parsing validation for amount fields
        validateAmountField(result, "originalAmount", loan.getOriginalAmount());
        validateAmountField(result, "currentBalance", loan.getCurrentBalance());
        validateAmountField(result, "monthlyPayment", loan.getMonthlyPayment());
        validateAmountField(result, "escrowBalance", loan.getEscrowBalance());
        validateAmountField(result, "appraisedValue", loan.getAppraisedValue());
        validateNumericField(result, "interestRate", loan.getInterestRate(), true);
        validateNumericField(result, "termMonths", loan.getTermMonths(), false);
        validateNumericField(result, "delinquencyDays", loan.getDelinquencyDays(), false);
        validateNumericField(result, "ltvPercent", loan.getLtvPercent(), true);

        // Date format validation
        validateDateField(result, "originationDate", loan.getOriginationDate());
        validateDateField(result, "maturityDate", loan.getMaturityDate());
        validateDateField(result, "firstPaymentDate", loan.getFirstPaymentDate());
        validateDateField(result, "nextPaymentDate", loan.getNextPaymentDate());

        // Status code validation
        if (loan.getStatusCode() != null && !VALID_LOAN_STATUSES.contains(loan.getStatusCode())) {
            result.addWarning("statusCode",
                    "Unknown loan status code: '" + loan.getStatusCode() + "'");
        }

        // Cross-field validation: delinquency days vs status code (ANO-003)
        validateDelinquencyStatusConsistency(result, loan);

        logResult(result);
        return result;
    }

    /**
     * Validates a legacy payment record for required fields, numeric parsing,
     * date formats, valid type/status codes, and component sum reconciliation.
     */
    public DataQualityResult validatePayment(LegacyPayment payment) {
        DataQualityResult result = new DataQualityResult("Payment", payment.getPaymentSequenceNumber());

        // Required field checks
        validateRequiredField(result, "paymentSequenceNumber", payment.getPaymentSequenceNumber());
        validateRequiredField(result, "loanAccountNumber", payment.getLoanAccountNumber());
        validateRequiredField(result, "totalAmount", payment.getTotalAmount());

        // Numeric parsing validation
        validateAmountField(result, "totalAmount", payment.getTotalAmount());
        validateAmountField(result, "principalAmount", payment.getPrincipalAmount());
        validateAmountField(result, "interestAmount", payment.getInterestAmount());
        validateAmountField(result, "escrowAmount", payment.getEscrowAmount());
        validateAmountField(result, "lateFee", payment.getLateFee());

        // Date format validation
        validateDateField(result, "paymentDate", payment.getPaymentDate());
        validateDateField(result, "receivedDate", payment.getReceivedDate());
        validateDateField(result, "processedDate", payment.getProcessedDate());

        // Type and status code validation
        if (payment.getTypeCode() != null && !VALID_PAYMENT_TYPES.contains(payment.getTypeCode())) {
            result.addWarning("typeCode",
                    "Unknown payment type code: '" + payment.getTypeCode() + "'");
        }
        if (payment.getStatusCode() != null && !VALID_PAYMENT_STATUSES.contains(payment.getStatusCode())) {
            result.addWarning("statusCode",
                    "Unknown payment status code: '" + payment.getStatusCode() + "'");
        }

        // Cross-field validation: payment components must sum to total (ANO-001)
        validatePaymentComponentSum(result, payment);

        logResult(result);
        return result;
    }

    // =========================================================================
    // Cross-field validation methods
    // =========================================================================

    /**
     * Validates that delinquency days and loan status are consistent.
     * A loan with delinquency_days > 0 should not have status ACT without flagging. (ANO-003)
     */
    private void validateDelinquencyStatusConsistency(DataQualityResult result, LegacyLoanAccount loan) {
        Integer dlqDays = safeParseInteger(loan.getDelinquencyDays());
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(loan.getStatusCode())) {
            result.addError("statusCode/delinquencyDays",
                    "Loan has " + dlqDays + " delinquency days but status is 'ACT' (Active). "
                            + "Expected status DFT, DLQ, or FRB for delinquent loans.");
        }
    }

    /**
     * Validates that payment component amounts sum to the total payment amount. (ANO-001)
     * principal + interest + escrow + lateFee should equal totalAmount within tolerance.
     */
    private void validatePaymentComponentSum(DataQualityResult result, LegacyPayment payment) {
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (total == null) {
            return; // Cannot validate without a total
        }

        BigDecimal componentSum = (principal != null ? principal : BigDecimal.ZERO)
                .add(interest != null ? interest : BigDecimal.ZERO)
                .add(escrow != null ? escrow : BigDecimal.ZERO)
                .add(lateFee != null ? lateFee : BigDecimal.ZERO);

        BigDecimal discrepancy = componentSum.subtract(total).abs();
        if (discrepancy.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            result.addError("paymentComponents",
                    "Payment component sum (" + componentSum.setScale(2, RoundingMode.HALF_UP)
                            + ") does not match total (" + total.setScale(2, RoundingMode.HALF_UP)
                            + "). Discrepancy: $" + discrepancy.setScale(2, RoundingMode.HALF_UP));
        }
    }

    // =========================================================================
    // Field-level validation helpers
    // =========================================================================

    /** Validates that a required field is not null or blank. */
    private void validateRequiredField(DataQualityResult result, String fieldName, String value) {
        if (value == null || value.isBlank()) {
            result.addError(fieldName, "Required field is null or blank");
        }
    }

    /** Validates that a numeric string can be parsed (integer or decimal). */
    private void validateNumericField(DataQualityResult result, String fieldName, String value, boolean allowDecimal) {
        if (value == null || value.isBlank()) {
            return; // Null check handled by required field validation if applicable
        }
        try {
            if (allowDecimal) {
                new BigDecimal(value.trim());
            } else {
                Integer.parseInt(value.trim());
            }
        } catch (NumberFormatException e) {
            result.addWarning(fieldName,
                    "Cannot parse '" + value + "' as " + (allowDecimal ? "decimal" : "integer")
                            + ". Fallback default will be used.");
        }
    }

    /** Validates that an amount string (with commas) can be parsed to BigDecimal. */
    private void validateAmountField(DataQualityResult result, String fieldName, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            new BigDecimal(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            result.addWarning(fieldName,
                    "Cannot parse amount '" + value + "'. Fallback to zero will be used.");
        }
    }

    /** Validates that a date string is in MM/dd/yyyy format and represents a valid date. */
    private void validateDateField(DataQualityResult result, String fieldName, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        SimpleDateFormat sdf = new SimpleDateFormat("MM/dd/yyyy");
        sdf.setLenient(false);
        try {
            sdf.parse(value);
        } catch (ParseException e) {
            result.addWarning(fieldName,
                    "Invalid date format: '" + value + "'. Expected MM/DD/YYYY.");
        }
    }

    // =========================================================================
    // Safe parsing utilities (return null on failure instead of throwing)
    // =========================================================================

    private Integer safeParseInteger(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private BigDecimal safeParseAmount(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return new BigDecimal(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** Log validation results for observability. */
    private void logResult(DataQualityResult result) {
        if (result.hasIssues()) {
            for (DataQualityResult.Issue issue : result.getIssues()) {
                if (issue.severity() == DataQualityResult.Severity.ERROR) {
                    log.warn("DATA_QUALITY_ERROR [{}:{}] {}: {}",
                            result.getEntityType(), result.getRecordId(),
                            issue.field(), issue.message());
                } else {
                    log.info("DATA_QUALITY_WARNING [{}:{}] {}: {}",
                            result.getEntityType(), result.getRecordId(),
                            issue.field(), issue.message());
                }
            }
        }
    }
}
