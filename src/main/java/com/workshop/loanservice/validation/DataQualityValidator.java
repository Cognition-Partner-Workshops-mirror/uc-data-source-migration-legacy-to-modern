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

@Component
public class DataQualityValidator {

    private static final Logger log = LoggerFactory.getLogger(DataQualityValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_EMPLOYMENT_STATUSES = Set.of("EMPLOYED", "SELF-EMP", "RETIRED", "UNEMPLOYED");
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.01");

    public List<DataQualityIssue> validateBorrower(LegacyBorrower borrower) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String context = "CDW_BORR_MSTR[" + borrower.getBorrowerId() + "]";

        if (isNullOrBlank(borrower.getFirstName())) {
            issues.add(DataQualityIssue.critical(context, "BORR_FST_NM",
                    "First name is null or blank"));
        }
        if (isNullOrBlank(borrower.getLastName())) {
            issues.add(DataQualityIssue.critical(context, "BORR_LST_NM",
                    "Last name is null or blank"));
        }

        if (!isNullOrBlank(borrower.getCreditScore())) {
            Integer score = safeParseInteger(borrower.getCreditScore());
            if (score == null) {
                issues.add(DataQualityIssue.high(context, "BORR_CRDT_SCR",
                        "Credit score is not a valid integer: '" + borrower.getCreditScore() + "'"));
            } else if (score < 300 || score > 850) {
                issues.add(DataQualityIssue.medium(context, "BORR_CRDT_SCR",
                        "Credit score out of range (300-850): " + score));
            }
        }

        if (!isNullOrBlank(borrower.getAnnualIncome())) {
            BigDecimal income = safeParseAmount(borrower.getAnnualIncome());
            if (income == null) {
                issues.add(DataQualityIssue.high(context, "BORR_ANN_INCM",
                        "Annual income is not a valid amount: '" + borrower.getAnnualIncome() + "'"));
            } else if (income.compareTo(BigDecimal.ZERO) < 0) {
                issues.add(DataQualityIssue.high(context, "BORR_ANN_INCM",
                        "Annual income is negative: " + income));
            }
        }

        if (!isNullOrBlank(borrower.getDateOfBirth())) {
            LocalDate dob = safeParseLegacyDate(borrower.getDateOfBirth());
            if (dob == null) {
                issues.add(DataQualityIssue.high(context, "BORR_DOB_DT",
                        "Date of birth is not valid MM/DD/YYYY: '" + borrower.getDateOfBirth() + "'"));
            }
        }

        if (!isNullOrBlank(borrower.getEmploymentStatus())
                && !VALID_EMPLOYMENT_STATUSES.contains(borrower.getEmploymentStatus())) {
            issues.add(DataQualityIssue.medium(context, "BORR_EMP_STAT",
                    "Unknown employment status: '" + borrower.getEmploymentStatus() + "'"));
        }

        validateLegacyDate(borrower.getCreatedDate(), context, "BORR_CRET_DT", issues);
        validateLegacyDate(borrower.getUpdatedDate(), context, "BORR_UPDT_DT", issues);

        return issues;
    }

    public List<DataQualityIssue> validateLoanAccount(LegacyLoanAccount account,
                                                       Set<String> validBorrowerIds,
                                                       Set<String> validProductCodes) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String context = "CDW_LN_ACCT[" + account.getLoanAccountNumber() + "]";

        if (!isNullOrBlank(account.getBorrowerId())
                && !validBorrowerIds.contains(account.getBorrowerId())) {
            issues.add(DataQualityIssue.critical(context, "BORR_ID",
                    "Orphaned record: borrower ID '" + account.getBorrowerId()
                            + "' not found in CDW_BORR_MSTR"));
        }

        if (!isNullOrBlank(account.getProductCode())
                && !validProductCodes.contains(account.getProductCode())) {
            issues.add(DataQualityIssue.critical(context, "PROD_CD",
                    "Orphaned record: product code '" + account.getProductCode()
                            + "' not found in CDW_LN_PROD"));
        }

        validateNumericAmount(account.getOriginalAmount(), context, "LN_ORIG_AMT", true, issues);
        validateNumericAmount(account.getCurrentBalance(), context, "LN_CURR_BAL", true, issues);
        validateNumericAmount(account.getMonthlyPayment(), context, "LN_PMT_AMT", true, issues);
        validateNumericAmount(account.getEscrowBalance(), context, "LN_ESCROW_BAL", false, issues);
        validateNumericAmount(account.getAppraisedValue(), context, "PROP_APRS_VAL", false, issues);

        if (!isNullOrBlank(account.getInterestRate())) {
            BigDecimal rate = safeParseDecimal(account.getInterestRate());
            if (rate == null) {
                issues.add(DataQualityIssue.high(context, "LN_INT_RT",
                        "Interest rate is not a valid decimal: '" + account.getInterestRate() + "'"));
            } else if (rate.compareTo(BigDecimal.ZERO) <= 0 || rate.compareTo(new BigDecimal("30")) > 0) {
                issues.add(DataQualityIssue.medium(context, "LN_INT_RT",
                        "Interest rate out of plausible range (0-30%): " + rate));
            }
        }

        if (!isNullOrBlank(account.getStatusCode())
                && !VALID_LOAN_STATUSES.contains(account.getStatusCode())) {
            issues.add(DataQualityIssue.high(context, "LN_STAT_CD",
                    "Invalid loan status code: '" + account.getStatusCode() + "'"));
        }

        if (!isNullOrBlank(account.getDelinquencyDays()) && !isNullOrBlank(account.getStatusCode())) {
            Integer dlqDays = safeParseInteger(account.getDelinquencyDays());
            if (dlqDays != null && dlqDays > 0 && "ACT".equals(account.getStatusCode())) {
                issues.add(DataQualityIssue.high(context, "LN_DLQ_DAYS",
                        "Loan has " + dlqDays + " delinquency days but status is ACT (Active)"));
            }
        }

