package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Validates and sanitizes legacy CDW data at ingestion time.
 * Catches known anomalies (ANO-001 through ANO-012) before they
 * cause runtime failures in the service layer.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter PRIMARY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final DateTimeFormatter ISO_DATE_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd");
    private static final DateTimeFormatter SHORT_DATE_FORMAT =
            DateTimeFormatter.ofPattern("dd-MMM-yy");

    private static final Pattern NON_NUMERIC_PATTERN = Pattern.compile("[^\\d.\\-]");

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    // --- Amount Parsing (ANO-001) ---

    /**
     * Parse a legacy amount string into BigDecimal with defensive handling.
     * Strips currency symbols, whitespace, and commas before parsing.
     * Returns BigDecimal.ZERO with a warning for unparseable values.
     */
    public BigDecimal parseAmount(String amount, String recordId, String columnName) {
        if (amount == null || amount.isBlank()) {
            log.warn("Null/blank amount in {}.{} for record {}, defaulting to ZERO",
                    columnName, columnName, recordId);
            return BigDecimal.ZERO;
        }

        String cleaned = NON_NUMERIC_PATTERN.matcher(amount).replaceAll("");
        if (cleaned.isEmpty()) {
            log.warn("Unparseable amount '{}' in {} for record {}, defaulting to ZERO",
                    amount, columnName, recordId);
            return BigDecimal.ZERO;
        }

        try {
            BigDecimal result = new BigDecimal(cleaned);
            if (result.compareTo(BigDecimal.ZERO) < 0) {
                log.warn("Negative amount '{}' in {} for record {}", amount, columnName, recordId);
            }
            return result;
        } catch (NumberFormatException e) {
            log.warn("Unparseable amount '{}' in {} for record {}, defaulting to ZERO",
                    amount, columnName, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (no commas expected, e.g., interest rates).
     */
    public BigDecimal parseDecimal(String value, String recordId, String columnName) {
        if (value == null || value.isBlank()) {
            log.warn("Null/blank decimal in {} for record {}, defaulting to ZERO",
                    columnName, recordId);
            return BigDecimal.ZERO;
        }

        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal '{}' in {} for record {}, defaulting to ZERO",
                    value, columnName, recordId);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., credit score, term months).
     */
    public Integer parseInteger(String value, String recordId, String columnName) {
        if (value == null || value.isBlank()) {
            log.warn("Null/blank integer in {} for record {}", columnName, recordId);
            return null;
        }

        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer '{}' in {} for record {}", value, columnName, recordId);
            return null;
        }
    }

    // --- Date Parsing (ANO-002) ---

    /**
     * Parse a legacy date string, trying MM/dd/yyyy first, then ISO, then dd-MMM-yy.
     * Returns null with a warning for unparseable dates.
     */
    public LocalDate parseDate(String dateStr, String recordId, String columnName) {
        if (dateStr == null || dateStr.isBlank()) {
            log.warn("Null/blank date in {} for record {}", columnName, recordId);
            return null;
        }

        String trimmed = dateStr.trim();

        LocalDate parsed = tryParseDate(trimmed, PRIMARY_DATE_FORMAT);
        if (parsed != null) return validateDateBounds(parsed, dateStr, recordId, columnName);

        parsed = tryParseDate(trimmed, ISO_DATE_FORMAT);
        if (parsed != null) return validateDateBounds(parsed, dateStr, recordId, columnName);

        parsed = tryParseDate(trimmed, SHORT_DATE_FORMAT);
        if (parsed != null) return validateDateBounds(parsed, dateStr, recordId, columnName);

        log.warn("Unparseable date '{}' in {} for record {}", dateStr, columnName, recordId);
        return null;
    }

    /**
     * Format a date as ISO-8601 string, returning the raw input on parse failure.
     */
    public String formatDateToIso(String dateStr, String recordId, String columnName) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        LocalDate parsed = parseDate(dateStr, recordId, columnName);
        return parsed != null ? parsed.toString() : dateStr;
    }

    private LocalDate tryParseDate(String value, DateTimeFormatter formatter) {
        try {
            return LocalDate.parse(value, formatter);
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    private LocalDate validateDateBounds(LocalDate date, String original,
                                         String recordId, String columnName) {
        if (date.getYear() < 1900 || date.getYear() > 2100) {
            log.warn("Date '{}' in {} for record {} is out of bounds (year={})",
                    original, columnName, recordId, date.getYear());
        }
        return date;
    }

    // --- Status Code Validation (ANO-004) ---

    public String validateLoanStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_LOAN_STATUSES, "LN_STAT_CD", recordId);
    }

    public String validatePaymentStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_PAYMENT_STATUSES, "PMT_STAT_CD", recordId);
    }

    public String validatePaymentType(String code, String recordId) {
        return validateStatusCode(code, VALID_PAYMENT_TYPES, "PMT_TYP_CD", recordId);
    }

    public String validatePropertyType(String code, String recordId) {
        return validateStatusCode(code, VALID_PROPERTY_TYPES, "PROP_TYP_CD", recordId);
    }

    public String validateBorrowerStatus(String code, String recordId) {
        return validateStatusCode(code, VALID_BORROWER_STATUSES, "BORR_STAT_CD", recordId);
    }

    private String validateStatusCode(String code, Set<String> validCodes,
                                       String columnName, String recordId) {
        if (code == null || code.isBlank()) {
            log.warn("Null/blank status code in {} for record {}", columnName, recordId);
            return code;
        }

        String normalized = code.trim().toUpperCase();
        if (!validCodes.contains(normalized)) {
            log.warn("Unrecognized status code '{}' in {} for record {} (valid: {})",
                    code, columnName, recordId, validCodes);
        }
        return normalized;
    }

    // --- Credit Score Validation (ANO-007) ---

    public Integer validateCreditScore(String value, String recordId) {
        Integer score = parseInteger(value, recordId, "BORR_CRDT_SCR");
        if (score != null && (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX)) {
            log.warn("Credit score {} out of valid range [{}-{}] for record {}",
                    score, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, recordId);
        }
        return score;
    }

    // --- Required Field Validation (ANO-006) ---

    public List<String> validateBorrowerRequired(LegacyBorrower borrower) {
        List<String> violations = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (isBlank(borrower.getBorrowerId())) {
            violations.add("BORR_ID is null/blank");
        }
        if (isBlank(borrower.getFirstName())) {
            violations.add("BORR_FST_NM is null/blank for " + id);
        }
        if (isBlank(borrower.getLastName())) {
            violations.add("BORR_LST_NM is null/blank for " + id);
        }
        if (isBlank(borrower.getSsnEncrypted())) {
            violations.add("BORR_SSN_ENCR is null/blank for " + id);
        }

        if (!violations.isEmpty()) {
            log.warn("Required field violations for borrower {}: {}", id, violations);
        }
        return violations;
    }

    public List<String> validateLoanAccountRequired(LegacyLoanAccount account) {
        List<String> violations = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        if (isBlank(account.getLoanAccountNumber())) {
            violations.add("LN_ACCT_NBR is null/blank");
        }
        if (isBlank(account.getBorrowerId())) {
            violations.add("BORR_ID is null/blank for loan " + id);
        }
        if (isBlank(account.getProductCode())) {
            violations.add("PROD_CD is null/blank for loan " + id);
        }
        if (isBlank(account.getOriginalAmount())) {
            violations.add("LN_ORIG_AMT is null/blank for loan " + id);
        }
        if (isBlank(account.getStatusCode())) {
            violations.add("LN_STAT_CD is null/blank for loan " + id);
        }

        if (!violations.isEmpty()) {
            log.warn("Required field violations for loan {}: {}", id, violations);
        }
        return violations;
    }

    public List<String> validatePaymentRequired(LegacyPayment payment) {
        List<String> violations = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        if (isBlank(payment.getPaymentSequenceNumber())) {
            violations.add("PMT_SEQ_NBR is null/blank");
        }
        if (isBlank(payment.getLoanAccountNumber())) {
            violations.add("LN_ACCT_NBR is null/blank for payment " + id);
        }
        if (isBlank(payment.getTotalAmount())) {
            violations.add("PMT_AMT is null/blank for payment " + id);
        }
        if (isBlank(payment.getStatusCode())) {
            violations.add("PMT_STAT_CD is null/blank for payment " + id);
        }

        if (!violations.isEmpty()) {
            log.warn("Required field violations for payment {}: {}", id, violations);
        }
        return violations;
    }

    // --- Payment Amount Reconciliation (ANO-008) ---

    /**
     * Check that payment component amounts sum to the total amount within tolerance.
     */
    public boolean validatePaymentAmountReconciliation(LegacyPayment payment) {
        String id = payment.getPaymentSequenceNumber();
        BigDecimal total = parseAmount(payment.getTotalAmount(), id, "PMT_AMT");
        BigDecimal principal = parseAmount(payment.getPrincipalAmount(), id, "PMT_PRIN_AMT");
        BigDecimal interest = parseAmount(payment.getInterestAmount(), id, "PMT_INT_AMT");
        BigDecimal escrow = parseAmount(payment.getEscrowAmount(), id, "PMT_ESCROW_AMT");
        BigDecimal lateFee = parseAmount(payment.getLateFee(), id, "PMT_LATE_FEE");

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal delta = componentSum.subtract(total).abs();

        if (delta.compareTo(new BigDecimal("0.02")) > 0) {
            log.warn("Payment {} amount mismatch: total={}, components sum={}, delta={}",
                    id, total, componentSum, delta);
            return false;
        }
        return true;
    }

    // --- Delinquency-Status Consistency (ANO-009) ---

    public boolean validateDelinquencyStatusConsistency(LegacyLoanAccount account) {
        String id = account.getLoanAccountNumber();
        Integer dlqDays = parseInteger(account.getDelinquencyDays(), id, "LN_DLQ_DAYS");
        String status = account.getStatusCode();

        if (dlqDays != null && dlqDays > 0 && "ACT".equals(status)) {
            log.warn("Loan {} has {} delinquency days but status is ACT (Active)", id, dlqDays);
            return false;
        }
        if (dlqDays != null && dlqDays >= 90 && !"DFT".equals(status) && !"FRB".equals(status)) {
            log.warn("Loan {} has {} delinquency days but status is {} (expected DFT or FRB)",
                    id, dlqDays, status);
            return false;
        }
        return true;
    }

    // --- LTV Validation (ANO-010) ---

    public boolean validateLtvConsistency(LegacyLoanAccount account) {
        String id = account.getLoanAccountNumber();
        BigDecimal storedLtv = parseDecimal(account.getLtvPercent(), id, "LN_LTV_PCT");
        BigDecimal currentBalance = parseAmount(account.getCurrentBalance(), id, "LN_CURR_BAL");
        BigDecimal appraisedValue = parseAmount(account.getAppraisedValue(), id, "PROP_APRS_VAL");

        if (appraisedValue.compareTo(BigDecimal.ZERO) == 0) {
            log.warn("Loan {} has zero appraised value, cannot compute LTV", id);
            return false;
        }

        BigDecimal computedLtv = currentBalance
                .multiply(new BigDecimal("100"))
                .divide(appraisedValue, 1, java.math.RoundingMode.HALF_UP);
        BigDecimal ltvDelta = storedLtv.subtract(computedLtv).abs();

        if (ltvDelta.compareTo(new BigDecimal("5.0")) > 0) {
            log.warn("Loan {} LTV mismatch: stored={}, computed from current balance={}, delta={}",
                    id, storedLtv, computedLtv, ltvDelta);
            return false;
        }
        return true;
    }

    // --- Null-safe String Handling ---

    public String safeString(String value, String defaultValue) {
        return (value != null && !value.isBlank()) ? value.trim() : defaultValue;
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
