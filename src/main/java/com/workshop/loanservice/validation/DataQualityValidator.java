package com.workshop.loanservice.validation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;

/**
 * Validates and coerces legacy CDW data at ingestion time.
 * Catches anomalies identified in DATA_ANOMALY_REPORT.md:
 *   - Comma-formatted numeric strings (ANM-001)
 *   - Inconsistent date formats (ANM-002)
 *   - Orphaned foreign key references (ANM-003)
 *   - Credit score range violations (ANM-004)
 *   - Null values in required fields (ANM-005)
 *   - Interest rate / LTV bounds (ANM-007)
 *   - Invalid status codes (ANM-008)
 *   - Payment component mismatches (ANM-009)
 */
@Component
public class DataQualityValidator {

    private static final Logger log = LoggerFactory.getLogger(DataQualityValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final Set<String> VALID_LOAN_STATUS_CODES =
            Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_BORROWER_STATUS_CODES =
            Set.of("ACT", "INA");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES =
            Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES =
            Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES =
            Set.of("SFR", "CND", "MFR", "TWN");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;
    private static final BigDecimal INTEREST_RATE_MIN = BigDecimal.ZERO;
    private static final BigDecimal INTEREST_RATE_MAX = new BigDecimal("30.0");
    private static final BigDecimal LTV_MIN = BigDecimal.ZERO;
    private static final BigDecimal LTV_MAX = new BigDecimal("200.0");
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.02");

    private final List<ValidationResult> validationResults =
            Collections.synchronizedList(new ArrayList<>());

    /**
     * Parse a legacy amount string (e.g., "285,000" or "$1,487.02") to BigDecimal.
     * Strips commas, dollar signs, and whitespace. Returns null if unparseable.
     */
    public BigDecimal parseAmount(String amount, String fieldName) {
        if (amount == null || amount.isBlank()) {
            record(fieldName, amount, Severity.HIGH,
                    "Null or blank amount — cannot default to zero without business context");
            return null;
        }
        String normalized = amount.replace(",", "").replace("$", "").trim();
        try {
            return new BigDecimal(normalized);
        } catch (NumberFormatException e) {
            record(fieldName, amount, Severity.CRITICAL,
                    "Unparseable amount: '" + amount + "'");
            return null;
        }
    }

    /**
     * Parse a legacy amount string, returning a fallback default when null/unparseable.
     */
    public BigDecimal parseAmountWithDefault(String amount, String fieldName, BigDecimal defaultValue) {
        BigDecimal result = parseAmount(amount, fieldName);
        return result != null ? result : defaultValue;
    }

    /**
     * Parse a legacy decimal string (interest rate, LTV, etc.).
     * Strips commas and whitespace. Returns null if unparseable.
     */
    public BigDecimal parseDecimal(String value, String fieldName) {
        if (value == null || value.isBlank()) {
            record(fieldName, value, Severity.HIGH,
                    "Null or blank decimal value");
            return null;
        }
        String normalized = value.replace(",", "").trim();
        try {
            return new BigDecimal(normalized);
        } catch (NumberFormatException e) {
            record(fieldName, value, Severity.CRITICAL,
                    "Unparseable decimal: '" + value + "'");
            return null;
        }
    }

    /**
     * Parse a legacy integer string (credit score, term months, delinquency days).
     * Returns null if unparseable.
     */
    public Integer parseInteger(String value, String fieldName) {
        if (value == null || value.isBlank()) {
            record(fieldName, value, Severity.MEDIUM,
                    "Null or blank integer value");
            return null;
        }
        String normalized = value.replace(",", "").trim();
        try {
            return Integer.parseInt(normalized);
        } catch (NumberFormatException e) {
            record(fieldName, value, Severity.HIGH,
                    "Unparseable integer: '" + value + "'");
            return null;
        }
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format to LocalDate.
     * Returns null if unparseable.
     */
    public LocalDate parseDate(String dateStr, String fieldName) {
        if (dateStr == null || dateStr.isBlank()) {
            record(fieldName, dateStr, Severity.HIGH,
                    "Null or blank date");
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            record(fieldName, dateStr, Severity.CRITICAL,
                    "Unparseable date (expected MM/dd/yyyy): '" + dateStr + "'");
            return null;
        }
    }

    /**
     * Validate a credit score: must be parseable and within 300-850.
     */
    public Integer validateCreditScore(String value) {
        Integer score = parseInteger(value, "creditScore");
        if (score == null) {
            return null;
        }
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            record("creditScore", value, Severity.HIGH,
                    "Credit score " + score + " outside valid range [" +
                            CREDIT_SCORE_MIN + "-" + CREDIT_SCORE_MAX + "]");
            return null;
        }
        return score;
    }

    /**
     * Validate an interest rate: must be within 0-30%.
     */
    public BigDecimal validateInterestRate(String value) {
        BigDecimal rate = parseDecimal(value, "interestRate");
        if (rate == null) {
            return null;
        }
        if (rate.compareTo(INTEREST_RATE_MIN) < 0 || rate.compareTo(INTEREST_RATE_MAX) > 0) {
            record("interestRate", value, Severity.HIGH,
                    "Interest rate " + rate + " outside valid range [0-30%]");
            return null;
        }
        return rate;
    }

    /**
     * Validate LTV percent: must be within 0-200%.
     */
    public BigDecimal validateLtvPercent(String value) {
        BigDecimal ltv = parseDecimal(value, "ltvPercent");
        if (ltv == null) {
            return null;
        }
        if (ltv.compareTo(LTV_MIN) < 0 || ltv.compareTo(LTV_MAX) > 0) {
            record("ltvPercent", value, Severity.MEDIUM,
                    "LTV " + ltv + "% outside valid range [0-200%]");
            return null;
        }
        return ltv;
    }

    /**
     * Validate a status code against allowed values (case-insensitive).
     * Returns the normalized (uppercase) code, or "UNKNOWN" for invalid codes.
     */
    public String validateStatusCode(String code, Set<String> validCodes, String fieldName) {
        if (code == null || code.isBlank()) {
            record(fieldName, code, Severity.MEDIUM,
                    "Null or blank status code");
            return "UNKNOWN";
        }
        String normalized = code.trim().toUpperCase();
        if (!validCodes.contains(normalized)) {
            record(fieldName, code, Severity.MEDIUM,
                    "Unrecognized status code: '" + code + "'. Valid: " + validCodes);
            return "UNKNOWN";
        }
        return normalized;
    }

    public String validateLoanStatusCode(String code) {
        return validateStatusCode(code, VALID_LOAN_STATUS_CODES, "loanStatusCode");
    }

    public String validateBorrowerStatusCode(String code) {
        return validateStatusCode(code, VALID_BORROWER_STATUS_CODES, "borrowerStatusCode");
    }

    public String validatePaymentStatusCode(String code) {
        return validateStatusCode(code, VALID_PAYMENT_STATUS_CODES, "paymentStatusCode");
    }

    public String validatePaymentTypeCode(String code) {
        return validateStatusCode(code, VALID_PAYMENT_TYPE_CODES, "paymentTypeCode");
    }

    public String validatePropertyTypeCode(String code) {
        return validateStatusCode(code, VALID_PROPERTY_TYPE_CODES, "propertyTypeCode");
    }

    /**
     * Validate that payment components sum to the total (within tolerance).
     * Returns true if valid, false if mismatched.
     */
    public boolean validatePaymentComponents(BigDecimal total,
                                             BigDecimal principal,
                                             BigDecimal interest,
                                             BigDecimal escrow,
                                             BigDecimal lateFee,
                                             String paymentId) {
        if (total == null || principal == null || interest == null) {
            return true; // can't validate if components are missing
        }
        BigDecimal esc = escrow != null ? escrow : BigDecimal.ZERO;
        BigDecimal fee = lateFee != null ? lateFee : BigDecimal.ZERO;
        BigDecimal componentSum = principal.add(interest).add(esc).add(fee);
        BigDecimal difference = total.subtract(componentSum).abs();
        if (difference.compareTo(PAYMENT_TOLERANCE) > 0) {
            record("paymentComponents", paymentId, Severity.MEDIUM,
                    "Payment " + paymentId + " component mismatch: total=" + total +
                            ", components sum=" + componentSum + ", diff=" + difference);
            return false;
        }
        return true;
    }

    /**
     * Validate a required string field is not null or blank.
     */
    public String validateRequired(String value, String fieldName) {
        if (value == null || value.isBlank()) {
            record(fieldName, value, Severity.HIGH,
                    "Required field '" + fieldName + "' is null or blank");
            return null;
        }
        return value.trim();
    }

    /**
     * Validate a required string, returning a fallback if null/blank.
     */
    public String validateRequiredWithDefault(String value, String fieldName, String defaultValue) {
        String result = validateRequired(value, fieldName);
        return result != null ? result : defaultValue;
    }

    /**
     * Safe string concatenation that handles nulls.
     */
    public String safeConcat(String separator, String... parts) {
        StringBuilder sb = new StringBuilder();
        boolean first = true;
        for (String part : parts) {
            if (part != null && !part.isBlank()) {
                if (!first) {
                    sb.append(separator);
                }
                sb.append(part.trim());
                first = false;
            }
        }
        return sb.toString();
    }

    /**
     * Validate that a foreign key reference exists in a set of known IDs.
     */
    public boolean validateForeignKey(String fkValue, Set<String> validIds,
                                      String fieldName, String referencedTable) {
        if (fkValue == null || fkValue.isBlank()) {
            record(fieldName, fkValue, Severity.CRITICAL,
                    "Null foreign key reference to " + referencedTable);
            return false;
        }
        if (!validIds.contains(fkValue)) {
            record(fieldName, fkValue, Severity.CRITICAL,
                    "Orphaned reference: '" + fkValue + "' not found in " + referencedTable);
            return false;
        }
        return true;
    }

    /**
     * Validate payment date ordering (received should not be before payment date is an anomaly marker).
     */
    public boolean validatePaymentDateOrder(LocalDate paymentDate, LocalDate receivedDate,
                                            String paymentId) {
        if (paymentDate == null || receivedDate == null) {
            return true;
        }
        if (receivedDate.isAfter(paymentDate.plusDays(15))) {
            record("paymentDateOrder", paymentId, Severity.MEDIUM,
                    "Payment " + paymentId + " received significantly late: due=" +
                            paymentDate + ", received=" + receivedDate);
            return false;
        }
        return true;
    }

    private void record(String field, String value, Severity severity, String message) {
        ValidationResult result = new ValidationResult(field, value, severity, message);
        validationResults.add(result);
        switch (severity) {
            case CRITICAL -> log.error("DATA QUALITY [{}]: {}", field, message);
            case HIGH -> log.warn("DATA QUALITY [{}]: {}", field, message);
            case MEDIUM -> log.info("DATA QUALITY [{}]: {}", field, message);
            case LOW -> log.debug("DATA QUALITY [{}]: {}", field, message);
        }
    }

    public List<ValidationResult> getValidationResults() {
        return Collections.unmodifiableList(new ArrayList<>(validationResults));
    }

    public void clearResults() {
        validationResults.clear();
    }

    public long countBySeverity(Severity severity) {
        return validationResults.stream()
                .filter(r -> r.severity() == severity)
                .count();
    }

    public boolean hasErrors() {
        return validationResults.stream()
                .anyMatch(r -> r.severity() == Severity.CRITICAL || r.severity() == Severity.HIGH);
    }

    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    public record ValidationResult(String field, String value, Severity severity, String message) {
    }
}
