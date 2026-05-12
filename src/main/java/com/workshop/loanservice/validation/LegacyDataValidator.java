package com.workshop.loanservice.validation;

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

/**
 * Validates legacy CDW data at ingestion time, catching known anomaly patterns
 * (see docs/DATA_ANOMALY_REPORT.md) before they reach the API layer.
 *
 * Each validate* method returns a list of ValidationResult entries describing
 * any anomalies found. A record with validation errors can still be processed
 * (the service layer uses safe parsing with fallback defaults), but the errors
 * are logged for visibility and can be surfaced to monitoring dashboards.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Expected date format in legacy CDW tables
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    // Tolerance for payment reconciliation (floating-point rounding)
    private static final BigDecimal RECONCILIATION_TOLERANCE = new BigDecimal("0.01");

    // Valid status codes per table (ANM-010: no CHECK constraints in legacy schema)
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    /**
     * Validates a borrower record against known anomaly patterns.
     * Checks: required fields, date format, numeric parsability, status codes.
     */
    public List<ValidationResult> validateBorrower(LegacyBorrower borrower) {
        List<ValidationResult> results = new ArrayList<>();
        String recordId = borrower.getBorrowerId();

        // ANM-006: Null values in required fields
        if (isNullOrBlank(borrower.getFirstName())) {
            results.add(ValidationResult.error(recordId, "CDW_BORR_MSTR", "BORR_FST_NM",
                    "Required field is null or blank — will produce 'null' in API responses"));
        }
        if (isNullOrBlank(borrower.getLastName())) {
            results.add(ValidationResult.error(recordId, "CDW_BORR_MSTR", "BORR_LST_NM",
                    "Required field is null or blank — will produce 'null' in API responses"));
        }
        if (isNullOrBlank(borrower.getSsnEncrypted())) {
            results.add(ValidationResult.error(recordId, "CDW_BORR_MSTR", "BORR_SSN_ENCR",
                    "Required field is null or blank — identity verification will fail"));
        }

        // ANM-003: Numeric parsing — credit score
        if (!isNullOrBlank(borrower.getCreditScore())) {
            if (!isValidInteger(borrower.getCreditScore())) {
                results.add(ValidationResult.error(recordId, "CDW_BORR_MSTR", "BORR_CRDT_SCR",
                        "Non-numeric credit score: '" + borrower.getCreditScore()
                                + "' — will cause NumberFormatException"));
            } else {
                int score = Integer.parseInt(borrower.getCreditScore().trim());
                // Credit scores range 300-850
                if (score < 300 || score > 850) {
                    results.add(ValidationResult.warning(recordId, "CDW_BORR_MSTR", "BORR_CRDT_SCR",
                            "Credit score " + score + " outside valid range 300-850"));
                }
            }
        }

        // ANM-003: Numeric parsing — annual income
        if (!isNullOrBlank(borrower.getAnnualIncome())) {
            if (!isValidAmount(borrower.getAnnualIncome())) {
                results.add(ValidationResult.error(recordId, "CDW_BORR_MSTR", "BORR_ANN_INCM",
                        "Non-numeric annual income: '" + borrower.getAnnualIncome()
                                + "' — will cause NumberFormatException"));
            }
        }

        // ANM-003: Date format validation
        validateDateField(results, recordId, "CDW_BORR_MSTR", "BORR_DOB_DT", borrower.getDateOfBirth());
        validateDateField(results, recordId, "CDW_BORR_MSTR", "BORR_CRET_DT", borrower.getCreatedDate());
        validateDateField(results, recordId, "CDW_BORR_MSTR", "BORR_UPDT_DT", borrower.getUpdatedDate());

        // ANM-010: Status code validation
        if (!isNullOrBlank(borrower.getStatusCode())
                && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            results.add(ValidationResult.warning(recordId, "CDW_BORR_MSTR", "BORR_STAT_CD",
                    "Unknown status code: '" + borrower.getStatusCode()
                            + "' — expected one of " + VALID_BORROWER_STATUSES));
        }

        logResults("Borrower", recordId, results);
        return results;
    }

    /**
     * Validates a loan account record against known anomaly patterns.
     * Checks: required fields, numeric parsing, status/delinquency consistency,
     * SSN cross-reference, referential integrity placeholders.
     */
    public List<ValidationResult> validateLoanAccount(LegacyLoanAccount account,
                                                       LegacyBorrower borrower) {
        List<ValidationResult> results = new ArrayList<>();
        String recordId = account.getLoanAccountNumber();

        // ANM-001: SSN last-4 vs phone number cross-reference
        if (borrower != null
                && !isNullOrBlank(account.getBorrowerSsnLast4())
                && !isNullOrBlank(borrower.getPhoneNumber())) {
            String phoneLast4 = extractLast4Digits(borrower.getPhoneNumber());
            if (account.getBorrowerSsnLast4().equals(phoneLast4)) {
                results.add(ValidationResult.error(recordId, "CDW_LN_ACCT", "BORR_SSN_LST4",
                        "SSN last-4 '" + account.getBorrowerSsnLast4()
                                + "' matches phone last-4 — probable PII data corruption (ANM-001)"));
            }
        }

        // ANM-004: Referential integrity — borrower exists
        if (borrower == null && !isNullOrBlank(account.getBorrowerId())) {
            results.add(ValidationResult.error(recordId, "CDW_LN_ACCT", "BORR_ID",
                    "Borrower '" + account.getBorrowerId() + "' not found — orphaned loan record"));
        }

        // ANM-005: Delinquency > 0 with Active status
        if (!isNullOrBlank(account.getDelinquencyDays())
                && isValidInteger(account.getDelinquencyDays())) {
            int dlqDays = Integer.parseInt(account.getDelinquencyDays().trim());
            if (dlqDays > 0 && "ACT".equals(account.getStatusCode())) {
                results.add(ValidationResult.warning(recordId, "CDW_LN_ACCT", "LN_DLQ_DAYS",
                        "Delinquency days=" + dlqDays + " but status is ACT — "
                                + "should be flagged as delinquent (ANM-005)"));
            }
        }

        // ANM-007: Denormalized name drift check
        if (borrower != null) {
            if (!isNullOrBlank(account.getBorrowerFirstName())
                    && !account.getBorrowerFirstName().equals(borrower.getFirstName())) {
                results.add(ValidationResult.warning(recordId, "CDW_LN_ACCT", "BORR_FST_NM",
                        "Denormalized first name '" + account.getBorrowerFirstName()
                                + "' differs from master '" + borrower.getFirstName() + "' (ANM-007)"));
            }
            if (!isNullOrBlank(account.getBorrowerLastName())
                    && !account.getBorrowerLastName().equals(borrower.getLastName())) {
                results.add(ValidationResult.warning(recordId, "CDW_LN_ACCT", "BORR_LST_NM",
                        "Denormalized last name '" + account.getBorrowerLastName()
                                + "' differs from master '" + borrower.getLastName() + "' (ANM-007)"));
            }
        }

        // ANM-003: Numeric fields validation
        validateAmountField(results, recordId, "CDW_LN_ACCT", "LN_ORIG_AMT", account.getOriginalAmount());
        validateAmountField(results, recordId, "CDW_LN_ACCT", "LN_CURR_BAL", account.getCurrentBalance());
        validateAmountField(results, recordId, "CDW_LN_ACCT", "LN_PMT_AMT", account.getMonthlyPayment());
        validateAmountField(results, recordId, "CDW_LN_ACCT", "LN_ESCROW_BAL", account.getEscrowBalance());
        validateAmountField(results, recordId, "CDW_LN_ACCT", "PROP_APRS_VAL", account.getAppraisedValue());

        if (!isNullOrBlank(account.getInterestRate()) && !isValidDecimal(account.getInterestRate())) {
            results.add(ValidationResult.error(recordId, "CDW_LN_ACCT", "LN_INT_RT",
                    "Non-numeric interest rate: '" + account.getInterestRate() + "'"));
        }

        // ANM-003: Date fields
        validateDateField(results, recordId, "CDW_LN_ACCT", "LN_ORIG_DT", account.getOriginationDate());
        validateDateField(results, recordId, "CDW_LN_ACCT", "LN_MAT_DT", account.getMaturityDate());

        // ANM-010: Status code validation
        if (!isNullOrBlank(account.getStatusCode())
                && !VALID_LOAN_STATUSES.contains(account.getStatusCode())) {
            results.add(ValidationResult.warning(recordId, "CDW_LN_ACCT", "LN_STAT_CD",
                    "Unknown loan status: '" + account.getStatusCode()
                            + "' — expected one of " + VALID_LOAN_STATUSES));
        }

        // ANM-010: Property type validation
        if (!isNullOrBlank(account.getPropertyType())
                && !VALID_PROPERTY_TYPES.contains(account.getPropertyType())) {
            results.add(ValidationResult.warning(recordId, "CDW_LN_ACCT", "PROP_TYP_CD",
                    "Unknown property type: '" + account.getPropertyType()
                            + "' — expected one of " + VALID_PROPERTY_TYPES));
        }

        logResults("LoanAccount", recordId, results);
        return results;
    }

    /**
     * Validates a payment record against known anomaly patterns.
     * Checks: numeric parsing, component reconciliation, date consistency, status codes.
     */
    public List<ValidationResult> validatePayment(LegacyPayment payment) {
        List<ValidationResult> results = new ArrayList<>();
        String recordId = payment.getPaymentSequenceNumber();

        // ANM-003: Numeric fields
        validateAmountField(results, recordId, "CDW_PMT_HIST", "PMT_AMT", payment.getTotalAmount());
        validateAmountField(results, recordId, "CDW_PMT_HIST", "PMT_PRIN_AMT", payment.getPrincipalAmount());
        validateAmountField(results, recordId, "CDW_PMT_HIST", "PMT_INT_AMT", payment.getInterestAmount());
        validateAmountField(results, recordId, "CDW_PMT_HIST", "PMT_ESCROW_AMT", payment.getEscrowAmount());
        validateAmountField(results, recordId, "CDW_PMT_HIST", "PMT_LATE_FEE", payment.getLateFee());

        // ANM-002: Payment component reconciliation
        if (isValidAmount(payment.getTotalAmount())
                && isValidAmount(payment.getPrincipalAmount())
                && isValidAmount(payment.getInterestAmount())
                && isValidAmount(payment.getEscrowAmount())
                && isValidAmount(payment.getLateFee())) {

            BigDecimal total = parseAmount(payment.getTotalAmount());
            BigDecimal componentSum = parseAmount(payment.getPrincipalAmount())
                    .add(parseAmount(payment.getInterestAmount()))
                    .add(parseAmount(payment.getEscrowAmount()))
                    .add(parseAmount(payment.getLateFee()));

            BigDecimal discrepancy = componentSum.subtract(total).abs();
            if (discrepancy.compareTo(RECONCILIATION_TOLERANCE) > 0) {
                results.add(ValidationResult.error(recordId, "CDW_PMT_HIST", "PMT_AMT",
                        "Payment components do not reconcile: total=" + total
                                + ", component sum=" + componentSum
                                + ", discrepancy=" + discrepancy + " (ANM-002)"));
            }
        }

        // ANM-009: Late payment date consistency
        if (!isNullOrBlank(payment.getPaymentDate())
                && !isNullOrBlank(payment.getReceivedDate())
                && isValidDate(payment.getPaymentDate())
                && isValidDate(payment.getReceivedDate())) {
            LocalDate dueDate = parseDate(payment.getPaymentDate());
            LocalDate receivedDate = parseDate(payment.getReceivedDate());
            long daysLate = java.time.temporal.ChronoUnit.DAYS.between(dueDate, receivedDate);

            // If received more than 15 days after due date and no late fee
            if (daysLate > 15
                    && isValidAmount(payment.getLateFee())
                    && parseAmount(payment.getLateFee()).compareTo(BigDecimal.ZERO) == 0) {
                results.add(ValidationResult.warning(recordId, "CDW_PMT_HIST", "PMT_LATE_FEE",
                        "Payment received " + daysLate + " days late but no late fee assessed (ANM-009)"));
            }
        }

        // ANM-003: Date fields
        validateDateField(results, recordId, "CDW_PMT_HIST", "PMT_DT", payment.getPaymentDate());
        validateDateField(results, recordId, "CDW_PMT_HIST", "PMT_RECV_DT", payment.getReceivedDate());
        validateDateField(results, recordId, "CDW_PMT_HIST", "PMT_PROC_DT", payment.getProcessedDate());

        // ANM-010: Status and type code validation
        if (!isNullOrBlank(payment.getTypeCode())
                && !VALID_PAYMENT_TYPES.contains(payment.getTypeCode())) {
            results.add(ValidationResult.warning(recordId, "CDW_PMT_HIST", "PMT_TYP_CD",
                    "Unknown payment type: '" + payment.getTypeCode()
                            + "' — expected one of " + VALID_PAYMENT_TYPES));
        }
        if (!isNullOrBlank(payment.getStatusCode())
                && !VALID_PAYMENT_STATUSES.contains(payment.getStatusCode())) {
            results.add(ValidationResult.warning(recordId, "CDW_PMT_HIST", "PMT_STAT_CD",
                    "Unknown payment status: '" + payment.getStatusCode()
                            + "' — expected one of " + VALID_PAYMENT_STATUSES));
        }

        // ANM-004: Referential integrity — loan account number present
        if (isNullOrBlank(payment.getLoanAccountNumber())) {
            results.add(ValidationResult.error(recordId, "CDW_PMT_HIST", "LN_ACCT_NBR",
                    "Required loan account number is null — orphaned payment record"));
        }

        logResults("Payment", recordId, results);
        return results;
    }

    // =========================================================================
    // Helper methods for type validation and parsing
    // =========================================================================

    /** Checks if a string can be parsed as a comma-separated amount (e.g., "1,487.02"). */
    public boolean isValidAmount(String value) {
        if (isNullOrBlank(value)) return false;
        try {
            new BigDecimal(value.replace(",", "").trim());
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    /** Checks if a string can be parsed as a plain decimal (e.g., "4.750"). */
    public boolean isValidDecimal(String value) {
        if (isNullOrBlank(value)) return false;
        try {
            new BigDecimal(value.trim());
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    /** Checks if a string can be parsed as an integer (e.g., "745"). */
    public boolean isValidInteger(String value) {
        if (isNullOrBlank(value)) return false;
        try {
            Integer.parseInt(value.trim());
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    /** Checks if a string matches the legacy MM/dd/yyyy date format. */
    public boolean isValidDate(String value) {
        if (isNullOrBlank(value)) return false;
        try {
            LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
            return true;
        } catch (DateTimeParseException e) {
            return false;
        }
    }

    /** Safely parses an amount string, returning BigDecimal.ZERO on failure. */
    public BigDecimal parseAmount(String value) {
        if (isNullOrBlank(value)) return BigDecimal.ZERO;
        try {
            return new BigDecimal(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            return BigDecimal.ZERO;
        }
    }

    /** Safely parses a date string, returning null on failure. */
    public LocalDate parseDate(String value) {
        if (isNullOrBlank(value)) return null;
        try {
            return LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    /** Extracts the last 4 digits from a phone number string (e.g., "217-555-0142" → "0142"). */
    public String extractLast4Digits(String phone) {
        if (isNullOrBlank(phone)) return null;
        String digitsOnly = phone.replaceAll("[^0-9]", "");
        if (digitsOnly.length() < 4) return null;
        return digitsOnly.substring(digitsOnly.length() - 4);
    }

    private boolean isNullOrBlank(String value) {
        return value == null || value.isBlank();
    }

    private void validateDateField(List<ValidationResult> results, String recordId,
                                   String table, String column, String value) {
        if (!isNullOrBlank(value) && !isValidDate(value)) {
            results.add(ValidationResult.error(recordId, table, column,
                    "Invalid date format: '" + value + "' — expected MM/DD/YYYY"));
        }
    }

    private void validateAmountField(List<ValidationResult> results, String recordId,
                                     String table, String column, String value) {
        if (!isNullOrBlank(value) && !isValidAmount(value)) {
            results.add(ValidationResult.error(recordId, table, column,
                    "Non-numeric amount: '" + value + "' — will cause NumberFormatException"));
        }
    }

    private void logResults(String entityType, String recordId, List<ValidationResult> results) {
        if (results.isEmpty()) return;
        long errorCount = results.stream().filter(r -> r.severity() == ValidationResult.Severity.ERROR).count();
        long warnCount = results.stream().filter(r -> r.severity() == ValidationResult.Severity.WARNING).count();
        if (errorCount > 0) {
            log.error("Validation for {} [{}]: {} error(s), {} warning(s)", entityType, recordId, errorCount, warnCount);
        } else {
            log.warn("Validation for {} [{}]: {} warning(s)", entityType, recordId, warnCount);
        }
        for (ValidationResult r : results) {
            if (r.severity() == ValidationResult.Severity.ERROR) {
                log.error("  [{}] {}.{}: {}", recordId, r.table(), r.column(), r.message());
            } else {
                log.warn("  [{}] {}.{}: {}", recordId, r.table(), r.column(), r.message());
            }
        }
    }
}
