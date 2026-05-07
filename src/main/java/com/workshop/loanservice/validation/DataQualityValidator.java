package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
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
import java.util.Set;

/**
 * Validates legacy CDW data at ingestion time, catching anomalies
 * documented in docs/DATA_ANOMALY_REPORT.md before they cause
 * runtime failures or silent data corruption.
 *
 * Each validate method returns a list of warning/error messages.
 * An empty list indicates the record passed all checks.
 */
@Component
public class DataQualityValidator {

    private static final Logger log = LoggerFactory.getLogger(DataQualityValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    // Valid status codes per column_mappings.md
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    // Credit score business range (FICO)
    private static final int MIN_CREDIT_SCORE = 300;
    private static final int MAX_CREDIT_SCORE = 850;

    /**
     * Validates a legacy borrower record for null required fields,
     * unparseable numeric fields, invalid dates, and invalid status codes.
     */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> issues = new ArrayList<>();
        String id = borrower.getBorrowerId();

        // ANOM-002: Null required fields
        if (isBlank(borrower.getFirstName())) {
            issues.add(String.format("Borrower %s: BORR_FST_NM is null/blank (required field)", id));
        }
        if (isBlank(borrower.getLastName())) {
            issues.add(String.format("Borrower %s: BORR_LST_NM is null/blank (required field)", id));
        }
        if (isBlank(borrower.getSsnEncrypted())) {
            issues.add(String.format("Borrower %s: BORR_SSN_ENCR is null/blank (required for identity)", id));
        }

        // ANOM-003: Numeric parsing risks — credit score
        if (!isBlank(borrower.getCreditScore())) {
            Integer score = safeParseInteger(borrower.getCreditScore());
            if (score == null) {
                issues.add(String.format("Borrower %s: BORR_CRDT_SCR '%s' is not a valid integer",
                        id, borrower.getCreditScore()));
            } else if (score < MIN_CREDIT_SCORE || score > MAX_CREDIT_SCORE) {
                issues.add(String.format("Borrower %s: BORR_CRDT_SCR %d is outside valid FICO range [%d-%d]",
                        id, score, MIN_CREDIT_SCORE, MAX_CREDIT_SCORE));
            }
        }

        // ANOM-003: Numeric parsing risks — annual income
        if (!isBlank(borrower.getAnnualIncome())) {
            BigDecimal income = safeParseAmount(borrower.getAnnualIncome());
            if (income == null) {
                issues.add(String.format("Borrower %s: BORR_ANN_INCM '%s' is not a valid amount",
                        id, borrower.getAnnualIncome()));
            } else if (income.compareTo(BigDecimal.ZERO) < 0) {
                issues.add(String.format("Borrower %s: BORR_ANN_INCM is negative: %s", id, income));
            }
        }

        // ANOM-008: Date format validation
        validateDateField(borrower.getDateOfBirth(), "BORR_DOB_DT", id, issues);
        validateDateField(borrower.getCreatedDate(), "BORR_CRET_DT", id, issues);
        validateDateField(borrower.getUpdatedDate(), "BORR_UPDT_DT", id, issues);

        // ANOM-009: Status code validation
        if (!isBlank(borrower.getStatusCode()) && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            issues.add(String.format("Borrower %s: BORR_STAT_CD '%s' is not a recognized status code (valid: %s)",
                    id, borrower.getStatusCode(), VALID_BORROWER_STATUSES));
        }

        // Log all issues found for this record
        for (String issue : issues) {
            log.warn("Data quality issue: {}", issue);
        }

        return issues;
    }

