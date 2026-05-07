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
import java.util.regex.Pattern;

/**
 * Validates legacy CDW data at ingestion time, catching anomalies
 * before they cause runtime failures or produce incorrect API responses.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final Pattern NUMERIC_AMOUNT_PATTERN =
            Pattern.compile("^-?\\d{1,3}(,\\d{3})*(\\.\\d+)?$");

    private static final Pattern INTEGER_PATTERN =
            Pattern.compile("^-?\\d+$");

    private static final Set<String> VALID_LOAN_STATUSES =
            Set.of("ACT", "CLO", "DFT", "FRB");

    private static final Set<String> VALID_PAYMENT_STATUSES =
            Set.of("PST", "REV", "NSF", "PND");

    private static final Set<String> VALID_PAYMENT_TYPES =
            Set.of("REG", "EXT", "PRT", "PRE");

    private static final Set<String> VALID_PROPERTY_TYPES =
            Set.of("SFR", "CND", "MFR", "TWN");

    private static final Set<String> VALID_BORROWER_STATUSES =
            Set.of("ACT", "INA", "SUS", "DEC");

    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.01");

    // --- Public validation methods ---

    public List<DataQualityIssue> validateBorrower(LegacyBorrower borrower) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (isBlank(borrower.getFirstName())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_BORR_MSTR", "BORR_FST_NM", id,
                    "Required field is null or blank", borrower.getFirstName()));
        }

        if (isBlank(borrower.getLastName())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_BORR_MSTR", "BORR_LST_NM", id,
                    "Required field is null or blank", borrower.getLastName()));
        }

        if (!isBlank(borrower.getCreditScore()) && !isValidInteger(borrower.getCreditScore())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_BORR_MSTR", "BORR_CRDT_SCR", id,
                    "Credit score is not a valid integer", borrower.getCreditScore()));
        } else if (!isBlank(borrower.getCreditScore())) {
            try {
                int score = Integer.parseInt(borrower.getCreditScore().trim());
                if (score < 300 || score > 850) {
                    issues.add(new DataQualityIssue(DataQualityIssue.Severity.MEDIUM,
                            "CDW_BORR_MSTR", "BORR_CRDT_SCR", id,
                            "Credit score outside valid range (300-850)", borrower.getCreditScore()));
                }
            } catch (NumberFormatException e) {
                issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                        "CDW_BORR_MSTR", "BORR_CRDT_SCR", id,
                        "Credit score parse failure", borrower.getCreditScore()));
            }
        }

        if (!isBlank(borrower.getAnnualIncome()) && !isValidAmount(borrower.getAnnualIncome())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_BORR_MSTR", "BORR_ANN_INCM", id,
                    "Annual income is not a valid numeric amount", borrower.getAnnualIncome()));
        }

        if (!isBlank(borrower.getDateOfBirth()) && !isValidDate(borrower.getDateOfBirth())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_BORR_MSTR", "BORR_DOB_DT", id,
                    "Date of birth is not valid MM/DD/YYYY format", borrower.getDateOfBirth()));
        }

        if (!isBlank(borrower.getCreatedDate()) && !isValidDate(borrower.getCreatedDate())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.MEDIUM,
                    "CDW_BORR_MSTR", "BORR_CRET_DT", id,
                    "Created date is not valid MM/DD/YYYY format", borrower.getCreatedDate()));
        }

        if (!isBlank(borrower.getStatusCode())
                && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.MEDIUM,
                    "CDW_BORR_MSTR", "BORR_STAT_CD", id,
                    "Invalid borrower status code", borrower.getStatusCode()));
        }

        logIssues(issues);
        return issues;
    }

    public List<DataQualityIssue> validateLoanAccount(LegacyLoanAccount account) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        if (isBlank(account.getBorrowerId())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.CRITICAL,
                    "CDW_LN_ACCT", "BORR_ID", id,
                    "Required borrower ID is null or blank", account.getBorrowerId()));
        }

        if (!isBlank(account.getOriginalAmount()) && !isValidAmount(account.getOriginalAmount())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_LN_ACCT", "LN_ORIG_AMT", id,
                    "Original amount is not a valid numeric format", account.getOriginalAmount()));
        }

        if (!isBlank(account.getCurrentBalance()) && !isValidAmount(account.getCurrentBalance())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_LN_ACCT", "LN_CURR_BAL", id,
                    "Current balance is not a valid numeric format", account.getCurrentBalance()));
        }

        if (!isBlank(account.getInterestRate()) && !isValidDecimal(account.getInterestRate())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_LN_ACCT", "LN_INT_RT", id,
                    "Interest rate is not a valid decimal", account.getInterestRate()));
        }

        if (!isBlank(account.getMonthlyPayment()) && !isValidAmount(account.getMonthlyPayment())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_LN_ACCT", "LN_PMT_AMT", id,
                    "Monthly payment is not a valid numeric format", account.getMonthlyPayment()));
        }

        if (!isBlank(account.getStatusCode()) && !VALID_LOAN_STATUSES.contains(account.getStatusCode())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.MEDIUM,
                    "CDW_LN_ACCT", "LN_STAT_CD", id,
                    "Invalid loan status code", account.getStatusCode()));
        }

        if (!isBlank(account.getOriginationDate()) && !isValidDate(account.getOriginationDate())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_LN_ACCT", "LN_ORIG_DT", id,
                    "Origination date is not valid MM/DD/YYYY format", account.getOriginationDate()));
        }

        if (!isBlank(account.getMaturityDate()) && !isValidDate(account.getMaturityDate())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_LN_ACCT", "LN_MAT_DT", id,
                    "Maturity date is not valid MM/DD/YYYY format", account.getMaturityDate()));
        }

        if (!isBlank(account.getPropertyType()) && !VALID_PROPERTY_TYPES.contains(account.getPropertyType())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.LOW,
                    "CDW_LN_ACCT", "PROP_TYP_CD", id,
                    "Invalid property type code", account.getPropertyType()));
        }

        validateDelinquencyConsistency(account, issues);

        logIssues(issues);
        return issues;
    }

    public List<DataQualityIssue> validatePayment(LegacyPayment payment) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        if (isBlank(payment.getLoanAccountNumber())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.CRITICAL,
                    "CDW_PMT_HIST", "LN_ACCT_NBR", id,
                    "Required loan account number is null or blank", payment.getLoanAccountNumber()));
        }

        if (!isBlank(payment.getTotalAmount()) && !isValidAmount(payment.getTotalAmount())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_PMT_HIST", "PMT_AMT", id,
                    "Total amount is not a valid numeric format", payment.getTotalAmount()));
        }

        if (!isBlank(payment.getPrincipalAmount()) && !isValidAmount(payment.getPrincipalAmount())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_PMT_HIST", "PMT_PRIN_AMT", id,
                    "Principal amount is not a valid numeric format", payment.getPrincipalAmount()));
        }

        if (!isBlank(payment.getInterestAmount()) && !isValidAmount(payment.getInterestAmount())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_PMT_HIST", "PMT_INT_AMT", id,
                    "Interest amount is not a valid numeric format", payment.getInterestAmount()));
        }

        if (!isBlank(payment.getStatusCode()) && !VALID_PAYMENT_STATUSES.contains(payment.getStatusCode())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.MEDIUM,
                    "CDW_PMT_HIST", "PMT_STAT_CD", id,
                    "Invalid payment status code", payment.getStatusCode()));
        }

        if (!isBlank(payment.getTypeCode()) && !VALID_PAYMENT_TYPES.contains(payment.getTypeCode())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.MEDIUM,
                    "CDW_PMT_HIST", "PMT_TYP_CD", id,
                    "Invalid payment type code", payment.getTypeCode()));
        }

        if (!isBlank(payment.getPaymentDate()) && !isValidDate(payment.getPaymentDate())) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_PMT_HIST", "PMT_DT", id,
                    "Payment date is not valid MM/DD/YYYY format", payment.getPaymentDate()));
        }

        validatePaymentComponentSum(payment, issues);

        logIssues(issues);
        return issues;
    }

    // --- Safe parsing methods with fallback defaults ---

    public BigDecimal safeParseAmount(String amount, String table, String column,
                                      String recordId, List<DataQualityIssue> issues) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        String sanitized = sanitizeNumeric(amount);
        try {
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    table, column, recordId,
                    "Failed to parse amount: " + e.getMessage(), amount));
            log.warn("Parse failure for {}.{} record={}: '{}' -> fallback to ZERO",
                    table, column, recordId, amount);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal safeParseDecimal(String value, String table, String column,
                                       String recordId, List<DataQualityIssue> issues) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        String sanitized = value.trim().replaceAll("[%$\\s]", "");
        try {
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    table, column, recordId,
                    "Failed to parse decimal: " + e.getMessage(), value));
            log.warn("Parse failure for {}.{} record={}: '{}' -> fallback to ZERO",
                    table, column, recordId, value);
            return BigDecimal.ZERO;
        }
    }

    public Integer safeParseInteger(String value, String table, String column,
                                    String recordId, List<DataQualityIssue> issues) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String sanitized = value.trim().replaceAll("[,\\s]", "");
        try {
            return Integer.parseInt(sanitized);
        } catch (NumberFormatException e) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    table, column, recordId,
                    "Failed to parse integer: " + e.getMessage(), value));
            log.warn("Parse failure for {}.{} record={}: '{}' -> fallback to null",
                    table, column, recordId, value);
            return null;
        }
    }

    public LocalDate safeParseDate(String value, String table, String column,
                                   String recordId, List<DataQualityIssue> issues) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    table, column, recordId,
                    "Failed to parse date (expected MM/DD/YYYY): " + e.getMessage(), value));
            log.warn("Date parse failure for {}.{} record={}: '{}' -> fallback to null",
                    table, column, recordId, value);
            return null;
        }
    }

    // --- Private helper methods ---

    private void validatePaymentComponentSum(LegacyPayment payment, List<DataQualityIssue> issues) {
        String id = payment.getPaymentSequenceNumber();
        try {
            BigDecimal total = parseAmountOrNull(payment.getTotalAmount());
            BigDecimal principal = parseAmountOrNull(payment.getPrincipalAmount());
            BigDecimal interest = parseAmountOrNull(payment.getInterestAmount());
            BigDecimal escrow = parseAmountOrNull(payment.getEscrowAmount());
            BigDecimal lateFee = parseAmountOrNull(payment.getLateFee());

            if (total == null || principal == null || interest == null
                    || escrow == null || lateFee == null) {
                return;
            }

            BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
            BigDecimal difference = total.subtract(componentSum).abs();

            if (difference.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
                issues.add(new DataQualityIssue(DataQualityIssue.Severity.CRITICAL,
                        "CDW_PMT_HIST", "PMT_AMT", id,
                        String.format("Payment components sum (%s) does not match total (%s), diff=%s",
                                componentSum.setScale(2, RoundingMode.HALF_UP),
                                total.setScale(2, RoundingMode.HALF_UP),
                                difference.setScale(2, RoundingMode.HALF_UP)),
                        payment.getTotalAmount()));
            }
        } catch (NumberFormatException e) {
            // Format issues already caught by individual field validation
        }
    }

    private void validateDelinquencyConsistency(LegacyLoanAccount account, List<DataQualityIssue> issues) {
        String id = account.getLoanAccountNumber();
        if (isBlank(account.getDelinquencyDays()) || isBlank(account.getStatusCode())) {
            return;
        }
        try {
            int days = Integer.parseInt(account.getDelinquencyDays().trim());
            if (days > 0 && "ACT".equals(account.getStatusCode())) {
                issues.add(new DataQualityIssue(DataQualityIssue.Severity.MEDIUM,
                        "CDW_LN_ACCT", "LN_DLQ_DAYS", id,
                        String.format("Delinquency days=%d but status is ACT (Active)", days),
                        account.getDelinquencyDays()));
            }
        } catch (NumberFormatException e) {
            issues.add(new DataQualityIssue(DataQualityIssue.Severity.HIGH,
                    "CDW_LN_ACCT", "LN_DLQ_DAYS", id,
                    "Delinquency days is not a valid integer", account.getDelinquencyDays()));
        }
    }

    private BigDecimal parseAmountOrNull(String amount) {
        if (amount == null || amount.isBlank()) return null;
        return new BigDecimal(sanitizeNumeric(amount));
    }

    private String sanitizeNumeric(String value) {
        return value.trim().replaceAll("[$%\\s]", "").replace(",", "");
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private boolean isValidAmount(String value) {
        if (value == null || value.isBlank()) return false;
        String sanitized = value.trim().replaceAll("[$%\\s]", "");
        return NUMERIC_AMOUNT_PATTERN.matcher(sanitized).matches();
    }

    private boolean isValidDecimal(String value) {
        if (value == null || value.isBlank()) return false;
        String sanitized = value.trim().replaceAll("[$%\\s]", "");
        try {
            new BigDecimal(sanitized);
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    private boolean isValidInteger(String value) {
        if (value == null || value.isBlank()) return false;
        return INTEGER_PATTERN.matcher(value.trim()).matches();
    }

    private boolean isValidDate(String value) {
        if (value == null || value.isBlank()) return false;
        try {
            LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
            return true;
        } catch (DateTimeParseException e) {
            return false;
        }
    }

    private void logIssues(List<DataQualityIssue> issues) {
        for (DataQualityIssue issue : issues) {
            switch (issue.getSeverity()) {
                case CRITICAL -> log.error("DATA QUALITY CRITICAL: {}", issue);
                case HIGH -> log.warn("DATA QUALITY HIGH: {}", issue);
                case MEDIUM -> log.info("DATA QUALITY MEDIUM: {}", issue);
                case LOW -> log.debug("DATA QUALITY LOW: {}", issue);
            }
        }
    }
}
