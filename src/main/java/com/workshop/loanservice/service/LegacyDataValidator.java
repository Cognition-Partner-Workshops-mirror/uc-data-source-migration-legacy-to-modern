package com.workshop.loanservice.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.List;

/**
 * Validates and coerces legacy CDW data at ingestion time.
 * Catches anomalies identified in docs/DATA_ANOMALY_REPORT.md.
 *
 * Added as part of data quality anomaly detection:
 * - Parses all-VARCHAR legacy fields into proper Java types
 * - Validates value ranges (credit scores, interest rates, LTV)
 * - Checks status codes against known allowlists
 * - Verifies referential integrity (FK lookups)
 * - Detects payment reconciliation mismatches
 * - Flags denormalized name drift between loan and borrower tables
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Legacy CDW stores all dates as MM/dd/yyyy VARCHAR strings
    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    // Allowlists for legacy status code abbreviations (see column_mappings.md)
    private static final List<String> VALID_LOAN_STATUSES =
            List.of("ACT", "CLO", "DFT", "FRB");

    private static final List<String> VALID_BORROWER_STATUSES =
            List.of("ACT", "INA");

    private static final List<String> VALID_PAYMENT_STATUSES =
            List.of("PST", "REV", "NSF", "PND");

    private static final List<String> VALID_PAYMENT_TYPES =
            List.of("REG", "EXT", "PRT", "PRE");

    private static final List<String> VALID_PROPERTY_TYPES =
            List.of("SFR", "CND", "MFR", "TWN");

    // Business rule bounds for numeric field validation
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    private static final BigDecimal INTEREST_RATE_MAX = new BigDecimal("30.0");
    private static final BigDecimal LTV_MAX = new BigDecimal("200.0");
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.02");

    /**
     * Parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Strips all non-numeric characters except decimal point and minus sign.
     * Returns null on failure instead of masking missing data as zero.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            log.warn("Missing amount field [{}] on record [{}], returning null", fieldName, recordId);
            return null;
        }
        // Strip all non-numeric chars (commas, dollar signs, spaces) except decimal point and minus
        String sanitized = amount.replaceAll("[^\\d.\\-]", "");
        if (!sanitized.equals(amount.replace(",", ""))) {
            log.warn("Amount field [{}] on record [{}] contained unexpected characters: '{}' -> '{}'",
                    fieldName, recordId, amount, sanitized);
        }
        try {
            BigDecimal result = new BigDecimal(sanitized);
            if (result.compareTo(BigDecimal.ZERO) < 0) {
                log.warn("Negative amount in field [{}] on record [{}]: {}", fieldName, recordId, result);
            }
            return result;
        } catch (NumberFormatException e) {
            log.error("Unparseable amount field [{}] on record [{}]: '{}'", fieldName, recordId, amount);
            return null;
        }
    }

    /**
     * Parse a legacy amount string, returning a provided default for null/unparseable values.
     */
    public BigDecimal parseAmountWithDefault(String amount, String fieldName,
                                             String recordId, BigDecimal defaultValue) {
        BigDecimal result = parseAmount(amount, fieldName, recordId);
        return result != null ? result : defaultValue;
    }

    /**
     * Parse a legacy decimal string (e.g., "4.750") to BigDecimal.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("Missing decimal field [{}] on record [{}]", fieldName, recordId);
            return null;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.error("Unparseable decimal field [{}] on record [{}]: '{}'", fieldName, recordId, value);
            return null;
        }
    }

    /**
     * Parse a legacy integer string (e.g., "360") to Integer.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("Missing integer field [{}] on record [{}]", fieldName, recordId);
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.error("Unparseable integer field [{}] on record [{}]: '{}'", fieldName, recordId, value);
            return null;
        }
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format to LocalDate.
     */
    public LocalDate parseDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            log.warn("Missing date field [{}] on record [{}]", fieldName, recordId);
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.error("Unparseable date field [{}] on record [{}]: '{}' (expected MM/dd/yyyy)",
                    fieldName, recordId, dateStr);
            return null;
        }
    }

    /**
     * Validate credit score is within the 300-850 range.
     */
    public Integer validateCreditScore(String creditScoreStr, String recordId) {
        Integer score = parseInteger(creditScoreStr, "creditScore", recordId);
        if (score == null) {
            return null;
        }
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            log.warn("Credit score out of range [{}-{}] on record [{}]: {}",
                    CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, recordId, score);
            return null;
        }
        return score;
    }

    /**
     * Validate interest rate is within 0-30%.
     */
    public BigDecimal validateInterestRate(String rateStr, String recordId) {
        BigDecimal rate = parseDecimal(rateStr, "interestRate", recordId);
        if (rate == null) {
            return null;
        }
        if (rate.compareTo(BigDecimal.ZERO) < 0 || rate.compareTo(INTEREST_RATE_MAX) > 0) {
            log.warn("Interest rate out of range [0-{}] on record [{}]: {}",
                    INTEREST_RATE_MAX, recordId, rate);
        }
        return rate;
    }

    /**
     * Validate LTV percent is within 0-200%.
     */
    public BigDecimal validateLtvPercent(String ltvStr, String recordId) {
        BigDecimal ltv = parseDecimal(ltvStr, "ltvPercent", recordId);
        if (ltv == null) {
            return null;
        }
        if (ltv.compareTo(BigDecimal.ZERO) < 0 || ltv.compareTo(LTV_MAX) > 0) {
            log.warn("LTV percent out of valid range [0-{}] on record [{}]: {}",
                    LTV_MAX, recordId, ltv);
        }
        if (ltv.compareTo(new BigDecimal("100")) > 0) {
            log.warn("LTV percent > 100% (negative equity) on record [{}]: {}", recordId, ltv);
        }
        return ltv;
    }

    /**
     * Validate a status code against an allowlist.
     */
    public String validateStatusCode(String code, List<String> validCodes,
                                     String fieldName, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Missing status code field [{}] on record [{}]", fieldName, recordId);
            return null;
        }
        String trimmed = code.trim();
        if (!validCodes.contains(trimmed)) {
            log.warn("Unknown status code in field [{}] on record [{}]: '{}' (valid: {})",
                    fieldName, recordId, trimmed, validCodes);
        }
        return trimmed;
    }

    public String validateLoanStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_LOAN_STATUSES, "loanStatus", recordId);
    }

    public String validateBorrowerStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_BORROWER_STATUSES, "borrowerStatus", recordId);
    }

    public String validatePaymentStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_PAYMENT_STATUSES, "paymentStatus", recordId);
    }

    public String validatePaymentType(String code, String recordId) {
        return validateStatusCode(code, VALID_PAYMENT_TYPES, "paymentType", recordId);
    }

    public String validatePropertyType(String code, String recordId) {
        return validateStatusCode(code, VALID_PROPERTY_TYPES, "propertyType", recordId);
    }

    /**
     * Validate that payment components sum to total within tolerance.
     * Returns true if reconciled, false if mismatch.
     */
    public boolean validatePaymentReconciliation(String paymentId,
                                                  BigDecimal total,
                                                  BigDecimal principal,
                                                  BigDecimal interest,
                                                  BigDecimal escrow,
                                                  BigDecimal lateFee) {
        if (total == null || principal == null || interest == null) {
            log.warn("Cannot reconcile payment [{}]: missing total, principal, or interest", paymentId);
            return false;
        }
        // Treat null optional components as zero for reconciliation
        BigDecimal safeEscrow = escrow != null ? escrow : BigDecimal.ZERO;
        BigDecimal safeLateFee = lateFee != null ? lateFee : BigDecimal.ZERO;

        // Sum all components: principal + interest + escrow + late fee
        BigDecimal componentSum = principal.add(interest).add(safeEscrow).add(safeLateFee);
        BigDecimal difference = total.subtract(componentSum).abs();

        if (difference.compareTo(PAYMENT_TOLERANCE) > 0) {
            log.warn("Payment reconciliation FAILED for [{}]: total={}, componentSum={}, delta={}",
                    paymentId, total, componentSum, difference);
            return false;
        }
        return true;
    }

    /**
     * Validate delinquency days is a non-negative integer within a reasonable range.
     */
    public Integer validateDelinquencyDays(String daysStr, String recordId) {
        Integer days = parseInteger(daysStr, "delinquencyDays", recordId);
        if (days == null) {
            return 0;
        }
        if (days < 0 || days > 999) {
            log.warn("Delinquency days out of range [0-999] on record [{}]: {}", recordId, days);
            return 0;
        }
        return days;
    }

    /**
     * Validate a required string field is not null or blank.
     */
    public String validateRequired(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.error("Required field [{}] is null/blank on record [{}]", fieldName, recordId);
            return null;
        }
        return value.trim();
    }

    /**
     * Check referential integrity: verify that a foreign key value exists in a set of valid keys.
     * Returns true if valid, false if orphaned.
     */
    public boolean validateForeignKey(String fkValue, java.util.Set<String> validKeys,
                                      String fkField, String recordId) {
        if (fkValue == null || fkValue.isBlank()) {
            log.error("Missing foreign key [{}] on record [{}]", fkField, recordId);
            return false;
        }
        if (!validKeys.contains(fkValue)) {
            log.error("Orphaned record [{}]: [{}]='{}' not found in parent table",
                    recordId, fkField, fkValue);
            return false;
        }
        return true;
    }

    /**
     * Validate denormalized borrower name in loan account matches the borrower master.
     */
    public void validateDenormalizedName(String loanAccountNumber,
                                         String loanFirstName, String loanLastName,
                                         String masterFirstName, String masterLastName) {
        if (masterFirstName != null && !masterFirstName.equals(loanFirstName)) {
            log.warn("Denormalized first name mismatch on loan [{}]: loan='{}', master='{}'",
                    loanAccountNumber, loanFirstName, masterFirstName);
        }
        if (masterLastName != null && !masterLastName.equals(loanLastName)) {
            log.warn("Denormalized last name mismatch on loan [{}]: loan='{}', master='{}'",
                    loanAccountNumber, loanLastName, masterLastName);
        }
    }
}