    /**
     * Validates a legacy loan account for null required fields, unparseable
     * numeric fields, invalid status codes, and referential integrity hints.
     */
    public List<String> validateLoanAccount(LegacyLoanAccount account) {
        List<String> issues = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        // ANOM-002: Null required fields
        if (isBlank(account.getBorrowerId())) {
            issues.add(String.format("Loan %s: BORR_ID is null/blank (required for borrower lookup)", id));
        }
        if (isBlank(account.getProductCode())) {
            issues.add(String.format("Loan %s: PROD_CD is null/blank (required for product lookup)", id));
        }
        if (isBlank(account.getBorrowerFirstName())) {
            issues.add(String.format("Loan %s: BORR_FST_NM is null/blank (required for display)", id));
        }
        if (isBlank(account.getBorrowerLastName())) {
            issues.add(String.format("Loan %s: BORR_LST_NM is null/blank (required for display)", id));
        }

        // ANOM-003: Numeric parsing risks — loan amounts
        validateAmountField(account.getOriginalAmount(), "LN_ORIG_AMT", id, issues);
        validateAmountField(account.getCurrentBalance(), "LN_CURR_BAL", id, issues);
        validateAmountField(account.getMonthlyPayment(), "LN_PMT_AMT", id, issues);
        validateAmountField(account.getEscrowBalance(), "LN_ESCROW_BAL", id, issues);
        validateAmountField(account.getAppraisedValue(), "PROP_APRS_VAL", id, issues);

        // ANOM-003: Interest rate parsing
        if (!isBlank(account.getInterestRate())) {
            BigDecimal rate = safeParseDecimal(account.getInterestRate());
            if (rate == null) {
                issues.add(String.format("Loan %s: LN_INT_RT '%s' is not a valid decimal",
                        id, account.getInterestRate()));
            } else if (rate.compareTo(BigDecimal.ZERO) < 0 || rate.compareTo(new BigDecimal("100")) > 0) {
                issues.add(String.format("Loan %s: LN_INT_RT %s is outside valid range [0-100]", id, rate));
            }
        }

        // ANOM-003: Integer parsing — term months, delinquency days
        validateIntegerField(account.getTermMonths(), "LN_TERM_MOS", id, issues);
        validateIntegerField(account.getDelinquencyDays(), "LN_DLQ_DAYS", id, issues);

        // ANOM-003: LTV percent parsing
        if (!isBlank(account.getLtvPercent())) {
            BigDecimal ltv = safeParseDecimal(account.getLtvPercent());
            if (ltv == null) {
                issues.add(String.format("Loan %s: LN_LTV_PCT '%s' is not a valid decimal",
                        id, account.getLtvPercent()));
            }
        }

        // ANOM-008: Date format validation
        validateDateField(account.getOriginationDate(), "LN_ORIG_DT", id, issues);
        validateDateField(account.getMaturityDate(), "LN_MAT_DT", id, issues);
        validateDateField(account.getFirstPaymentDate(), "LN_1ST_PMT_DT", id, issues);
        validateDateField(account.getNextPaymentDate(), "LN_NXT_PMT_DT", id, issues);
        validateDateField(account.getCreatedDate(), "LN_CRET_DT", id, issues);
        validateDateField(account.getUpdatedDate(), "LN_UPDT_DT", id, issues);

        // ANOM-009: Status code validation
        if (!isBlank(account.getStatusCode()) && !VALID_LOAN_STATUSES.contains(account.getStatusCode())) {
            issues.add(String.format("Loan %s: LN_STAT_CD '%s' is not a recognized status code (valid: %s)",
                    id, account.getStatusCode(), VALID_LOAN_STATUSES));
        }

        // ANOM-009: Property type validation
        if (!isBlank(account.getPropertyType()) && !VALID_PROPERTY_TYPES.contains(account.getPropertyType())) {
            issues.add(String.format("Loan %s: PROP_TYP_CD '%s' is not a recognized property type (valid: %s)",
                    id, account.getPropertyType(), VALID_PROPERTY_TYPES));
        }

        // Log all issues found for this record
        for (String issue : issues) {
            log.warn("Data quality issue: {}", issue);
        }

        return issues;
    }

    /**
     * Validates a legacy payment for null required fields, unparseable amounts,
     * payment component mismatch, invalid status/type codes, and temporal consistency.
     */
    public List<String> validatePayment(LegacyPayment payment) {
        List<String> issues = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        // ANOM-002: Null required fields
        if (isBlank(payment.getLoanAccountNumber())) {
            issues.add(String.format("Payment %s: LN_ACCT_NBR is null/blank (required for loan lookup)", id));
        }
        if (isBlank(payment.getTotalAmount())) {
            issues.add(String.format("Payment %s: PMT_AMT is null/blank (required)", id));
        }

        // ANOM-003: Numeric parsing risks — payment amounts
        validateAmountField(payment.getTotalAmount(), "PMT_AMT", id, issues);
        validateAmountField(payment.getPrincipalAmount(), "PMT_PRIN_AMT", id, issues);
        validateAmountField(payment.getInterestAmount(), "PMT_INT_AMT", id, issues);
        validateAmountField(payment.getEscrowAmount(), "PMT_ESCROW_AMT", id, issues);
        validateAmountField(payment.getLateFee(), "PMT_LATE_FEE", id, issues);

        // ANOM-001: Payment component mismatch validation
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());

        if (total != null && principal != null && interest != null && escrow != null) {
            BigDecimal componentSum = principal.add(interest).add(escrow);
            // Allow small rounding tolerance of $0.01
            BigDecimal delta = total.subtract(componentSum).abs();
            if (delta.compareTo(new BigDecimal("0.01")) > 0) {
                issues.add(String.format(
                        "Payment %s: Component mismatch — total=%s but principal(%s)+interest(%s)+escrow(%s)=%s, delta=%s",
                        id, total, principal, interest, escrow, componentSum, delta));
            }
        }

