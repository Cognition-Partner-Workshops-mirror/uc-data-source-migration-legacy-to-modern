package com.workshop.loanservice.migration;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Validates and parses legacy VARCHAR amount/numeric fields into proper Java types.
 * <p>
 * Legacy CDW tables store monetary amounts as VARCHAR(15) with embedded commas
 * (e.g. "285,000" or "1,487.02"). The modern schema uses DECIMAL columns with
 * defined precision and scale. This validator strips formatting, validates
 * against the target column constraints, and checks domain-specific ranges.
 * </p>
 */
public class AmountValidator {

    // Regex for a valid numeric value after comma stripping: digits with optional decimal part
    private static final Pattern NUMERIC_PATTERN = Pattern.compile("^\\d+(\\.\\d+)?$");

    /**
     * Parse a legacy amount string into BigDecimal, validating against DECIMAL(precision, scale).
     * Strips commas, validates numeric format, checks precision/scale limits, rejects negatives.
     *
     * @param raw       the raw string from the legacy table (may contain commas)
     * @param columnName the source column name for error reporting
     * @param required  if true, null/blank/unparseable yields ERROR; otherwise WARNING
     * @param precision total number of digits allowed (e.g. 12 for DECIMAL(12,2))
     * @param scale     number of decimal places allowed (e.g. 2 for DECIMAL(12,2))
     * @return validation result containing the parsed BigDecimal or error details
     */
    public ValidationResult<BigDecimal> parseAmount(String raw, String columnName,
                                                    boolean required, int precision, int scale) {
        // Handle null/blank input
        if (raw == null || raw.isBlank()) {
            if (required) {
                return ValidationResult.error(columnName, raw,
                        "Required amount field is null or blank");
            }
            return ValidationResult.ok(null);
        }

        // Strip commas (legacy formatting) and trim whitespace
        String cleaned = raw.trim().replace(",", "");

        // Validate against numeric regex
        if (!NUMERIC_PATTERN.matcher(cleaned).matches()) {
            String msg = "Invalid numeric format after comma removal: '" + cleaned + "'";
            if (required) {
                return ValidationResult.error(columnName, raw, msg);
            }
            return ValidationResult.warning(columnName, raw, msg);
        }

        BigDecimal value;
        try {
            value = new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            return ValidationResult.error(columnName, raw,
                    "Failed to parse as BigDecimal: " + e.getMessage());
        }

        // Reject negative values — all monetary amounts should be non-negative
        if (value.compareTo(BigDecimal.ZERO) < 0) {
            return ValidationResult.error(columnName, raw,
                    "Negative value not allowed: " + value);
        }

        // Check precision/scale limits for DECIMAL(precision, scale)
        BigDecimal scaled = value.setScale(scale, RoundingMode.UNNECESSARY);
        BigDecimal maxValue = BigDecimal.TEN.pow(precision - scale).subtract(BigDecimal.ONE.scaleByPowerOfTen(-scale));
        if (scaled.compareTo(maxValue) > 0) {
            return ValidationResult.error(columnName, raw,
                    "Value " + value + " exceeds DECIMAL(" + precision + "," + scale + ") limit of " + maxValue);
        }

        return ValidationResult.ok(value);
    }

    /**
     * Parse and validate an interest rate — specialized for DECIMAL(5,3).
     * Valid range: 0% to 30% inclusive.
     */
    public ValidationResult<BigDecimal> parseInterestRate(String raw) {
        ValidationResult<BigDecimal> result = parseAmount(raw, "interest_rate", true, 5, 3);
        if (!result.isValid()) return result;

        BigDecimal rate = result.getValue();
        if (rate != null && rate.compareTo(new BigDecimal("30")) > 0) {
            return ValidationResult.warning("interest_rate", raw,
                    "Interest rate " + rate + "% exceeds typical maximum of 30%");
        }

        return result;
    }

