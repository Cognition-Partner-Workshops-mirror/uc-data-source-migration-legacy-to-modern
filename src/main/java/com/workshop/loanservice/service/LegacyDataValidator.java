package com.workshop.loanservice.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Set;

/**
 * Validates and safely coerces legacy CDW string fields into proper Java types.
 * Handles the known data quality anomalies from the legacy data warehouse:
 * - Comma-formatted amounts with potential non-numeric characters
 * - Date strings in MM/DD/YYYY with format inconsistencies
 * - Credit scores and integers stored as strings
 * - Status code validation
 * - Payment component reconciliation
 * - Referential integrity warnings
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final DateTimeFormatter ISO_DATE_FORMAT = DateTimeFormatter.ISO_LOCAL_DATE;

    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUS_CODES = Set.of("ACT", "INA");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;
    private static final BigDecimal PAYMENT_RECONCILIATION_TOLERANCE = new BigDecimal("0.02");

    /**
     * Safely parse a legacy amount string (e.g., "285,000" or "1,487.02") into BigDecimal.
     * Strips all non-numeric characters except decimal points and minus signs.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            log.warn("Null/blank amount for field={} record={}, defaulting to ZERO", fieldName, recordId);
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replaceAll("[^\\d.\\-]", "");
            if (cleaned.isEmpty()) {
                log.warn("No numeric content in field={} record={} value='{}', defaulting to ZERO",
                        fieldName, recordId, amount);
                return BigDecimal.ZERO;
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.error("Failed to parse amount field={} record={} value='{}': {}",
                    fieldName, recordId, amount, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy decimal string (e.g., "5.250") into BigDecimal.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("Null/blank decimal for field={} record={}, defaulting to ZERO", fieldName, recordId);
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = value.replaceAll("[^\\d.\\-]", "").trim();
            if (cleaned.isEmpty()) {
                log.warn("No numeric content in decimal field={} record={} value='{}', defaulting to ZERO",
                        fieldName, recordId, value);
                return BigDecimal.ZERO;
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.error("Failed to parse decimal field={} record={} value='{}': {}",
                    fieldName, recordId, value, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy integer string (e.g., "360") into Integer.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            String cleaned = value.replaceAll("[^\\d\\-]", "").trim();
            if (cleaned.isEmpty()) {
                log.warn("No numeric content in integer field={} record={} value='{}'",
                        fieldName, recordId, value);
                return null;
            }
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.error("Failed to parse integer field={} record={} value='{}': {}",
                    fieldName, recordId, value, e.getMessage());
            return null;
        }
    }

    /**
     * Parse and validate a credit score string. Valid range: 300-850.
     */
    public Integer parseCreditScore(String value, String recordId) {
        Integer score = parseInteger(value, "creditScore", recordId);
        if (score == null) {
            return null;
        }
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            log.warn("Credit score out of range [{}-{}] for record={} value={}",
                    CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, recordId, score);
            return null;
        }
        return score;
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format to ISO-8601 (yyyy-MM-dd).
     * Falls back to returning the original string if parsing fails.
     */
    public String parseLegacyDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate parsed = LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return parsed.format(ISO_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            try {
                LocalDate parsed = LocalDate.parse(dateStr.trim(), ISO_DATE_FORMAT);
                return parsed.format(ISO_DATE_FORMAT);
            } catch (DateTimeParseException e2) {
                log.warn("Unparseable date field={} record={} value='{}', returning as-is",
                        fieldName, recordId, dateStr);
                return dateStr;
            }
        }
    }

    /**
     * Validate a loan status code. Returns the code if valid, logs a warning and returns the code as-is if not.
     */
    public String validateLoanStatusCode(String code, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Null/blank loan status code for record={}", recordId);
            return null;
        }
        if (!VALID_LOAN_STATUS_CODES.contains(code)) {
            log.warn("Invalid loan status code='{}' for record={}, valid codes: {}",
                    code, recordId, VALID_LOAN_STATUS_CODES);
        }
        return code;
    }

    /**
     * Validate a payment type code.
     */
    public String validatePaymentTypeCode(String code, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Null/blank payment type code for record={}", recordId);
            return null;
        }
        if (!VALID_PAYMENT_TYPE_CODES.contains(code)) {
            log.warn("Invalid payment type code='{}' for record={}, valid codes: {}",
                    code, recordId, VALID_PAYMENT_TYPE_CODES);
        }
        return code;
    }

    /**
     * Validate a payment status code.
     */
    public String validatePaymentStatusCode(String code, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Null/blank payment status code for record={}", recordId);
            return null;
        }
        if (!VALID_PAYMENT_STATUS_CODES.contains(code)) {
            log.warn("Invalid payment status code='{}' for record={}, valid codes: {}",
                    code, recordId, VALID_PAYMENT_STATUS_CODES);
        }
        return code;
    }

    /**
     * Validate a property type code.
     */
    public String validatePropertyTypeCode(String code, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Null/blank property type code for record={}", recordId);
            return null;
        }
        if (!VALID_PROPERTY_TYPE_CODES.contains(code)) {
            log.warn("Invalid property type code='{}' for record={}, valid codes: {}",
                    code, recordId, VALID_PROPERTY_TYPE_CODES);
        }
        return code;
    }

    /**
     * Validate that a required string field is not null or blank.
     */
    public String validateRequiredField(String value, String fieldName, String recordId, String fallback) {
        if (value == null || value.isBlank()) {
            log.warn("Required field '{}' is null/blank for record={}, using fallback='{}'",
                    fieldName, recordId, fallback);
            return fallback;
        }
        return value;
    }

    /**
     * Validate payment component reconciliation: principal + interest + escrow + late_fee should equal total.
     */
    public boolean validatePaymentReconciliation(BigDecimal total, BigDecimal principal,
                                                  BigDecimal interest, BigDecimal escrow,
                                                  BigDecimal lateFee, String recordId) {
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal difference = total.subtract(componentSum).abs();
        if (difference.compareTo(PAYMENT_RECONCILIATION_TOLERANCE) > 0) {
            log.warn("Payment reconciliation mismatch for record={}: total={} but components sum to {} (diff={})",
                    recordId, total, componentSum, difference);
            return false;
        }
        return true;
    }

    /**
     * Validate that delinquency days are consistent with loan status.
     */
    public void validateDelinquencyConsistency(String delinquencyDaysStr, String statusCode, String recordId) {
        Integer days = parseInteger(delinquencyDaysStr, "delinquencyDays", recordId);
        if (days != null && days > 0 && "ACT".equals(statusCode)) {
            log.warn("Loan {} has {} delinquency days but status is ACT (Active). "
                    + "Consider updating status to DFT or FRB.", recordId, days);
        }
    }

    /**
     * Validate LTV percent against computed value from balance and appraised value.
     */
    public void validateLtvConsistency(String ltvStr, String balanceStr, String appraisedStr, String recordId) {
        BigDecimal ltv = parseDecimal(ltvStr, "ltvPercent", recordId);
        BigDecimal balance = parseAmount(balanceStr, "currentBalance", recordId);
        BigDecimal appraised = parseAmount(appraisedStr, "appraisedValue", recordId);

        if (appraised.compareTo(BigDecimal.ZERO) > 0) {
            BigDecimal computedLtv = balance.divide(appraised, 4, RoundingMode.HALF_UP)
                    .multiply(new BigDecimal("100"))
                    .setScale(1, RoundingMode.HALF_UP);
            BigDecimal diff = ltv.subtract(computedLtv).abs();
            if (diff.compareTo(new BigDecimal("5.0")) > 0) {
                log.warn("LTV mismatch for record={}: stored={} computed={} (diff={})",
                        recordId, ltv, computedLtv, diff);
            }
        }
    }

    /**
     * Validate that denormalized borrower name in loan account matches the master record.
     */
    public void validateDenormalizedBorrowerName(String acctFirstName, String acctLastName,
                                                  String masterFirstName, String masterLastName,
                                                  String recordId) {
        if (masterFirstName != null && acctFirstName != null
                && !masterFirstName.equals(acctFirstName)) {
            log.warn("Borrower first name mismatch for loan={}: account='{}' vs master='{}'",
                    recordId, acctFirstName, masterFirstName);
        }
        if (masterLastName != null && acctLastName != null
                && !masterLastName.equals(acctLastName)) {
            log.warn("Borrower last name mismatch for loan={}: account='{}' vs master='{}'",
                    recordId, acctLastName, masterLastName);
        }
    }
}
