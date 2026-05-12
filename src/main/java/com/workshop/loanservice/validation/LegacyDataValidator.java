package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.DataQualityIssue.Severity;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Validates legacy CDW data at ingestion time, catching anomalies documented in
 * docs/DATA_ANOMALY_REPORT.md before they cause runtime failures or incorrect
 * API responses.
 *
 * Covers: null required fields, numeric parsing safety, date format validation,
 * cross-field consistency (payment sums, delinquency vs status, denormalized
 * name divergence), credit score range, and foreign key existence.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Expected date format in all legacy tables — STRICT mode rejects invalid
    // days like 02/30 instead of silently rounding them (ANO-008)
    private static final DateTimeFormatter LEGACY_DATE_FMT =
            DateTimeFormatter.ofPattern("MM/dd/uuuu").withResolverStyle(ResolverStyle.STRICT);

    // Valid FICO credit score range
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    // Known valid status codes for each domain
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    // Tolerance for payment component sum comparison (to account for rounding)
    private static final BigDecimal RECONCILIATION_TOLERANCE = new BigDecimal("0.01");

    // =========================================================================
    // Borrower validation
    // =========================================================================

    /**
     * Validates a legacy borrower record for null required fields, parseable
     * numeric/date fields, and credit score range.
     */
    public List<DataQualityIssue> validateBorrower(LegacyBorrower borrower) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String id = borrower.getBorrowerId() != null ? borrower.getBorrowerId() : "UNKNOWN";
        String table = "CDW_BORR_MSTR";

        // ANO-005: Null required fields
        if (isBlank(borrower.getFirstName())) {
            issues.add(new DataQualityIssue(Severity.HIGH, table, id,
                    "BORR_FST_NM", "Required field is null/blank", borrower.getFirstName()));
        }
        if (isBlank(borrower.getLastName())) {
            issues.add(new DataQualityIssue(Severity.HIGH, table, id,
                    "BORR_LST_NM", "Required field is null/blank", borrower.getLastName()));
        }
        if (isBlank(borrower.getEmail())) {
            issues.add(new DataQualityIssue(Severity.MEDIUM, table, id,
                    "BORR_EMAIL_ADDR", "Email is null/blank", borrower.getEmail()));
        }

        // ANO-003: Numeric parsing safety — credit score
        if (!isBlank(borrower.getCreditScore())) {
            Integer score = safeParseInt(borrower.getCreditScore());
            if (score == null) {
                issues.add(new DataQualityIssue(Severity.CRITICAL, table, id,
                        "BORR_CRDT_SCR", "Unparseable credit score",
                        borrower.getCreditScore()));
            } else if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
                // ANO-010: Credit score out of valid FICO range
                issues.add(new DataQualityIssue(Severity.LOW, table, id,
                        "BORR_CRDT_SCR",
                        "Credit score out of range (valid: " + CREDIT_SCORE_MIN + "-" + CREDIT_SCORE_MAX + ")",
                        borrower.getCreditScore()));
            }
        }

        // ANO-003: Numeric parsing safety — annual income
        if (!isBlank(borrower.getAnnualIncome())) {
            BigDecimal income = safeParseAmount(borrower.getAnnualIncome());
            if (income == null) {
                issues.add(new DataQualityIssue(Severity.CRITICAL, table, id,
                        "BORR_ANN_INCM", "Unparseable annual income",
                        borrower.getAnnualIncome()));
            }
        }

        // ANO-008: Date format validation
        validateDateField(issues, table, id, "BORR_DOB_DT", borrower.getDateOfBirth());
        validateDateField(issues, table, id, "BORR_CRET_DT", borrower.getCreatedDate());
        validateDateField(issues, table, id, "BORR_UPDT_DT", borrower.getUpdatedDate());

        logIssues(issues);
        return issues;
    }

    // =========================================================================
    // Loan account validation
    // =========================================================================

    /**
     * Validates a legacy loan account for null fields, numeric parsing,
     * status code validity, delinquency consistency, and date logic.
     */
    public List<DataQualityIssue> validateLoanAccount(LegacyLoanAccount acct) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String id = acct.getLoanAccountNumber() != null ? acct.getLoanAccountNumber() : "UNKNOWN";
        String table = "CDW_LN_ACCT";

        // ANO-005: Null required fields
        if (isBlank(acct.getBorrowerId())) {
            issues.add(new DataQualityIssue(Severity.HIGH, table, id,
                    "BORR_ID", "Required borrower ID is null/blank", acct.getBorrowerId()));
        }
        if (isBlank(acct.getProductCode())) {
            issues.add(new DataQualityIssue(Severity.HIGH, table, id,
                    "PROD_CD", "Required product code is null/blank", acct.getProductCode()));
        }

        // ANO-003: Numeric parsing safety for financial amounts
        validateAmountField(issues, table, id, "LN_ORIG_AMT", acct.getOriginalAmount());
        validateAmountField(issues, table, id, "LN_CURR_BAL", acct.getCurrentBalance());
        validateAmountField(issues, table, id, "LN_PMT_AMT", acct.getMonthlyPayment());
        validateAmountField(issues, table, id, "LN_ESCROW_BAL", acct.getEscrowBalance());
        validateAmountField(issues, table, id, "PROP_APRS_VAL", acct.getAppraisedValue());
        validateDecimalField(issues, table, id, "LN_INT_RT", acct.getInterestRate());
        validateDecimalField(issues, table, id, "LN_LTV_PCT", acct.getLtvPercent());
        validateIntField(issues, table, id, "LN_TERM_MOS", acct.getTermMonths());
        validateIntField(issues, table, id, "LN_DLQ_DAYS", acct.getDelinquencyDays());

        // ANO-004: Delinquency days vs. loan status inconsistency
        if (!isBlank(acct.getDelinquencyDays()) && !isBlank(acct.getStatusCode())) {
            Integer dlqDays = safeParseInt(acct.getDelinquencyDays());
            if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
                issues.add(new DataQualityIssue(Severity.HIGH, table, id,
                        "LN_DLQ_DAYS/LN_STAT_CD",
                        "Loan has " + dlqDays + " delinquency days but status is ACT (Active)",
                        acct.getDelinquencyDays() + " / " + acct.getStatusCode()));
            }
        }

        // Validate status code is known
        if (!isBlank(acct.getStatusCode()) && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            issues.add(new DataQualityIssue(Severity.MEDIUM, table, id,
                    "LN_STAT_CD", "Unknown loan status code", acct.getStatusCode()));
        }
        if (!isBlank(acct.getPropertyType()) && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            issues.add(new DataQualityIssue(Severity.MEDIUM, table, id,
                    "PROP_TYP_CD", "Unknown property type code", acct.getPropertyType()));
        }

        // ANO-008: Date fields
        validateDateField(issues, table, id, "LN_ORIG_DT", acct.getOriginationDate());
        validateDateField(issues, table, id, "LN_MAT_DT", acct.getMaturityDate());
        validateDateField(issues, table, id, "LN_1ST_PMT_DT", acct.getFirstPaymentDate());
        validateDateField(issues, table, id, "LN_NXT_PMT_DT", acct.getNextPaymentDate());

        // Logical date range: maturity must be after origination
        LocalDate origDate = safeParseLegacyDate(acct.getOriginationDate());
        LocalDate matDate = safeParseLegacyDate(acct.getMaturityDate());
        if (origDate != null && matDate != null && !matDate.isAfter(origDate)) {
            issues.add(new DataQualityIssue(Severity.HIGH, table, id,
                    "LN_ORIG_DT/LN_MAT_DT",
                    "Maturity date is not after origination date",
                    acct.getOriginationDate() + " / " + acct.getMaturityDate()));
        }

        logIssues(issues);
        return issues;
    }

    /**
     * Validates denormalized borrower name in loan account against the
     * authoritative borrower master record.
     */
    public List<DataQualityIssue> validateDenormalizedBorrowerName(
            LegacyLoanAccount acct, LegacyBorrower borrower) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String id = acct.getLoanAccountNumber() != null ? acct.getLoanAccountNumber() : "UNKNOWN";
        String table = "CDW_LN_ACCT";

        if (borrower == null) {
            // ANO-006: Orphaned record — borrower FK doesn't resolve
            issues.add(new DataQualityIssue(Severity.HIGH, table, id,
                    "BORR_ID",
                    "Borrower ID references non-existent borrower",
                    acct.getBorrowerId()));
        } else {
            // ANO-007: Denormalized name divergence check
            if (!safeEquals(acct.getBorrowerFirstName(), borrower.getFirstName())) {
                issues.add(new DataQualityIssue(Severity.MEDIUM, table, id,
                        "BORR_FST_NM",
                        "Denormalized first name diverges from borrower master ("
                                + borrower.getFirstName() + ")",
                        acct.getBorrowerFirstName()));
            }
            if (!safeEquals(acct.getBorrowerLastName(), borrower.getLastName())) {
                issues.add(new DataQualityIssue(Severity.MEDIUM, table, id,
                        "BORR_LST_NM",
                        "Denormalized last name diverges from borrower master ("
                                + borrower.getLastName() + ")",
                        acct.getBorrowerLastName()));
            }
        }

        logIssues(issues);
        return issues;
    }

    // =========================================================================
    // Payment validation
    // =========================================================================

    /**
     * Validates a legacy payment for numeric parsing, status codes, date logic,
     * and the critical component-sum reconciliation (ANO-001).
     */
    public List<DataQualityIssue> validatePayment(LegacyPayment pmt) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber() != null ? pmt.getPaymentSequenceNumber() : "UNKNOWN";
        String table = "CDW_PMT_HIST";

        // ANO-005: Null required fields
        if (isBlank(pmt.getLoanAccountNumber())) {
            issues.add(new DataQualityIssue(Severity.HIGH, table, id,
                    "LN_ACCT_NBR", "Required loan account number is null/blank",
                    pmt.getLoanAccountNumber()));
        }

        // ANO-003: Numeric parsing safety
        validateAmountField(issues, table, id, "PMT_AMT", pmt.getTotalAmount());
        validateAmountField(issues, table, id, "PMT_PRIN_AMT", pmt.getPrincipalAmount());
        validateAmountField(issues, table, id, "PMT_INT_AMT", pmt.getInterestAmount());
        validateAmountField(issues, table, id, "PMT_ESCROW_AMT", pmt.getEscrowAmount());
        validateAmountField(issues, table, id, "PMT_LATE_FEE", pmt.getLateFee());

        // ANO-001: Payment component sum reconciliation
        BigDecimal total = safeParseAmount(pmt.getTotalAmount());
        BigDecimal principal = safeParseAmount(pmt.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(pmt.getInterestAmount());
        BigDecimal escrow = safeParseAmount(pmt.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(pmt.getLateFee());

        if (total != null && principal != null && interest != null
                && escrow != null && lateFee != null) {
            BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
            BigDecimal discrepancy = componentSum.subtract(total).abs();
            if (discrepancy.compareTo(RECONCILIATION_TOLERANCE) > 0) {
                issues.add(new DataQualityIssue(Severity.CRITICAL, table, id,
                        "PMT_AMT",
                        "Payment components (principal+interest+escrow+late_fee=" + componentSum
                                + ") do not sum to total (" + total + "), discrepancy=" + discrepancy,
                        pmt.getTotalAmount()));
            }
        }

        // Validate status and type codes
        if (!isBlank(pmt.getTypeCode()) && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            issues.add(new DataQualityIssue(Severity.MEDIUM, table, id,
                    "PMT_TYP_CD", "Unknown payment type code", pmt.getTypeCode()));
        }
        if (!isBlank(pmt.getStatusCode()) && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            issues.add(new DataQualityIssue(Severity.MEDIUM, table, id,
                    "PMT_STAT_CD", "Unknown payment status code", pmt.getStatusCode()));
        }

        // ANO-008 & ANO-009: Date validation and late receipt detection
        validateDateField(issues, table, id, "PMT_DT", pmt.getPaymentDate());
        validateDateField(issues, table, id, "PMT_RECV_DT", pmt.getReceivedDate());
        validateDateField(issues, table, id, "PMT_PROC_DT", pmt.getProcessedDate());

        LocalDate pmtDate = safeParseLegacyDate(pmt.getPaymentDate());
        LocalDate recvDate = safeParseLegacyDate(pmt.getReceivedDate());
        if (pmtDate != null && recvDate != null && recvDate.isAfter(pmtDate)) {
            long daysLate = java.time.temporal.ChronoUnit.DAYS.between(pmtDate, recvDate);
            issues.add(new DataQualityIssue(Severity.MEDIUM, table, id,
                    "PMT_RECV_DT",
                    "Payment received " + daysLate + " days after due date",
                    pmt.getReceivedDate()));
        }

        logIssues(issues);
        return issues;
    }

    // =========================================================================
    // Safe parsing utilities — return null instead of throwing exceptions
    // =========================================================================

    /**
     * Safely parses a legacy amount string (e.g., "1,487.02") to BigDecimal.
     * Returns null if unparseable instead of throwing NumberFormatException.
     */
    public BigDecimal safeParseAmount(String amount) {
        if (amount == null || amount.isBlank()) return null;
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount: '{}'", amount);
            return null;
        }
    }

    /**
     * Safely parses a decimal string (e.g., "5.250") to BigDecimal.
     * Returns null if unparseable.
     */
    public BigDecimal safeParseDecimal(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal: '{}'", value);
            return null;
        }
    }

    /**
     * Safely parses an integer string (e.g., "360") to Integer.
     * Returns null if unparseable.
     */
    public Integer safeParseInt(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer: '{}'", value);
            return null;
        }
    }

    /**
     * Safely parses a legacy date string in MM/dd/yyyy format.
     * Returns null if the string is blank or unparseable.
     */
    public LocalDate safeParseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FMT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date: '{}'", dateStr);
            return null;
        }
    }

    // =========================================================================
    // Internal helpers
    // =========================================================================

    private void validateAmountField(List<DataQualityIssue> issues, String table,
                                     String recordId, String field, String value) {
        if (!isBlank(value) && safeParseAmount(value) == null) {
            issues.add(new DataQualityIssue(Severity.CRITICAL, table, recordId,
                    field, "Unparseable amount value", value));
        }
    }

    private void validateDecimalField(List<DataQualityIssue> issues, String table,
                                      String recordId, String field, String value) {
        if (!isBlank(value) && safeParseDecimal(value) == null) {
            issues.add(new DataQualityIssue(Severity.CRITICAL, table, recordId,
                    field, "Unparseable decimal value", value));
        }
    }

    private void validateIntField(List<DataQualityIssue> issues, String table,
                                  String recordId, String field, String value) {
        if (!isBlank(value) && safeParseInt(value) == null) {
            issues.add(new DataQualityIssue(Severity.CRITICAL, table, recordId,
                    field, "Unparseable integer value", value));
        }
    }

    private void validateDateField(List<DataQualityIssue> issues, String table,
                                   String recordId, String field, String value) {
        if (!isBlank(value) && safeParseLegacyDate(value) == null) {
            issues.add(new DataQualityIssue(Severity.MEDIUM, table, recordId,
                    field, "Unparseable date (expected MM/dd/yyyy)", value));
        }
    }

    private boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    private boolean safeEquals(String a, String b) {
        if (a == null && b == null) return true;
        if (a == null || b == null) return false;
        return a.equals(b);
    }

    private void logIssues(List<DataQualityIssue> issues) {
        for (DataQualityIssue issue : issues) {
            switch (issue.getSeverity()) {
                case CRITICAL -> log.error("DATA QUALITY: {}", issue);
                case HIGH -> log.warn("DATA QUALITY: {}", issue);
                case MEDIUM -> log.info("DATA QUALITY: {}", issue);
                case LOW -> log.debug("DATA QUALITY: {}", issue);
            }
        }
    }
}