        if (!isNullOrBlank(account.getPropertyType())
                && !VALID_PROPERTY_TYPES.contains(account.getPropertyType())) {
            issues.add(DataQualityIssue.medium(context, "PROP_TYP_CD",
                    "Unknown property type code: '" + account.getPropertyType() + "'"));
        }

        validateLegacyDate(account.getOriginationDate(), context, "LN_ORIG_DT", issues);
        validateLegacyDate(account.getMaturityDate(), context, "LN_MAT_DT", issues);

        return issues;
    }

    public List<DataQualityIssue> validatePayment(LegacyPayment payment,
                                                   Set<String> validLoanAccountNumbers) {
        List<DataQualityIssue> issues = new ArrayList<>();
        String context = "CDW_PMT_HIST[" + payment.getPaymentSequenceNumber() + "]";

        if (!isNullOrBlank(payment.getLoanAccountNumber())
                && !validLoanAccountNumbers.contains(payment.getLoanAccountNumber())) {
            issues.add(DataQualityIssue.critical(context, "LN_ACCT_NBR",
                    "Orphaned record: loan account '" + payment.getLoanAccountNumber()
                            + "' not found in CDW_LN_ACCT"));
        }

        validateNumericAmount(payment.getTotalAmount(), context, "PMT_AMT", true, issues);
        validateNumericAmount(payment.getPrincipalAmount(), context, "PMT_PRIN_AMT", false, issues);
        validateNumericAmount(payment.getInterestAmount(), context, "PMT_INT_AMT", false, issues);
        validateNumericAmount(payment.getEscrowAmount(), context, "PMT_ESCROW_AMT", false, issues);
        validateNumericAmount(payment.getLateFee(), context, "PMT_LATE_FEE", false, issues);

        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (total != null && principal != null && interest != null && escrow != null && lateFee != null) {
            BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
            BigDecimal difference = total.subtract(componentSum).abs();
            if (difference.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
                issues.add(DataQualityIssue.critical(context, "PMT_AMT",
                        "Payment components do not sum to total: total=" + total
                                + ", components=" + componentSum + ", difference=" + difference));
            }
        }

        if (!isNullOrBlank(payment.getTypeCode())
                && !VALID_PAYMENT_TYPES.contains(payment.getTypeCode())) {
            issues.add(DataQualityIssue.high(context, "PMT_TYP_CD",
                    "Invalid payment type code: '" + payment.getTypeCode() + "'"));
        }
        if (!isNullOrBlank(payment.getStatusCode())
                && !VALID_PAYMENT_STATUSES.contains(payment.getStatusCode())) {
            issues.add(DataQualityIssue.high(context, "PMT_STAT_CD",
                    "Invalid payment status code: '" + payment.getStatusCode() + "'"));
        }

        validateLegacyDate(payment.getPaymentDate(), context, "PMT_DT", issues);
        validateLegacyDate(payment.getReceivedDate(), context, "PMT_RECV_DT", issues);
        validateLegacyDate(payment.getProcessedDate(), context, "PMT_PROC_DT", issues);

        return issues;
    }

    // =========================================================================
    // Safe parsing methods with error handling
    // =========================================================================

    public BigDecimal safeParseAmount(String amount) {
        if (isNullOrBlank(amount)) return BigDecimal.ZERO;
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
            return null;
        }
    }

    public BigDecimal safeParseDecimal(String value) {
        if (isNullOrBlank(value)) return BigDecimal.ZERO;
        try {
            String cleaned = value.replace(",", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}': {}", value, e.getMessage());
            return null;
        }
    }

    public Integer safeParseInteger(String value) {
        if (isNullOrBlank(value)) return null;
        try {
            String cleaned = value.replace(",", "").trim();
            if (cleaned.contains(".")) {
                return (int) Double.parseDouble(cleaned);
            }
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    public LocalDate safeParseLegacyDate(String dateStr) {
        if (isNullOrBlank(dateStr)) return null;
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse legacy date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    public BigDecimal recomputePaymentTotal(LegacyPayment payment) {
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (principal == null) principal = BigDecimal.ZERO;
        if (interest == null) interest = BigDecimal.ZERO;
        if (escrow == null) escrow = BigDecimal.ZERO;
        if (lateFee == null) lateFee = BigDecimal.ZERO;

        return principal.add(interest).add(escrow).add(lateFee)
                .setScale(2, RoundingMode.HALF_UP);
    }

    // =========================================================================
    // Private helpers
    // =========================================================================

    private void validateNumericAmount(String value, String context, String column,
                                       boolean required, List<DataQualityIssue> issues) {
        if (isNullOrBlank(value)) {
            if (required) {
                issues.add(DataQualityIssue.critical(context, column,
                        "Required numeric field is null or blank"));
            }
            return;
        }
        BigDecimal parsed = safeParseAmount(value);
        if (parsed == null) {
            issues.add(DataQualityIssue.high(context, column,
                    "Cannot parse as numeric amount: '" + value + "'"));
        }
    }

    private void validateLegacyDate(String dateStr, String context, String column,
                                     List<DataQualityIssue> issues) {
        if (isNullOrBlank(dateStr)) return;
        if (safeParseLegacyDate(dateStr) == null) {
            issues.add(DataQualityIssue.high(context, column,
                    "Invalid date format (expected MM/DD/YYYY): '" + dateStr + "'"));
        }
    }

    private boolean isNullOrBlank(String value) {
        return value == null || value.isBlank();
    }
}
