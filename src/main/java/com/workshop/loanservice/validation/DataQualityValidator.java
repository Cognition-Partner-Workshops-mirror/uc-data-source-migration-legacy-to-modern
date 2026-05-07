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
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Validates legacy CDW data at ingestion time, catching known data quality
 * anomalies before they cause runtime failures or silent corruption.
 */
@Component
public class DataQualityValidator {

    private static final Logger log = LoggerFactory.getLogger(DataQualityValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/uuuu").withResolverStyle(ResolverStyle.STRICT);

    private static final Pattern AMOUNT_PATTERN = Pattern.compile("^-?\\d{1,3}(,\\d{3})*(\\.\\d+)?$");
    private static final Pattern INTEGER_PATTERN = Pattern.compile("^-?\\d+$");

    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_BORROWER_STATUS_CODES = Set.of("ACT", "INA", "SUS", "DEC");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");

    private static final BigDecimal RECONCILIATION_TOLERANCE = new BigDecimal("0.01");

    public List<ValidationIssue> validateBorrower(LegacyBorrower borrower) {
        List<ValidationIssue> issues = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (isBlank(borrower.getFirstName())) {
            issues.add(ValidationIssue.critical("BORR_FST_NM", id, "First name is null/blank"));
        }
        if (isBlank(borrower.getLastName())) {
            issues.add(ValidationIssue.critical("BORR_LST_NM", id, "Last name is null/blank"));
        }
        if (isBlank(borrower.getStatusCode())) {
            issues.add(ValidationIssue.high("BORR_STAT_CD", id, "Status code is null/blank"));
        } else if (!VALID_BORROWER_STATUS_CODES.contains(borrower.getStatusCode())) {
            issues.add(ValidationIssue.medium("BORR_STAT_CD", id,
                    "Unknown status code: " + borrower.getStatusCode()));
        }

        validateDateField(borrower.getDateOfBirth(), "BORR_DOB_DT", id, issues);
        validateDateField(borrower.getCreatedDate(), "BORR_CRET_DT", id, issues);
        validateDateField(borrower.getUpdatedDate(), "BORR_UPDT_DT", id, issues);

        if (!isBlank(borrower.getCreditScore())) {
            if (!INTEGER_PATTERN.matcher(borrower.getCreditScore().trim()).matches()) {
                issues.add(ValidationIssue.high("BORR_CRDT_SCR", id,
                        "Credit score not parseable as integer: " + borrower.getCreditScore()));
            } else {
                int score = Integer.parseInt(borrower.getCreditScore().trim());
                if (score < 300 || score > 850) {
                    issues.add(ValidationIssue.medium("BORR_CRDT_SCR", id,
                            "Credit score out of valid range (300-850): " + score));
                }
            }
        }

        if (!isBlank(borrower.getAnnualIncome())) {
            if (!AMOUNT_PATTERN.matcher(borrower.getAnnualIncome().trim()).matches()) {
                issues.add(ValidationIssue.high("BORR_ANN_INCM", id,
                        "Annual income not parseable as amount: " + borrower.getAnnualIncome()));
            }
        }

        return issues;
    }

    public List<ValidationIssue> validateLoanAccount(LegacyLoanAccount account,
                                                     Set<String> validBorrowerIds,
                                                     Set<String> validProductCodes) {
        List<ValidationIssue> issues = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        if (isBlank(account.getBorrowerId())) {
            issues.add(ValidationIssue.critical("BORR_ID", id, "Borrower ID is null/blank"));
        } else if (!validBorrowerIds.contains(account.getBorrowerId())) {
            issues.add(ValidationIssue.critical("BORR_ID", id,
                    "Orphaned record — borrower not found: " + account.getBorrowerId()));
        }

        if (isBlank(account.getProductCode())) {
            issues.add(ValidationIssue.high("PROD_CD", id, "Product code is null/blank"));
        } else if (!validProductCodes.contains(account.getProductCode())) {
            issues.add(ValidationIssue.high("PROD_CD", id,
                    "Orphaned record — product not found: " + account.getProductCode()));
        }

        if (isBlank(account.getStatusCode())) {
            issues.add(ValidationIssue.high("LN_STAT_CD", id, "Status code is null/blank"));
        } else if (!VALID_LOAN_STATUS_CODES.contains(account.getStatusCode())) {
            issues.add(ValidationIssue.medium("LN_STAT_CD", id,
                    "Unknown loan status code: " + account.getStatusCode()));
        }

        validateAmountField(account.getOriginalAmount(), "LN_ORIG_AMT", id, issues);
        validateAmountField(account.getCurrentBalance(), "LN_CURR_BAL", id, issues);
        validateAmountField(account.getMonthlyPayment(), "LN_PMT_AMT", id, issues);
        validateAmountField(account.getEscrowBalance(), "LN_ESCROW_BAL", id, issues);
        validateAmountField(account.getAppraisedValue(), "PROP_APRS_VAL", id, issues);

        if (!isBlank(account.getInterestRate())) {
            try {
                BigDecimal rate = new BigDecimal(account.getInterestRate().trim());
                if (rate.compareTo(BigDecimal.ZERO) < 0 || rate.compareTo(new BigDecimal("30")) > 0) {
                    issues.add(ValidationIssue.medium("LN_INT_RT", id,
                            "Interest rate out of range (0-30%): " + rate));
                }
            } catch (NumberFormatException e) {
                issues.add(ValidationIssue.high("LN_INT_RT", id,
                        "Interest rate not parseable: " + account.getInterestRate()));
            }
        }

        if (!isBlank(account.getDelinquencyDays())) {
            if (!INTEGER_PATTERN.matcher(account.getDelinquencyDays().trim()).matches()) {
                issues.add(ValidationIssue.high("LN_DLQ_DAYS", id,
                        "Delinquency days not parseable as integer: " + account.getDelinquencyDays()));
            }
        }

        if (!isBlank(account.getPropertyType()) &&
                !VALID_PROPERTY_TYPE_CODES.contains(account.getPropertyType())) {
            issues.add(ValidationIssue.low("PROP_TYP_CD", id,
                    "Unknown property type code: " + account.getPropertyType()));
        }

        validateDateField(account.getOriginationDate(), "LN_ORIG_DT", id, issues);
        validateDateField(account.getMaturityDate(), "LN_MAT_DT", id, issues);
        validateDateField(account.getFirstPaymentDate(), "LN_1ST_PMT_DT", id, issues);
        validateDateField(account.getNextPaymentDate(), "LN_NXT_PMT_DT", id, issues);

        return issues;
    }

    public List<ValidationIssue> validatePayment(LegacyPayment payment,
                                                 Set<String> validLoanAccountNumbers) {
        List<ValidationIssue> issues = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        if (isBlank(payment.getLoanAccountNumber())) {
            issues.add(ValidationIssue.critical("LN_ACCT_NBR", id, "Loan account number is null/blank"));
        } else if (!validLoanAccountNumbers.contains(payment.getLoanAccountNumber())) {
            issues.add(ValidationIssue.critical("LN_ACCT_NBR", id,
                    "Orphaned record — loan account not found: " + payment.getLoanAccountNumber()));
        }

        if (isBlank(payment.getStatusCode())) {
            issues.add(ValidationIssue.high("PMT_STAT_CD", id, "Payment status is null/blank"));
        } else if (!VALID_PAYMENT_STATUS_CODES.contains(payment.getStatusCode())) {
            issues.add(ValidationIssue.medium("PMT_STAT_CD", id,
                    "Unknown payment status code: " + payment.getStatusCode()));
        }

        if (isBlank(payment.getTypeCode())) {
            issues.add(ValidationIssue.high("PMT_TYP_CD", id, "Payment type is null/blank"));
        } else if (!VALID_PAYMENT_TYPE_CODES.contains(payment.getTypeCode())) {
            issues.add(ValidationIssue.medium("PMT_TYP_CD", id,
                    "Unknown payment type code: " + payment.getTypeCode()));
        }

        validateAmountField(payment.getTotalAmount(), "PMT_AMT", id, issues);
        validateAmountField(payment.getPrincipalAmount(), "PMT_PRIN_AMT", id, issues);
        validateAmountField(payment.getInterestAmount(), "PMT_INT_AMT", id, issues);
        validateAmountField(payment.getEscrowAmount(), "PMT_ESCROW_AMT", id, issues);
        validateAmountField(payment.getLateFee(), "PMT_LATE_FEE", id, issues);

        validateDateField(payment.getPaymentDate(), "PMT_DT", id, issues);
        validateDateField(payment.getReceivedDate(), "PMT_RECV_DT", id, issues);
        validateDateField(payment.getProcessedDate(), "PMT_PROC_DT", id, issues);

        validatePaymentReconciliation(payment, id, issues);

        return issues;
    }

    /**
     * Checks that payment components sum to the total amount within tolerance.
     */
    private void validatePaymentReconciliation(LegacyPayment payment, String id,
                                               List<ValidationIssue> issues) {
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (total == null || principal == null || interest == null ||
                escrow == null || lateFee == null) {
            return;
        }

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal discrepancy = componentSum.subtract(total).abs();

        if (discrepancy.compareTo(RECONCILIATION_TOLERANCE) > 0) {
            issues.add(ValidationIssue.critical("PMT_AMT", id,
                    String.format("Payment components do not reconcile: total=%s, " +
                                    "sum(P+I+E+F)=%s, discrepancy=%s",
                            total.setScale(2, RoundingMode.HALF_UP),
                            componentSum.setScale(2, RoundingMode.HALF_UP),
                            discrepancy.setScale(2, RoundingMode.HALF_UP))));
        }
    }

    private void validateDateField(String value, String column, String recordId,
                                   List<ValidationIssue> issues) {
        if (isBlank(value)) {
            return;
        }
        try {
            LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            issues.add(ValidationIssue.medium(column, recordId,
                    "Date not parseable as MM/DD/YYYY: " + value));
        }
    }

    private void validateAmountField(String value, String column, String recordId,
                                     List<ValidationIssue> issues) {
        if (isBlank(value)) {
            return;
        }
        String trimmed = value.trim();
        if (!AMOUNT_PATTERN.matcher(trimmed).matches()) {
            issues.add(ValidationIssue.high(column, recordId,
                    "Amount not parseable as numeric: " + value));
        }
    }

    private BigDecimal safeParseAmount(String amount) {
        if (isBlank(amount)) {
            return BigDecimal.ZERO;
        }
        String trimmed = amount.trim();
        if (!AMOUNT_PATTERN.matcher(trimmed).matches()) {
            return null;
        }
        return new BigDecimal(trimmed.replace(",", ""));
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
