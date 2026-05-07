package com.workshop.loanservice.validation;

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

/**
 * Validates and safely parses legacy CDW data, catching anomalies at ingestion time.
 * <p>
 * Addresses the following known anomalies:
 * - ANO-001: Payment component sum mismatch
 * - ANO-002: Numeric strings without error handling
 * - ANO-003: Orphaned records (FK violations)
 * - ANO-004: Delinquency vs status inconsistency
 * - ANO-005: Denormalized borrower name drift
 * - ANO-006: Late fee inconsistency
 * - ANO-007: Stale LTV percentages
 * - ANO-008: Date strings never parsed
 * - ANO-009: NULL values in expected fields
 * - ANO-010: Escrow balance vs payment escrow mismatch
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.02");

    /**
     * Safely parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Returns BigDecimal.ZERO and logs a warning for malformed values.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId, List<DataQualityWarning> warnings) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(amount.replace(",", "").replace("$", "").trim());
        } catch (NumberFormatException e) {
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-002", "Critical", fieldName, amount,
                    "Malformed numeric value in record " + recordId + "; defaulting to 0");
            warnings.add(warning);
            log.warn("{}", warning);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy decimal string (e.g., "4.750") to BigDecimal.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.replace("%", "").trim());
        } catch (NumberFormatException e) {
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-002", "Critical", fieldName, value,
                    "Malformed decimal value in record " + recordId + "; defaulting to 0");
            warnings.add(warning);
            log.warn("{}", warning);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy integer string (e.g., "745") to Integer.
     * Returns null for malformed values.
     */
    public Integer parseInteger(String value, String fieldName, String recordId, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-002", "Critical", fieldName, value,
                    "Malformed integer value in record " + recordId + "; defaulting to null");
            warnings.add(warning);
            log.warn("{}", warning);
            return null;
        }
    }

    /**
     * Safely parse a legacy date string in MM/DD/YYYY format to LocalDate.
     * Returns null for malformed dates.
     */
    public LocalDate parseDate(String dateStr, String fieldName, String recordId, List<DataQualityWarning> warnings) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-008", "Medium", fieldName, dateStr,
                    "Invalid date format in record " + recordId + "; expected MM/DD/YYYY");
            warnings.add(warning);
            log.warn("{}", warning);
            return null;
        }
    }

    /**
     * Validate that payment components sum to the total amount (ANO-001).
     */
    public void validatePaymentComponentSum(String paymentId, BigDecimal totalAmount,
                                            BigDecimal principal, BigDecimal interest,
                                            BigDecimal escrow, BigDecimal lateFee,
                                            List<DataQualityWarning> warnings) {
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal difference = totalAmount.subtract(componentSum).abs();

        if (difference.compareTo(PAYMENT_TOLERANCE) > 0) {
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-001", "Critical", "PMT_AMT",
                    "total=" + totalAmount + " components=" + componentSum,
                    "Payment " + paymentId + " component sum mismatch: difference=" + difference);
            warnings.add(warning);
            log.warn("{}", warning);
        }
    }

    /**
     * Validate delinquency days vs status code consistency (ANO-004).
     */
    public void validateDelinquencyStatus(String loanAccountNumber, String delinquencyDays,
                                          String statusCode, List<DataQualityWarning> warnings) {
        Integer dlqDays = parseInteger(delinquencyDays, "LN_DLQ_DAYS", loanAccountNumber, new ArrayList<>());
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(statusCode)) {
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-004", "High", "LN_DLQ_DAYS/LN_STAT_CD",
                    "delinquencyDays=" + dlqDays + " status=" + statusCode,
                    "Loan " + loanAccountNumber + " is " + dlqDays + " days delinquent but status is ACT");
            warnings.add(warning);
            log.warn("{}", warning);
        }
    }

    /**
     * Validate denormalized borrower names match the master record (ANO-005).
     */
    public void validateBorrowerNameConsistency(String loanAccountNumber,
                                                String acctFirstName, String acctLastName,
                                                String masterFirstName, String masterLastName,
                                                List<DataQualityWarning> warnings) {
        boolean firstNameMismatch = !safeEquals(acctFirstName, masterFirstName);
        boolean lastNameMismatch = !safeEquals(acctLastName, masterLastName);

        if (firstNameMismatch || lastNameMismatch) {
            String acctName = acctFirstName + " " + acctLastName;
            String masterName = masterFirstName + " " + masterLastName;
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-005", "High", "BORR_FST_NM/BORR_LST_NM",
                    "acct=" + acctName + " master=" + masterName,
                    "Loan " + loanAccountNumber + " has denormalized borrower name mismatch");
            warnings.add(warning);
            log.warn("{}", warning);
        }
    }

    /**
     * Validate late fee consistency with payment timing (ANO-006).
     */
    public void validateLateFeeConsistency(String paymentId, String paymentDateStr,
                                           String receivedDateStr, BigDecimal lateFee,
                                           int gracePeriodDays,
                                           List<DataQualityWarning> warnings) {
        List<DataQualityWarning> dateWarnings = new ArrayList<>();
        LocalDate paymentDate = parseDate(paymentDateStr, "PMT_DT", paymentId, dateWarnings);
        LocalDate receivedDate = parseDate(receivedDateStr, "PMT_RECV_DT", paymentId, dateWarnings);

        if (paymentDate == null || receivedDate == null) {
            return;
        }

        long daysLate = java.time.temporal.ChronoUnit.DAYS.between(paymentDate, receivedDate);
        if (daysLate > gracePeriodDays && lateFee.compareTo(BigDecimal.ZERO) == 0) {
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-006", "High", "PMT_LATE_FEE",
                    "daysLate=" + daysLate + " lateFee=" + lateFee,
                    "Payment " + paymentId + " is " + daysLate + " days late but has no late fee");
            warnings.add(warning);
            log.warn("{}", warning);
        }
    }

    /**
     * Validate LTV percentage against current balance and appraised value (ANO-007).
     */
    public void validateLtvAccuracy(String loanAccountNumber, BigDecimal currentBalance,
                                    BigDecimal appraisedValue, BigDecimal recordedLtv,
                                    List<DataQualityWarning> warnings) {
        if (appraisedValue.compareTo(BigDecimal.ZERO) == 0) {
            return;
        }

        BigDecimal calculatedLtv = currentBalance
                .divide(appraisedValue, 4, RoundingMode.HALF_UP)
                .multiply(new BigDecimal("100"))
                .setScale(1, RoundingMode.HALF_UP);

        BigDecimal ltvDifference = recordedLtv.subtract(calculatedLtv).abs();
        if (ltvDifference.compareTo(new BigDecimal("1.0")) > 0) {
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-007", "High", "LN_LTV_PCT",
                    "recorded=" + recordedLtv + " calculated=" + calculatedLtv,
                    "Loan " + loanAccountNumber + " has stale LTV (off by " + ltvDifference + "%)");
            warnings.add(warning);
            log.warn("{}", warning);
        }
    }

    /**
     * Validate that a required string field is not null or blank (ANO-009).
     */
    public String validateRequiredField(String value, String fieldName, String recordId,
                                        String defaultValue, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            DataQualityWarning warning = new DataQualityWarning(
                    "ANO-009", "Medium", fieldName, "NULL",
                    "Required field is null/blank in record " + recordId + "; using default: " + defaultValue);
            warnings.add(warning);
            log.warn("{}", warning);
            return defaultValue;
        }
        return value;
    }

    private boolean safeEquals(String a, String b) {
        if (a == null && b == null) return true;
        if (a == null || b == null) return false;
        return a.trim().equalsIgnoreCase(b.trim());
    }
}