    /**
     * Parse and validate a loan-to-value percentage — range 0% to 200% inclusive.
     */
    public ValidationResult<BigDecimal> parseLtvPercent(String raw) {
        ValidationResult<BigDecimal> result = parseAmount(raw, "ltv_percent", false, 5, 2);
        if (!result.isValid()) return result;

        BigDecimal ltv = result.getValue();
        if (ltv != null && ltv.compareTo(new BigDecimal("200")) > 0) {
            return ValidationResult.warning("ltv_percent", raw,
                    "LTV " + ltv + "% exceeds maximum of 200%");
        }

        return result;
    }

    /**
     * Parse and validate a credit score — valid range 300 to 850 inclusive.
     */
    public ValidationResult<Integer> parseCreditScore(String raw) {
        if (raw == null || raw.isBlank()) {
            return ValidationResult.ok(null);
        }

        String trimmed = raw.trim();
        int score;
        try {
            score = Integer.parseInt(trimmed);
        } catch (NumberFormatException e) {
            return ValidationResult.error("credit_score", raw,
                    "Cannot parse credit score as integer: '" + trimmed + "'");
        }

        if (score < 300 || score > 850) {
            return ValidationResult.warning("credit_score", raw,
                    "Credit score " + score + " outside valid range 300-850");
        }

        return ValidationResult.ok(score);
    }

    /**
     * Parse a legacy integer string — replaces the existing parseLegacyInteger
     * which throws uncaught NumberFormatException on invalid input.
     *
     * @param raw        the raw string value
     * @param columnName the source column name for error reporting
     * @param required   if true, null/blank/unparseable yields ERROR; otherwise WARNING
     * @return validation result containing the parsed Integer or error details
     */
    public ValidationResult<Integer> parseInteger(String raw, String columnName, boolean required) {
        if (raw == null || raw.isBlank()) {
            if (required) {
                return ValidationResult.error(columnName, raw,
                        "Required integer field is null or blank");
            }
            return ValidationResult.ok(null);
        }

        String trimmed = raw.trim();
        try {
            return ValidationResult.ok(Integer.parseInt(trimmed));
        } catch (NumberFormatException e) {
            String msg = "Cannot parse as integer: '" + trimmed + "'";
            if (required) {
                return ValidationResult.error(columnName, raw, msg);
            }
            return ValidationResult.warning(columnName, raw, msg);
        }
    }

    /**
     * Validate that payment components sum to the total amount.
     * Checks: principal + interest + escrow + lateFee == total.
     * Returns WARNING with the delta amount if they don't match.
     *
     * @param total     the total payment amount (PMT_AMT)
     * @param principal the principal portion (PMT_PRIN_AMT)
     * @param interest  the interest portion (PMT_INT_AMT)
     * @param escrow    the escrow portion (PMT_ESCROW_AMT)
     * @param lateFee   the late fee amount (PMT_LATE_FEE)
     * @param paymentId the payment sequence number for error reporting
     * @return list of WARNING results if components don't sum to total
     */
    public List<ValidationResult<?>> validatePaymentComponentSum(BigDecimal total,
                                                                  BigDecimal principal,
                                                                  BigDecimal interest,
                                                                  BigDecimal escrow,
                                                                  BigDecimal lateFee,
                                                                  String paymentId) {
        List<ValidationResult<?>> results = new ArrayList<>();

        if (total == null || principal == null || interest == null) {
            // Can't validate if key components are missing
            return results;
        }

        // Default escrow and lateFee to zero if null
        BigDecimal esc = escrow != null ? escrow : BigDecimal.ZERO;
        BigDecimal fee = lateFee != null ? lateFee : BigDecimal.ZERO;

        BigDecimal componentSum = principal.add(interest).add(esc).add(fee);
        if (componentSum.compareTo(total) != 0) {
            BigDecimal delta = componentSum.subtract(total);
            results.add(ValidationResult.warning("payment_components/" + paymentId,
                    "total=" + total + " components=" + componentSum,
                    "Payment component sum mismatch: principal(" + principal
                            + ") + interest(" + interest + ") + escrow(" + esc
                            + ") + lateFee(" + fee + ") = " + componentSum
                            + " but total is " + total + " (delta: " + delta + ")"));
        }

        return results;
    }
}
