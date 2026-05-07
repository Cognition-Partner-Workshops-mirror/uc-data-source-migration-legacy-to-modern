package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.ValidationResult.Severity;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Validates legacy CDW data at ingestion time, catching anomalies documented
 * in docs/DATA_ANOMALY_REPORT.md before they propagate to API consumers.
 *
 * Each validation method corresponds to one or more ANOM-xxx entries.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    /** Legacy date format used across all CDW tables. */
    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    /** Valid loan status codes per the legacy schema. */
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");

    /** Valid payment type codes. */
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");

    /** Valid payment status codes. */
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");

    /** Valid borrower status codes. */
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");

    /** Valid property type codes. */
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    /** Tolerance for payment arithmetic check (cents). */
    private static final BigDecimal ARITHMETIC_TOLERANCE = new BigDecimal("0.01");

    // =========================================================================
    // ANOM-001: Payment component arithmetic mismatch
    // =========================================================================

    /**
     * Validates that payment component amounts sum to the total.
     * Catches ANOM-001: principal + interest + escrow + lateFee should equal totalAmount.
     */
    public void validatePaymentArithmetic(LegacyPayment payment, ValidationResult result) {
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        // Skip if any amount failed to parse (already flagged by ANOM-002 checks)
        if (total == null || principal == null || interest == null
                || escrow == null || lateFee == null) {
            return;
        }

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal delta = total.subtract(componentSum).abs();

        if (delta.compareTo(ARITHMETIC_TOLERANCE) > 0) {
            String desc = String.format(
                    "Payment total (%s) != principal(%s) + interest(%s) + escrow(%s) + lateFee(%s) = %s; delta=%s",
                    total, principal, interest, escrow, lateFee, componentSum, total.subtract(componentSum));
            result.addIssue(Severity.CRITICAL, "ANOM-001",
                    payment.getPaymentSequenceNumber(), desc);
            log.warn("ANOM-001: {}", desc);
        }
    }

    // =========================================================================
    // ANOM-002: Safe numeric parsing with error handling
    // =========================================================================

    /**
     * Safely parses a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Returns null and logs a warning if the value cannot be parsed.
     * Catches ANOM-002: numeric strings with commas that may contain non-numeric data.
     */
    public BigDecimal safeParseAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("ANOM-002: Failed to parse amount '{}': {}", amount, e.getMessage());
            return null;
        }
    }

    /**
     * Safely parses a legacy decimal string (e.g., "4.750") to BigDecimal.
     * Returns null on parse failure.
     */
    public BigDecimal safeParseDecimal(String value) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("ANOM-002: Failed to parse decimal '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Safely parses a legacy integer string (e.g., "745") to Integer.
     * Returns null on parse failure.
     */
    public Integer safeParseInteger(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("ANOM-002: Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Validates that all numeric fields on a borrower record are parseable.
     */
    public void validateBorrowerNumericFields(LegacyBorrower borrower, ValidationResult result) {
        // Credit score
        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            Integer score = safeParseInteger(borrower.getCreditScore());
            if (score == null) {
                result.addIssue(Severity.CRITICAL, "ANOM-002", borrower.getBorrowerId(),
                        "Unparseable credit score: '" + borrower.getCreditScore() + "'");
            } else if (score < 300 || score > 850) {
                // Credit score range validation
                result.addIssue(Severity.MEDIUM, "ANOM-002", borrower.getBorrowerId(),
                        "Credit score out of valid range (300-850): " + score);
            }
        }

        // Annual income
        if (borrower.getAnnualIncome() != null && !borrower.getAnnualIncome().isBlank()) {
            BigDecimal income = safeParseAmount(borrower.getAnnualIncome());
            if (income == null) {
                result.addIssue(Severity.CRITICAL, "ANOM-002", borrower.getBorrowerId(),
                        "Unparseable annual income: '" + borrower.getAnnualIncome() + "'");
            } else if (income.compareTo(BigDecimal.ZERO) < 0) {
                result.addIssue(Severity.HIGH, "ANOM-002", borrower.getBorrowerId(),
                        "Negative annual income: " + income);
            }
        }
    }

    /**
     * Validates that all numeric fields on a loan account record are parseable.
     */
    public void validateLoanAccountNumericFields(LegacyLoanAccount account, ValidationResult result) {
        String id = account.getLoanAccountNumber();

        // Original amount
        validateAmountField(account.getOriginalAmount(), "LN_ORIG_AMT", id, result);
        // Current balance
        validateAmountField(account.getCurrentBalance(), "LN_CURR_BAL", id, result);
        // Interest rate
        if (account.getInterestRate() != null && !account.getInterestRate().isBlank()) {
            BigDecimal rate = safeParseDecimal(account.getInterestRate());
            if (rate == null) {
                result.addIssue(Severity.CRITICAL, "ANOM-002", id,
                        "Unparseable interest rate: '" + account.getInterestRate() + "'");
            } else if (rate.compareTo(BigDecimal.ZERO) <= 0 || rate.compareTo(new BigDecimal("30")) > 0) {
                result.addIssue(Severity.MEDIUM, "ANOM-002", id,
                        "Interest rate out of expected range (0-30%): " + rate);
            }
        }
        // Monthly payment
        validateAmountField(account.getMonthlyPayment(), "LN_PMT_AMT", id, result);
        // Escrow balance
        validateAmountField(account.getEscrowBalance(), "LN_ESCROW_BAL", id, result);
        // LTV percent
        if (account.getLtvPercent() != null && !account.getLtvPercent().isBlank()) {
            BigDecimal ltv = safeParseDecimal(account.getLtvPercent());
            if (ltv == null) {
                result.addIssue(Severity.CRITICAL, "ANOM-002", id,
                        "Unparseable LTV percent: '" + account.getLtvPercent() + "'");
            }
        }
        // Appraised value
        validateAmountField(account.getAppraisedValue(), "PROP_APRS_VAL", id, result);
    }

    /**
     * Validates that all numeric fields on a payment record are parseable.
     */
    public void validatePaymentNumericFields(LegacyPayment payment, ValidationResult result) {
        String id = payment.getPaymentSequenceNumber();
        validateAmountField(payment.getTotalAmount(), "PMT_AMT", id, result);
        validateAmountField(payment.getPrincipalAmount(), "PMT_PRIN_AMT", id, result);
        validateAmountField(payment.getInterestAmount(), "PMT_INT_AMT", id, result);
        validateAmountField(payment.getEscrowAmount(), "PMT_ESCROW_AMT", id, result);
        validateAmountField(payment.getLateFee(), "PMT_LATE_FEE", id, result);
    }

    // =========================================================================
    // ANOM-003: Referential integrity (orphaned records)
    // =========================================================================

    /**
     * Validates referential integrity across all tables.
     * Catches ANOM-003: orphaned loan accounts and payments.
     */
    public void validateReferentialIntegrity(
            List<LegacyBorrower> borrowers,
            List<LegacyLoanProduct> products,
            List<LegacyLoanAccount> accounts,
            List<LegacyPayment> payments,
            ValidationResult result) {

        Set<String> borrowerIds = borrowers.stream()
                .map(LegacyBorrower::getBorrowerId)
                .collect(Collectors.toSet());
        Set<String> productCodes = products.stream()
                .map(LegacyLoanProduct::getProductCode)
                .collect(Collectors.toSet());
        Set<String> accountNumbers = accounts.stream()
                .map(LegacyLoanAccount::getLoanAccountNumber)
                .collect(Collectors.toSet());

        // Check loan accounts reference valid borrowers and products
        for (LegacyLoanAccount account : accounts) {
            if (account.getBorrowerId() != null && !borrowerIds.contains(account.getBorrowerId())) {
                result.addIssue(Severity.HIGH, "ANOM-003", account.getLoanAccountNumber(),
                        "Orphaned loan account: BORR_ID '" + account.getBorrowerId()
                                + "' not found in CDW_BORR_MSTR");
                log.warn("ANOM-003: Orphaned loan {} references missing borrower {}",
                        account.getLoanAccountNumber(), account.getBorrowerId());
            }
            if (account.getProductCode() != null && !productCodes.contains(account.getProductCode())) {
                result.addIssue(Severity.HIGH, "ANOM-003", account.getLoanAccountNumber(),
                        "Orphaned loan account: PROD_CD '" + account.getProductCode()
                                + "' not found in CDW_LN_PROD");
                log.warn("ANOM-003: Loan {} references missing product {}",
                        account.getLoanAccountNumber(), account.getProductCode());
            }
        }

        // Check payments reference valid loan accounts
        for (LegacyPayment payment : payments) {
            if (payment.getLoanAccountNumber() != null
                    && !accountNumbers.contains(payment.getLoanAccountNumber())) {
                result.addIssue(Severity.HIGH, "ANOM-003", payment.getPaymentSequenceNumber(),
                        "Orphaned payment: LN_ACCT_NBR '" + payment.getLoanAccountNumber()
                                + "' not found in CDW_LN_ACCT");
                log.warn("ANOM-003: Payment {} references missing loan {}",
                        payment.getPaymentSequenceNumber(), payment.getLoanAccountNumber());
            }
        }
    }

    // =========================================================================
    // ANOM-004: Date format validation
    // =========================================================================

    /**
     * Safely parses a legacy MM/DD/YYYY date string to LocalDate.
     * Returns null on parse failure and logs a warning.
     * Catches ANOM-004: unparseable or malformed dates.
     */
    public LocalDate safeParseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("ANOM-004: Failed to parse date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    /**
     * Formats a legacy date string to ISO-8601, returning the original string if unparseable.
     */
    public String formatDateToIso(String legacyDate) {
        LocalDate parsed = safeParseLegacyDate(legacyDate);
        return parsed != null ? parsed.toString() : legacyDate;
    }

    /**
     * Validates all date fields on a borrower record.
     */
    public void validateBorrowerDateFields(LegacyBorrower borrower, ValidationResult result) {
        validateDateField(borrower.getDateOfBirth(), "BORR_DOB_DT", borrower.getBorrowerId(), result);
        validateDateField(borrower.getCreatedDate(), "BORR_CRET_DT", borrower.getBorrowerId(), result);
        validateDateField(borrower.getUpdatedDate(), "BORR_UPDT_DT", borrower.getBorrowerId(), result);
    }

    /**
     * Validates all date fields on a loan account record.
     */
    public void validateLoanAccountDateFields(LegacyLoanAccount account, ValidationResult result) {
        String id = account.getLoanAccountNumber();
        validateDateField(account.getOriginationDate(), "LN_ORIG_DT", id, result);
        validateDateField(account.getMaturityDate(), "LN_MAT_DT", id, result);
        validateDateField(account.getFirstPaymentDate(), "LN_1ST_PMT_DT", id, result);
        validateDateField(account.getNextPaymentDate(), "LN_NXT_PMT_DT", id, result);
        validateDateField(account.getCreatedDate(), "LN_CRET_DT", id, result);
        validateDateField(account.getUpdatedDate(), "LN_UPDT_DT", id, result);
    }

    /**
     * Validates all date fields on a payment record.
     */
    public void validatePaymentDateFields(LegacyPayment payment, ValidationResult result) {
        String id = payment.getPaymentSequenceNumber();
        validateDateField(payment.getPaymentDate(), "PMT_DT", id, result);
        validateDateField(payment.getReceivedDate(), "PMT_RECV_DT", id, result);
        validateDateField(payment.getProcessedDate(), "PMT_PROC_DT", id, result);
        validateDateField(payment.getCreatedDate(), "PMT_CRET_DT", id, result);
        validateDateField(payment.getUpdatedDate(), "PMT_UPDT_DT", id, result);
    }

    // =========================================================================
    // ANOM-005: Status / delinquency inconsistency
    // =========================================================================

    /**
     * Validates that loan status is consistent with delinquency days.
     * Catches ANOM-005: delinquent loan with ACT status.
     */
    public void validateLoanStatusConsistency(LegacyLoanAccount account, ValidationResult result) {
        Integer dlqDays = safeParseInteger(account.getDelinquencyDays());
        String status = account.getStatusCode();

        if (dlqDays != null && dlqDays > 0 && "ACT".equals(status)) {
            String desc = String.format(
                    "Loan has %d delinquency days but status is ACT (Active). "
                            + "Expected DLQ or DFT status for delinquent loans.", dlqDays);
            result.addIssue(Severity.HIGH, "ANOM-005", account.getLoanAccountNumber(), desc);
            log.warn("ANOM-005: Loan {} has {} delinquency days with ACT status",
                    account.getLoanAccountNumber(), dlqDays);
        }

        // Also validate status code is recognized
        if (status != null && !VALID_LOAN_STATUSES.contains(status)) {
            result.addIssue(Severity.HIGH, "ANOM-005", account.getLoanAccountNumber(),
                    "Unrecognized loan status code: '" + status + "'");
        }
    }

    // =========================================================================
    // ANOM-006: Late payment without late fee
    // =========================================================================

    /**
     * Validates that late payments have appropriate late fees assessed.
     * Catches ANOM-006: payment received after due date but late fee is zero.
     */
    public void validateLateFeeConsistency(LegacyPayment payment, ValidationResult result) {
        LocalDate dueDate = safeParseLegacyDate(payment.getPaymentDate());
        LocalDate receivedDate = safeParseLegacyDate(payment.getReceivedDate());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (dueDate == null || receivedDate == null || lateFee == null) {
            return; // Date/amount parse issues already flagged by other validators
        }

        // Standard grace period is typically 15 days, but flag anything received after due date
        if (receivedDate.isAfter(dueDate)
                && lateFee.compareTo(BigDecimal.ZERO) == 0) {
            long daysLate = java.time.temporal.ChronoUnit.DAYS.between(dueDate, receivedDate);
            String desc = String.format(
                    "Payment received %d days after due date (%s vs %s) but late fee is $0.00",
                    daysLate, receivedDate, dueDate);
            result.addIssue(Severity.MEDIUM, "ANOM-006",
                    payment.getPaymentSequenceNumber(), desc);
            log.warn("ANOM-006: Payment {} received {} days late with no fee",
                    payment.getPaymentSequenceNumber(), daysLate);
        }
    }

    // =========================================================================
    // ANOM-007: Denormalized data consistency
    // =========================================================================

    /**
     * Validates that denormalized borrower fields in loan accounts match the borrower master.
     * Catches ANOM-007: stale borrower data in CDW_LN_ACCT.
     */
    public void validateDenormalizedBorrowerData(
            LegacyLoanAccount account,
            Map<String, LegacyBorrower> borrowerMap,
            ValidationResult result) {

        LegacyBorrower borrower = borrowerMap.get(account.getBorrowerId());
        if (borrower == null) {
            return; // Orphaned record — already caught by ANOM-003
        }

        // Check first name match
        if (!safeEquals(account.getBorrowerFirstName(), borrower.getFirstName())) {
            result.addIssue(Severity.MEDIUM, "ANOM-007", account.getLoanAccountNumber(),
                    "Denormalized first name mismatch: loan has '"
                            + account.getBorrowerFirstName() + "', borrower master has '"
                            + borrower.getFirstName() + "'");
        }

        // Check last name match
        if (!safeEquals(account.getBorrowerLastName(), borrower.getLastName())) {
            result.addIssue(Severity.MEDIUM, "ANOM-007", account.getLoanAccountNumber(),
                    "Denormalized last name mismatch: loan has '"
                            + account.getBorrowerLastName() + "', borrower master has '"
                            + borrower.getLastName() + "'");
        }
    }

    // =========================================================================
    // ANOM-008: Null required field validation
    // =========================================================================

    /**
     * Validates that required borrower fields are not null.
     */
    public void validateBorrowerRequiredFields(LegacyBorrower borrower, ValidationResult result) {
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            result.addIssue(Severity.HIGH, "ANOM-008", id, "Required field BORR_FST_NM is null/blank");
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            result.addIssue(Severity.HIGH, "ANOM-008", id, "Required field BORR_LST_NM is null/blank");
        }
        if (borrower.getSsnEncrypted() == null || borrower.getSsnEncrypted().isBlank()) {
            result.addIssue(Severity.CRITICAL, "ANOM-008", id, "Required field BORR_SSN_ENCR is null/blank");
        }
        // Middle initial is nullable (Low severity, documented in ANOM-008)
        if (borrower.getMiddleInitial() == null) {
            result.addIssue(Severity.LOW, "ANOM-008", id,
                    "BORR_MID_INIT is null — may cause inconsistent name formatting");
        }
        // Validate borrower status code
        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            result.addIssue(Severity.MEDIUM, "ANOM-008", id,
                    "Unrecognized borrower status code: '" + borrower.getStatusCode() + "'");
        }
    }

    // =========================================================================
    // ANOM-009: Product validation
    // =========================================================================

    /**
     * Validates loan product business rules.
     * Catches ANOM-009: zero minimum amount and other product anomalies.
     */
    public void validateLoanProduct(LegacyLoanProduct product, ValidationResult result) {
        String id = product.getProductCode();

        BigDecimal minAmount = safeParseAmount(product.getMinAmount());
        BigDecimal maxAmount = safeParseAmount(product.getMaxAmount());

        if (minAmount != null && minAmount.compareTo(BigDecimal.ZERO) <= 0) {
            result.addIssue(Severity.LOW, "ANOM-009", id,
                    "Product minimum amount is zero or negative: " + minAmount);
        }

        if (minAmount != null && maxAmount != null && minAmount.compareTo(maxAmount) > 0) {
            result.addIssue(Severity.HIGH, "ANOM-009", id,
                    "Product min amount (" + minAmount + ") exceeds max amount (" + maxAmount + ")");
        }

        Integer termMonths = safeParseInteger(product.getTermMonths());
        if (termMonths != null && (termMonths <= 0 || termMonths > 600)) {
            result.addIssue(Severity.MEDIUM, "ANOM-009", id,
                    "Term months out of expected range (1-600): " + termMonths);
        }
    }

    // =========================================================================
    // Comprehensive validation runner
    // =========================================================================

    /**
     * Runs all validations across all legacy data.
     * Returns a combined ValidationResult with all detected anomalies.
     */
    public ValidationResult validateAll(
            List<LegacyBorrower> borrowers,
            List<LegacyLoanProduct> products,
            List<LegacyLoanAccount> accounts,
            List<LegacyPayment> payments) {

        ValidationResult result = new ValidationResult();

        Map<String, LegacyBorrower> borrowerMap = borrowers.stream()
                .collect(Collectors.toMap(LegacyBorrower::getBorrowerId, b -> b));

        // Validate borrowers
        for (LegacyBorrower borrower : borrowers) {
            validateBorrowerRequiredFields(borrower, result);
            validateBorrowerNumericFields(borrower, result);
            validateBorrowerDateFields(borrower, result);
        }

        // Validate products
        for (LegacyLoanProduct product : products) {
            validateLoanProduct(product, result);
        }

        // Validate loan accounts
        for (LegacyLoanAccount account : accounts) {
            validateLoanAccountNumericFields(account, result);
            validateLoanAccountDateFields(account, result);
            validateLoanStatusConsistency(account, result);
            validateDenormalizedBorrowerData(account, borrowerMap, result);
        }

        // Validate payments
        for (LegacyPayment payment : payments) {
            validatePaymentNumericFields(payment, result);
            validatePaymentDateFields(payment, result);
            validatePaymentArithmetic(payment, result);
            validateLateFeeConsistency(payment, result);
        }

        // Cross-table referential integrity
        validateReferentialIntegrity(borrowers, products, accounts, payments, result);

        log.info("Legacy data validation complete: {} issues found ({} critical, {} high, {} medium, {} low)",
                result.size(),
                result.getIssuesBySeverity(Severity.CRITICAL).size(),
                result.getIssuesBySeverity(Severity.HIGH).size(),
                result.getIssuesBySeverity(Severity.MEDIUM).size(),
                result.getIssuesBySeverity(Severity.LOW).size());

        return result;
    }

    // =========================================================================
    // Private helpers
    // =========================================================================

    /**
     * Validates a single amount field is parseable and non-negative.
     */
    private void validateAmountField(String value, String columnName, String recordId,
                                     ValidationResult result) {
        if (value != null && !value.isBlank()) {
            BigDecimal parsed = safeParseAmount(value);
            if (parsed == null) {
                result.addIssue(Severity.CRITICAL, "ANOM-002", recordId,
                        "Unparseable amount in " + columnName + ": '" + value + "'");
            } else if (parsed.compareTo(BigDecimal.ZERO) < 0) {
                result.addIssue(Severity.HIGH, "ANOM-002", recordId,
                        "Negative amount in " + columnName + ": " + parsed);
            }
        }
    }

    /**
     * Validates a single date field is parseable in MM/DD/YYYY format.
     */
    private void validateDateField(String dateStr, String columnName, String recordId,
                                   ValidationResult result) {
        if (dateStr != null && !dateStr.isBlank()) {
            LocalDate parsed = safeParseLegacyDate(dateStr);
            if (parsed == null) {
                result.addIssue(Severity.HIGH, "ANOM-004", recordId,
                        "Unparseable date in " + columnName + ": '" + dateStr + "'");
            }
        }
    }

    /**
     * Null-safe string equality check.
     */
    private boolean safeEquals(String a, String b) {
        if (a == null && b == null) return true;
        if (a == null || b == null) return false;
        return a.trim().equals(b.trim());
    }
}
