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
import java.time.format.ResolverStyle;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/uuuu")
            .withResolverStyle(ResolverStyle.STRICT);

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");

    // --- Numeric parsing with error handling ---

    public BigDecimal parseAmount(String value, String recordId, String field, List<ValidationWarning> warnings) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.replace(",", "").replace("$", "").trim());
        } catch (NumberFormatException e) {
            warnings.add(new ValidationWarning(recordId, field, "INVALID_NUMERIC",
                    "Cannot parse amount '" + value + "': " + e.getMessage(), "Critical"));
            log.warn("Failed to parse amount for {}.{}: '{}'", recordId, field, value);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal parseDecimal(String value, String recordId, String field, List<ValidationWarning> warnings) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = value.replace("%", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            warnings.add(new ValidationWarning(recordId, field, "INVALID_NUMERIC",
                    "Cannot parse decimal '" + value + "': " + e.getMessage(), "Critical"));
            log.warn("Failed to parse decimal for {}.{}: '{}'", recordId, field, value);
            return BigDecimal.ZERO;
        }
    }

    public Integer parseInteger(String value, String recordId, String field, List<ValidationWarning> warnings) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            warnings.add(new ValidationWarning(recordId, field, "INVALID_NUMERIC",
                    "Cannot parse integer '" + value + "': " + e.getMessage(), "Critical"));
            log.warn("Failed to parse integer for {}.{}: '{}'", recordId, field, value);
            return null;
        }
    }

    // --- Date validation ---

    public LocalDate parseDate(String value, String recordId, String field, List<ValidationWarning> warnings) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            warnings.add(new ValidationWarning(recordId, field, "INVALID_DATE",
                    "Cannot parse date '" + value + "' as MM/DD/YYYY: " + e.getMessage(), "High"));
            log.warn("Failed to parse date for {}.{}: '{}'", recordId, field, value);
            return null;
        }
    }

    // --- Borrower validation ---

    public List<ValidationWarning> validateBorrower(LegacyBorrower borrower) {
        List<ValidationWarning> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (id == null || id.isBlank()) {
            warnings.add(new ValidationWarning("UNKNOWN", "BORR_ID", "NULL_REQUIRED_FIELD",
                    "Borrower ID is null or blank", "Critical"));
            return warnings;
        }

        validateRequiredString(id, "BORR_FST_NM", borrower.getFirstName(), warnings);
        validateRequiredString(id, "BORR_LST_NM", borrower.getLastName(), warnings);

        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            Integer score = parseInteger(borrower.getCreditScore(), id, "BORR_CRDT_SCR", warnings);
            if (score != null && (score < 300 || score > 850)) {
                warnings.add(new ValidationWarning(id, "BORR_CRDT_SCR", "OUT_OF_RANGE",
                        "Credit score " + score + " is outside valid range (300-850)", "High"));
            }
        }

        if (borrower.getAnnualIncome() != null && !borrower.getAnnualIncome().isBlank()) {
            BigDecimal income = parseAmount(borrower.getAnnualIncome(), id, "BORR_ANN_INCM", warnings);
            if (income.compareTo(BigDecimal.ZERO) < 0) {
                warnings.add(new ValidationWarning(id, "BORR_ANN_INCM", "NEGATIVE_VALUE",
                        "Annual income is negative: " + income, "High"));
            }
        }

        parseDate(borrower.getDateOfBirth(), id, "BORR_DOB_DT", warnings);
        parseDate(borrower.getCreatedDate(), id, "BORR_CRET_DT", warnings);
        parseDate(borrower.getUpdatedDate(), id, "BORR_UPDT_DT", warnings);

        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            warnings.add(new ValidationWarning(id, "BORR_STAT_CD", "INVALID_STATUS_CODE",
                    "Unknown borrower status code: '" + borrower.getStatusCode() + "'", "Medium"));
        }

        return warnings;
    }

    // --- Loan account validation ---

    public List<ValidationWarning> validateLoanAccount(LegacyLoanAccount loan,
                                                        Set<String> validBorrowerIds,
                                                        Set<String> validProductCodes) {
        List<ValidationWarning> warnings = new ArrayList<>();
        String id = loan.getLoanAccountNumber();

        if (id == null || id.isBlank()) {
            warnings.add(new ValidationWarning("UNKNOWN", "LN_ACCT_NBR", "NULL_REQUIRED_FIELD",
                    "Loan account number is null or blank", "Critical"));
            return warnings;
        }

        // Orphaned record checks
        if (loan.getBorrowerId() == null || loan.getBorrowerId().isBlank()) {
            warnings.add(new ValidationWarning(id, "BORR_ID", "NULL_REQUIRED_FIELD",
                    "Borrower ID is null or blank", "Critical"));
        } else if (!validBorrowerIds.contains(loan.getBorrowerId())) {
            warnings.add(new ValidationWarning(id, "BORR_ID", "ORPHANED_REFERENCE",
                    "Borrower ID '" + loan.getBorrowerId() + "' does not exist in CDW_BORR_MSTR", "High"));
        }

        if (loan.getProductCode() == null || loan.getProductCode().isBlank()) {
            warnings.add(new ValidationWarning(id, "PROD_CD", "NULL_REQUIRED_FIELD",
                    "Product code is null or blank", "Critical"));
        } else if (!validProductCodes.contains(loan.getProductCode())) {
            warnings.add(new ValidationWarning(id, "PROD_CD", "ORPHANED_REFERENCE",
                    "Product code '" + loan.getProductCode() + "' does not exist in CDW_LN_PROD", "High"));
        }

        // Numeric field validation
        BigDecimal origAmt = parseAmount(loan.getOriginalAmount(), id, "LN_ORIG_AMT", warnings);
        BigDecimal currBal = parseAmount(loan.getCurrentBalance(), id, "LN_CURR_BAL", warnings);
        parseDecimal(loan.getInterestRate(), id, "LN_INT_RT", warnings);
        parseAmount(loan.getMonthlyPayment(), id, "LN_PMT_AMT", warnings);
        parseAmount(loan.getEscrowBalance(), id, "LN_ESCROW_BAL", warnings);
        parseDecimal(loan.getLtvPercent(), id, "LN_LTV_PCT", warnings);
        parseAmount(loan.getAppraisedValue(), id, "PROP_APRS_VAL", warnings);

        if (currBal.compareTo(origAmt) > 0) {
            warnings.add(new ValidationWarning(id, "LN_CURR_BAL", "BALANCE_EXCEEDS_ORIGINAL",
                    "Current balance (" + currBal + ") exceeds original amount (" + origAmt + ")", "High"));
        }

        // Date validation
        parseDate(loan.getOriginationDate(), id, "LN_ORIG_DT", warnings);
        parseDate(loan.getMaturityDate(), id, "LN_MAT_DT", warnings);
        parseDate(loan.getFirstPaymentDate(), id, "LN_1ST_PMT_DT", warnings);
        parseDate(loan.getNextPaymentDate(), id, "LN_NXT_PMT_DT", warnings);
        parseDate(loan.getCreatedDate(), id, "LN_CRET_DT", warnings);
        parseDate(loan.getUpdatedDate(), id, "LN_UPDT_DT", warnings);

        // Status code validation
        if (loan.getStatusCode() != null && !VALID_LOAN_STATUSES.contains(loan.getStatusCode())) {
            warnings.add(new ValidationWarning(id, "LN_STAT_CD", "INVALID_STATUS_CODE",
                    "Unknown loan status code: '" + loan.getStatusCode() + "'", "Medium"));
        }

        if (loan.getPropertyType() != null && !VALID_PROPERTY_TYPES.contains(loan.getPropertyType())) {
            warnings.add(new ValidationWarning(id, "PROP_TYP_CD", "INVALID_STATUS_CODE",
                    "Unknown property type code: '" + loan.getPropertyType() + "'", "Medium"));
        }

        // Delinquency / status consistency
        Integer dlqDays = parseInteger(loan.getDelinquencyDays(), id, "LN_DLQ_DAYS", warnings);
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(loan.getStatusCode())) {
            warnings.add(new ValidationWarning(id, "LN_DLQ_DAYS", "STATUS_INCONSISTENCY",
                    "Loan is " + dlqDays + " days delinquent but status is ACT (Active)", "High"));
        }

        // Denormalized SSN last-4 cross-reference
        if (loan.getBorrowerSsnLast4() != null && !loan.getBorrowerSsnLast4().isBlank()) {
            if (!loan.getBorrowerSsnLast4().matches("\\d{4}")) {
                warnings.add(new ValidationWarning(id, "BORR_SSN_LST4", "INVALID_FORMAT",
                        "SSN last-4 '" + loan.getBorrowerSsnLast4() + "' is not 4 digits", "High"));
            }
        }

        return warnings;
    }

    // --- Payment validation ---

    public List<ValidationWarning> validatePayment(LegacyPayment payment, Set<String> validLoanAccountNumbers) {
        List<ValidationWarning> warnings = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        if (id == null || id.isBlank()) {
            warnings.add(new ValidationWarning("UNKNOWN", "PMT_SEQ_NBR", "NULL_REQUIRED_FIELD",
                    "Payment sequence number is null or blank", "Critical"));
            return warnings;
        }

        // Orphaned record check
        if (payment.getLoanAccountNumber() == null || payment.getLoanAccountNumber().isBlank()) {
            warnings.add(new ValidationWarning(id, "LN_ACCT_NBR", "NULL_REQUIRED_FIELD",
                    "Loan account number is null or blank", "Critical"));
        } else if (!validLoanAccountNumbers.contains(payment.getLoanAccountNumber())) {
            warnings.add(new ValidationWarning(id, "LN_ACCT_NBR", "ORPHANED_REFERENCE",
                    "Loan account '" + payment.getLoanAccountNumber() + "' does not exist in CDW_LN_ACCT", "High"));
        }

        // Numeric validation + component sum check
        BigDecimal total = parseAmount(payment.getTotalAmount(), id, "PMT_AMT", warnings);
        BigDecimal principal = parseAmount(payment.getPrincipalAmount(), id, "PMT_PRIN_AMT", warnings);
        BigDecimal interest = parseAmount(payment.getInterestAmount(), id, "PMT_INT_AMT", warnings);
        BigDecimal escrow = parseAmount(payment.getEscrowAmount(), id, "PMT_ESCROW_AMT", warnings);
        BigDecimal lateFee = parseAmount(payment.getLateFee(), id, "PMT_LATE_FEE", warnings);

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        if (total.compareTo(BigDecimal.ZERO) > 0 && componentSum.compareTo(total) != 0) {
            warnings.add(new ValidationWarning(id, "PMT_AMT", "COMPONENT_SUM_MISMATCH",
                    "Payment components (" + componentSum + ") do not sum to total (" + total
                            + "), difference: " + componentSum.subtract(total), "Critical"));
        }

        // Date validation
        parseDate(payment.getPaymentDate(), id, "PMT_DT", warnings);
        parseDate(payment.getReceivedDate(), id, "PMT_RECV_DT", warnings);
        parseDate(payment.getProcessedDate(), id, "PMT_PROC_DT", warnings);
        parseDate(payment.getCreatedDate(), id, "PMT_CRET_DT", warnings);
        parseDate(payment.getUpdatedDate(), id, "PMT_UPDT_DT", warnings);

        // Status code validation
        if (payment.getTypeCode() != null && !VALID_PAYMENT_TYPES.contains(payment.getTypeCode())) {
            warnings.add(new ValidationWarning(id, "PMT_TYP_CD", "INVALID_STATUS_CODE",
                    "Unknown payment type code: '" + payment.getTypeCode() + "'", "Medium"));
        }

        if (payment.getStatusCode() != null && !VALID_PAYMENT_STATUSES.contains(payment.getStatusCode())) {
            warnings.add(new ValidationWarning(id, "PMT_STAT_CD", "INVALID_STATUS_CODE",
                    "Unknown payment status code: '" + payment.getStatusCode() + "'", "Medium"));
        }

        return warnings;
    }

    // --- Denormalized data cross-reference ---

    public List<ValidationWarning> validateDenormalizedBorrowerData(LegacyLoanAccount loan,
                                                                     LegacyBorrower borrower) {
        List<ValidationWarning> warnings = new ArrayList<>();
        String id = loan.getLoanAccountNumber();

        if (borrower == null) {
            return warnings;
        }

        if (loan.getBorrowerFirstName() != null && !loan.getBorrowerFirstName().equals(borrower.getFirstName())) {
            warnings.add(new ValidationWarning(id, "BORR_FST_NM", "DENORMALIZED_DRIFT",
                    "Loan has first name '" + loan.getBorrowerFirstName()
                            + "' but master has '" + borrower.getFirstName() + "'", "Medium"));
        }

        if (loan.getBorrowerLastName() != null && !loan.getBorrowerLastName().equals(borrower.getLastName())) {
            warnings.add(new ValidationWarning(id, "BORR_LST_NM", "DENORMALIZED_DRIFT",
                    "Loan has last name '" + loan.getBorrowerLastName()
                            + "' but master has '" + borrower.getLastName() + "'", "Medium"));
        }

        // Cross-reference SSN last-4 against phone (known anomaly)
        if (loan.getBorrowerSsnLast4() != null && borrower.getPhoneNumber() != null) {
            String phoneLast4 = borrower.getPhoneNumber().replaceAll("[^\\d]", "");
            if (phoneLast4.length() >= 4) {
                phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
                if (loan.getBorrowerSsnLast4().equals(phoneLast4)) {
                    warnings.add(new ValidationWarning(id, "BORR_SSN_LST4", "DATA_CROSS_CONTAMINATION",
                            "SSN last-4 '" + loan.getBorrowerSsnLast4()
                                    + "' matches phone last-4, likely contains phone digits instead of SSN",
                            "Critical"));
                }
            }
        }

        return warnings;
    }

    // --- Helpers ---

    private void validateRequiredString(String recordId, String field, String value,
                                        List<ValidationWarning> warnings) {
        if (value == null || value.isBlank()) {
            warnings.add(new ValidationWarning(recordId, field, "NULL_REQUIRED_FIELD",
                    field + " is null or blank", "Medium"));
        }
    }
}
