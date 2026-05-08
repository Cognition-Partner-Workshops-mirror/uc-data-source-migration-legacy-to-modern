package com.workshop.loanservice.validation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Set;

/**
 * Validates and safely coerces legacy CDW data during ingestion.
 *
 * The legacy data warehouse stores all values as VARCHAR with known quality issues:
 * - Numeric amounts contain embedded commas and may include currency symbols
 * - Dates are MM/DD/YYYY strings that may be malformed
 * - Status codes may not match the expected value set
 * - Cross-field consistency (e.g., payment component sums) is not enforced
 *
 * This validator catches anomalies at ingestion time, logs them for observability,
 * and returns safe fallback defaults to prevent runtime crashes.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Expected date format for all legacy date fields
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    // Valid status code sets for cross-field validation
    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_BORROWER_STATUS_CODES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_PRODUCT_TYPE_CODES = Set.of("FXD", "ARM", "FHA", "VA");
    private static final Set<String> VALID_RATE_TYPE_CODES = Set.of("FIXED", "VARIABLE");

    // Tolerance for payment component sum validation (accounting for rounding)
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.01");

    // Credit score valid range (FICO)
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    // Interest rate valid range (percentage)
    private static final BigDecimal INTEREST_RATE_MIN = BigDecimal.ZERO;
    private static final BigDecimal INTEREST_RATE_MAX = new BigDecimal("100");

    // =========================================================================
    // SAFE NUMERIC PARSING — wraps parsing in try-catch with fallback defaults
    // =========================================================================

    /**
     * Safely parse a legacy amount string (e.g., "285,000" or "1,487.02") into BigDecimal.
     * Strips commas, dollar signs, percent signs, and whitespace before parsing.
     * Returns BigDecimal.ZERO on failure and logs the error with context.
     */
    public BigDecimal safeParseAmount(String rawValue, String fieldName, String recordId) {
        if (rawValue == null || rawValue.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            // Strip common non-numeric characters that appear in legacy data
            String cleaned = sanitizeNumericString(rawValue);
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount field '{}' with value '{}' for record '{}'. Falling back to ZERO.",
                    fieldName, rawValue, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy decimal string (e.g., "4.750") into BigDecimal.
     * Returns BigDecimal.ZERO on failure.
     */
    public BigDecimal safeParseDecimal(String rawValue, String fieldName, String recordId) {
        if (rawValue == null || rawValue.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = sanitizeNumericString(rawValue);
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal field '{}' with value '{}' for record '{}'. Falling back to ZERO.",
                    fieldName, rawValue, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy integer string (e.g., "360", "745") into Integer.
     * Returns null on failure (preserving the distinction between 0 and unknown).
     */
    public Integer safeParseInteger(String rawValue, String fieldName, String recordId) {
        if (rawValue == null || rawValue.isBlank()) {
            return null;
        }
        try {
            String cleaned = sanitizeNumericString(rawValue);
            // Handle decimals stored in integer fields (e.g., "360.0")
            if (cleaned.contains(".")) {
                cleaned = cleaned.substring(0, cleaned.indexOf('.'));
            }
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer field '{}' with value '{}' for record '{}'. Falling back to null.",
                    fieldName, rawValue, recordId);
            return null;
        }
    }

    // =========================================================================
    // DATE VALIDATION — parses MM/DD/YYYY strings into LocalDate
    // =========================================================================

    /**
     * Parse a legacy date string in MM/DD/YYYY format into LocalDate.
     * Returns null if the date is null, blank, or unparseable.
     */
    public LocalDate safeParseLegacyDate(String rawValue, String fieldName, String recordId) {
        if (rawValue == null || rawValue.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(rawValue.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date field '{}' with value '{}' for record '{}'. Expected MM/DD/YYYY format.",
                    fieldName, rawValue, recordId);
            return null;
        }
    }

    // =========================================================================
    // STATUS CODE VALIDATION — checks codes against known valid sets
    // =========================================================================

    /**
     * Validate a loan status code against the known set (ACT, CLO, DFT, FRB).
     * Returns the code if valid, logs a warning and returns the raw code if unknown.
     */
    public String validateLoanStatusCode(String code, String recordId) {
        return validateCode(code, VALID_LOAN_STATUS_CODES, "loan status", recordId);
    }

    /**
     * Validate a borrower status code against the known set (ACT, INA).
     */
    public String validateBorrowerStatusCode(String code, String recordId) {
        return validateCode(code, VALID_BORROWER_STATUS_CODES, "borrower status", recordId);
    }

    /**
     * Validate a payment type code against the known set (REG, EXT, PRT, PRE).
     */
    public String validatePaymentTypeCode(String code, String recordId) {
        return validateCode(code, VALID_PAYMENT_TYPE_CODES, "payment type", recordId);
    }

    /**
     * Validate a payment status code against the known set (PST, REV, NSF, PND).
     */
    public String validatePaymentStatusCode(String code, String recordId) {
        return validateCode(code, VALID_PAYMENT_STATUS_CODES, "payment status", recordId);
    }

    /**
     * Validate a property type code against the known set (SFR, CND, MFR, TWN).
     */
    public String validatePropertyTypeCode(String code, String recordId) {
        return validateCode(code, VALID_PROPERTY_TYPE_CODES, "property type", recordId);
    }

    /**
     * Validate a product type code against the known set (FXD, ARM, FHA, VA).
     */
    public String validateProductTypeCode(String code, String recordId) {
        return validateCode(code, VALID_PRODUCT_TYPE_CODES, "product type", recordId);
    }

    /**
     * Validate a rate type code against the known set (FIXED, VARIABLE).
     */
    public String validateRateTypeCode(String code, String recordId) {
        return validateCode(code, VALID_RATE_TYPE_CODES, "rate type", recordId);
    }

    // =========================================================================
    // RANGE VALIDATION — checks numeric values fall within expected bounds
    // =========================================================================

    /**
     * Validate a credit score is within the FICO range (300–850).
     * Returns the score if valid, logs a warning and returns the score (clamped) if out of range.
     */
    public Integer validateCreditScore(Integer score, String recordId) {
        if (score == null) {
            return null;
        }
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            log.warn("Credit score {} out of valid range [{}-{}] for record '{}'. Clamping to valid range.",
                    score, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, recordId);
            return Math.max(CREDIT_SCORE_MIN, Math.min(CREDIT_SCORE_MAX, score));
        }
        return score;
    }

    /**
     * Validate an interest rate is within [0, 100].
     * Returns the rate if valid, logs a warning and returns ZERO if negative.
     */
    public BigDecimal validateInterestRate(BigDecimal rate, String recordId) {
        if (rate == null) {
            return BigDecimal.ZERO;
        }
        if (rate.compareTo(INTEREST_RATE_MIN) < 0) {
            log.warn("Negative interest rate {} for record '{}'. Falling back to ZERO.", rate, recordId);
            return BigDecimal.ZERO;
        }
        if (rate.compareTo(INTEREST_RATE_MAX) > 0) {
            log.warn("Interest rate {} exceeds 100% for record '{}'. Returning as-is but flagged.", rate, recordId);
        }
        return rate;
    }

    /**
     * Validate that a monetary amount is non-negative.
     * Returns BigDecimal.ZERO for negative amounts.
     */
    public BigDecimal validateNonNegativeAmount(BigDecimal amount, String fieldName, String recordId) {
        if (amount == null) {
            return BigDecimal.ZERO;
        }
        if (amount.compareTo(BigDecimal.ZERO) < 0) {
            log.warn("Negative amount {} in field '{}' for record '{}'. Falling back to ZERO.",
                    amount, fieldName, recordId);
            return BigDecimal.ZERO;
        }
        return amount;
    }

    // =========================================================================
    // CROSS-FIELD VALIDATION — checks consistency between related fields
    // =========================================================================

    /**
     * Validate that payment component amounts sum to the total within tolerance.
     * Returns true if valid, false if mismatch detected.
     * ANM-001: Payment component sum mismatch is a critical anomaly.
     */
    public boolean validatePaymentComponentSum(BigDecimal totalAmount, BigDecimal principalAmount,
                                                BigDecimal interestAmount, BigDecimal escrowAmount,
                                                BigDecimal lateFee, String paymentId) {
        // Sum the components
        BigDecimal computedSum = principalAmount
                .add(interestAmount)
                .add(escrowAmount)
                .add(lateFee);

        BigDecimal difference = totalAmount.subtract(computedSum).abs();

        if (difference.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            log.warn("Payment component sum mismatch for '{}': total={}, computed sum={}, delta={}",
                    paymentId, totalAmount, computedSum, difference);
            return false;
        }
        return true;
    }

    /**
     * Validate delinquency days vs. loan status consistency.
     * ANM-005: A loan with delinquency days > 0 should not have ACT status.
     * Returns true if consistent, false if inconsistent.
     */
    public boolean validateDelinquencyStatusConsistency(String statusCode, String delinquencyDaysStr,
                                                         String recordId) {
        if (statusCode == null || delinquencyDaysStr == null || delinquencyDaysStr.isBlank()) {
            return true;
        }
        Integer delinquencyDays = safeParseInteger(delinquencyDaysStr, "LN_DLQ_DAYS", recordId);
        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(statusCode)) {
            log.warn("Loan '{}' has {} delinquency days but status is ACT. Status may need review.",
                    recordId, delinquencyDays);
            return false;
        }
        return true;
    }

    /**
     * Validate that denormalized borrower name in loan account matches the borrower master.
     * ANM-006: Denormalized data consistency check.
     * Returns true if consistent, false if mismatch detected.
     */
    public boolean validateDenormalizedBorrowerName(String loanFirstName, String loanLastName,
                                                     String masterFirstName, String masterLastName,
                                                     String loanAccountNumber) {
        boolean firstNameMatch = nullSafeEquals(loanFirstName, masterFirstName);
        boolean lastNameMatch = nullSafeEquals(loanLastName, masterLastName);

        if (!firstNameMatch || !lastNameMatch) {
            log.warn("Denormalized borrower name mismatch for loan '{}': " +
                            "loan has '{} {}', master has '{} {}'",
                    loanAccountNumber, loanFirstName, loanLastName, masterFirstName, masterLastName);
            return false;
        }
        return true;
    }

    /**
     * Validate that SSN last-4 does not match the phone number last-4
     * (which would indicate the wrong source column was used).
     * ANM-002: SSN last-4 populated from phone number.
     * Returns true if the SSN last-4 appears genuine, false if it matches the phone pattern.
     */
    public boolean validateSsnLast4NotFromPhone(String ssnLast4, String phoneNumber, String recordId) {
        if (ssnLast4 == null || phoneNumber == null) {
            return true;
        }
        // Extract last 4 digits from phone number
        String phoneLast4 = phoneNumber.replaceAll("[^0-9]", "");
        if (phoneLast4.length() >= 4) {
            phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
            if (ssnLast4.equals(phoneLast4)) {
                log.warn("SSN last-4 '{}' for record '{}' matches phone number last-4. " +
                        "Possible data source error (ANM-002).", ssnLast4, recordId);
                return false;
            }
        }
        return true;
    }

    /**
     * Validate LTV percentage against computed value from loan amount and appraisal.
     * ANM-008: LTV percentage calculation discrepancy.
     * Returns true if within tolerance, false if discrepancy detected.
     */
    public boolean validateLtvPercentage(String ltvPercentStr, String originalAmountStr,
                                          String appraisedValueStr, String recordId) {
        BigDecimal ltv = safeParseDecimal(ltvPercentStr, "LN_LTV_PCT", recordId);
        BigDecimal originalAmount = safeParseAmount(originalAmountStr, "LN_ORIG_AMT", recordId);
        BigDecimal appraisedValue = safeParseAmount(appraisedValueStr, "PROP_APRS_VAL", recordId);

        if (appraisedValue.compareTo(BigDecimal.ZERO) == 0) {
            log.warn("Appraised value is zero for record '{}'. Cannot validate LTV.", recordId);
            return false;
        }

        // Compute expected LTV: (loan amount / appraised value) * 100
        BigDecimal computedLtv = originalAmount
                .multiply(new BigDecimal("100"))
                .divide(appraisedValue, 2, RoundingMode.HALF_UP);

        BigDecimal difference = ltv.subtract(computedLtv).abs();
        // Tolerance of 0.5% for rounding differences
        BigDecimal ltvTolerance = new BigDecimal("0.5");

        if (difference.compareTo(ltvTolerance) > 0) {
            log.warn("LTV mismatch for record '{}': stored={}, computed={}, delta={}",
                    recordId, ltv, computedLtv, difference);
            return false;
        }
        return true;
    }

    // =========================================================================
    // NULL-SAFE STRING OPERATIONS — prevents NullPointerException in concatenation
    // =========================================================================

    /**
     * Null-safe string concatenation for building display names.
     * Returns empty string for null inputs instead of the literal "null".
     */
    public String nullSafeString(String value) {
        return value != null ? value : "";
    }

    /**
     * Build a full name from first, middle initial, and last name with null safety.
     */
    public String buildFullName(String firstName, String middleInitial, String lastName) {
        StringBuilder sb = new StringBuilder();
        sb.append(nullSafeString(firstName));
        if (middleInitial != null && !middleInitial.isBlank()) {
            sb.append(" ").append(middleInitial).append(".");
        }
        sb.append(" ").append(nullSafeString(lastName));
        return sb.toString().trim();
    }

    /**
     * Build a full address from components with null safety.
     * Skips null/blank components instead of inserting "null".
     */
    public String buildFullAddress(String address, String city, String state, String zip) {
        StringBuilder sb = new StringBuilder();
        if (address != null && !address.isBlank()) {
            sb.append(address);
        }
        if (city != null && !city.isBlank()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(city);
        }
        if (state != null && !state.isBlank()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(state);
        }
        if (zip != null && !zip.isBlank()) {
            if (sb.length() > 0) sb.append(" ");
            sb.append(zip);
        }
        return sb.toString();
    }

    // =========================================================================
    // PRIVATE HELPERS
    // =========================================================================

    /**
     * Remove common non-numeric characters from legacy data strings.
     * Strips dollar signs, percent signs, commas, and surrounding whitespace.
     */
    private String sanitizeNumericString(String raw) {
        return raw.trim()
                .replace(",", "")
                .replace("$", "")
                .replace("%", "");
    }

    /**
     * Validate a code against a set of known valid values.
     * Returns the code as-is (even if unknown) to preserve the original data,
     * but logs a warning for unknown codes.
     */
    private String validateCode(String code, Set<String> validCodes, String codeType, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Missing {} code for record '{}'.", codeType, recordId);
            return code;
        }
        if (!validCodes.contains(code)) {
            log.warn("Unknown {} code '{}' for record '{}'. Valid codes: {}",
                    codeType, code, recordId, validCodes);
        }
        return code;
    }

    /**
     * Null-safe string equality check.
     */
    private boolean nullSafeEquals(String a, String b) {
        if (a == null && b == null) return true;
        if (a == null || b == null) return false;
        return a.equals(b);
    }
}