        // ANOM-006: Temporal consistency — payment date vs received date
        if (!isBlank(payment.getPaymentDate()) && !isBlank(payment.getReceivedDate())) {
            LocalDate pmtDate = safeParseLegacyDate(payment.getPaymentDate());
            LocalDate recvDate = safeParseLegacyDate(payment.getReceivedDate());
            if (pmtDate != null && recvDate != null && pmtDate.isBefore(recvDate)) {
                issues.add(String.format(
                        "Payment %s: PMT_DT (%s) is before PMT_RECV_DT (%s) — possible late payment or field semantics issue",
                        id, payment.getPaymentDate(), payment.getReceivedDate()));
            }
        }

        // ANOM-008: Date format validation
        validateDateField(payment.getPaymentDate(), "PMT_DT", id, issues);
        validateDateField(payment.getReceivedDate(), "PMT_RECV_DT", id, issues);
        validateDateField(payment.getProcessedDate(), "PMT_PROC_DT", id, issues);
        validateDateField(payment.getCreatedDate(), "PMT_CRET_DT", id, issues);
        validateDateField(payment.getUpdatedDate(), "PMT_UPDT_DT", id, issues);

        // ANOM-009: Status and type code validation
        if (!isBlank(payment.getStatusCode()) && !VALID_PAYMENT_STATUSES.contains(payment.getStatusCode())) {
            issues.add(String.format("Payment %s: PMT_STAT_CD '%s' is not a recognized status (valid: %s)",
                    id, payment.getStatusCode(), VALID_PAYMENT_STATUSES));
        }
        if (!isBlank(payment.getTypeCode()) && !VALID_PAYMENT_TYPES.contains(payment.getTypeCode())) {
            issues.add(String.format("Payment %s: PMT_TYP_CD '%s' is not a recognized type (valid: %s)",
                    id, payment.getTypeCode(), VALID_PAYMENT_TYPES));
        }

        // Log all issues found for this record
        for (String issue : issues) {
            log.warn("Data quality issue: {}", issue);
        }

        return issues;
    }

    // =========================================================================
    // Safe parsing helpers — return null on failure instead of throwing
    // =========================================================================

    /**
     * Parses a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Returns null if the value cannot be parsed.
     */
    public BigDecimal safeParseAmount(String amount) {
        if (isBlank(amount)) return null;
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
            return null;
        }
    }

    /**
     * Parses a legacy decimal string (e.g., "4.750") to BigDecimal.
     * Returns null if the value cannot be parsed.
     */
    public BigDecimal safeParseDecimal(String value) {
        if (isBlank(value)) return null;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Parses a legacy integer string (e.g., "360") to Integer.
     * Returns null if the value cannot be parsed.
     */
    public Integer safeParseInteger(String value) {
        if (isBlank(value)) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Parses a legacy date string in MM/DD/YYYY format to LocalDate.
     * Returns null if the value cannot be parsed.
     */
    public LocalDate safeParseLegacyDate(String dateStr) {
        if (isBlank(dateStr)) return null;
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    // =========================================================================
    // Private helper methods
    // =========================================================================

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    /** Validates that an amount field can be parsed as a non-negative BigDecimal. */
    private void validateAmountField(String value, String fieldName, String recordId, List<String> issues) {
        if (!isBlank(value)) {
            BigDecimal parsed = safeParseAmount(value);
            if (parsed == null) {
                issues.add(String.format("%s %s: %s '%s' is not a valid amount",
                        recordId.startsWith("PMT") ? "Payment" : "Loan", recordId, fieldName, value));
            } else if (parsed.compareTo(BigDecimal.ZERO) < 0) {
                issues.add(String.format("%s %s: %s is negative: %s",
                        recordId.startsWith("PMT") ? "Payment" : "Loan", recordId, fieldName, parsed));
            }
        }
    }

    /** Validates that an integer field can be parsed. */
    private void validateIntegerField(String value, String fieldName, String recordId, List<String> issues) {
        if (!isBlank(value)) {
            Integer parsed = safeParseInteger(value);
            if (parsed == null) {
                issues.add(String.format("Loan %s: %s '%s' is not a valid integer",
                        recordId, fieldName, value));
            }
        }
    }

    /** Validates that a date field conforms to MM/DD/YYYY format. */
    private void validateDateField(String value, String fieldName, String recordId, List<String> issues) {
        if (!isBlank(value)) {
            LocalDate parsed = safeParseLegacyDate(value);
            if (parsed == null) {
                issues.add(String.format("%s: %s '%s' is not a valid MM/DD/YYYY date", recordId, fieldName, value));
            }
        }
    }
}
