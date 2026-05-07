package com.workshop.loanservice.service;

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

@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/uuuu")
            .withResolverStyle(ResolverStyle.STRICT);
    private static final Pattern AMOUNT_PATTERN = Pattern.compile("-?\\d{1,3}(,\\d{3})*(\\.\\d+)?");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.01");

    public BigDecimal parseAndValidateAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            log.warn("[{}] {} is null/blank — defaulting to ZERO", recordId, fieldName);
            return BigDecimal.ZERO;
        }
        String cleaned = amount.replace(",", "").replace("$", "").trim();
        try {
            BigDecimal value = new BigDecimal(cleaned);
            if (value.compareTo(BigDecimal.ZERO) < 0) {
                log.warn("[{}] {} has negative value: {} — using absolute value", recordId, fieldName, amount);
                return value.abs();
            }
            return value;
        } catch (NumberFormatException e) {
            log.error("[{}] {} has unparseable amount '{}' — defaulting to ZERO", recordId, fieldName, amount);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal parseAndValidateDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("[{}] {} is null/blank — defaulting to ZERO", recordId, fieldName);
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.error("[{}] {} has unparseable decimal '{}' — defaulting to ZERO", recordId, fieldName, value);
            return BigDecimal.ZERO;
        }
    }

    public Integer parseAndValidateInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("[{}] {} is null/blank — returning null", recordId, fieldName);
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.error("[{}] {} has unparseable integer '{}' — returning null", recordId, fieldName, value);
            return null;
        }
    }

    public String parseAndValidateDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            log.warn("[{}] {} is null/blank", recordId, fieldName);
            return null;
        }
        try {
            LocalDate.parse(dateStr, LEGACY_DATE_FORMAT);
            return dateStr;
        } catch (DateTimeParseException e) {
            log.error("[{}] {} has invalid date format '{}' — expected MM/DD/YYYY", recordId, fieldName, dateStr);
            return null;
        }
    }

    public Integer validateCreditScore(String creditScoreStr, String recordId) {
        Integer score = parseAndValidateInteger(creditScoreStr, "creditScore", recordId);
        if (score == null) {
            return null;
        }
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            log.warn("[{}] Credit score {} is outside valid FICO range [{}-{}]",
                    recordId, score, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX);
        }
        return score;
    }

    public String validateStatusCode(String statusCode, Set<String> validCodes, String fieldName, String recordId) {
        if (statusCode == null || statusCode.isBlank()) {
            log.warn("[{}] {} is null/blank — defaulting to 'Unknown'", recordId, fieldName);
            return null;
        }
        if (!validCodes.contains(statusCode)) {
            log.warn("[{}] {} has unrecognized status code '{}'", recordId, fieldName, statusCode);
        }
        return statusCode;
    }

    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add("First name is null/blank");
            log.warn("[{}] Borrower first name is null/blank", id);
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add("Last name is null/blank");
            log.warn("[{}] Borrower last name is null/blank", id);
        }
        if (borrower.getMiddleInitial() == null) {
            warnings.add("Middle initial is null");
        }

        parseAndValidateDate(borrower.getDateOfBirth(), "dateOfBirth", id);
        parseAndValidateDate(borrower.getCreatedDate(), "createdDate", id);
        parseAndValidateDate(borrower.getUpdatedDate(), "updatedDate", id);

        validateCreditScore(borrower.getCreditScore(), id);
        validateStatusCode(borrower.getStatusCode(), VALID_BORROWER_STATUSES, "borrowerStatus", id);

        if (borrower.getAnnualIncome() != null) {
            parseAndValidateAmount(borrower.getAnnualIncome(), "annualIncome", id);
        }

        return warnings;
    }

    public List<String> validateLoanAccount(LegacyLoanAccount acct) {
        List<String> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (acct.getBorrowerId() == null || acct.getBorrowerId().isBlank()) {
            warnings.add("Borrower ID is null/blank — potential orphaned loan");
            log.error("[{}] Loan has null/blank borrower ID", id);
        }

        validateStatusCode(acct.getStatusCode(), VALID_LOAN_STATUSES, "loanStatus", id);
        validateStatusCode(acct.getPropertyType(), VALID_PROPERTY_TYPES, "propertyType", id);

        Integer delinquencyDays = parseAndValidateInteger(acct.getDelinquencyDays(), "delinquencyDays", id);
        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(acct.getStatusCode())) {
            warnings.add("Active loan with " + delinquencyDays + " delinquency days");
            log.warn("[{}] Active loan has {} delinquency days — status/delinquency mismatch", id, delinquencyDays);
        }

        parseAndValidateDate(acct.getOriginationDate(), "originationDate", id);
        parseAndValidateDate(acct.getMaturityDate(), "maturityDate", id);
        parseAndValidateDate(acct.getFirstPaymentDate(), "firstPaymentDate", id);
        parseAndValidateDate(acct.getNextPaymentDate(), "nextPaymentDate", id);
        parseAndValidateDate(acct.getCreatedDate(), "createdDate", id);
        parseAndValidateDate(acct.getUpdatedDate(), "updatedDate", id);

        BigDecimal origAmt = parseAndValidateAmount(acct.getOriginalAmount(), "originalAmount", id);
        BigDecimal currBal = parseAndValidateAmount(acct.getCurrentBalance(), "currentBalance", id);
        if (currBal.compareTo(origAmt) > 0) {
            warnings.add("Current balance exceeds original amount");
            log.warn("[{}] Current balance {} exceeds original amount {}", id, currBal, origAmt);
        }

        if (acct.getBorrowerFirstName() == null || acct.getBorrowerFirstName().isBlank()) {
            warnings.add("Denormalized borrower first name is null/blank");
        }
        if (acct.getBorrowerLastName() == null || acct.getBorrowerLastName().isBlank()) {
            warnings.add("Denormalized borrower last name is null/blank");
        }

        return warnings;
    }

    public List<String> validatePayment(LegacyPayment pmt) {
        List<String> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (pmt.getLoanAccountNumber() == null || pmt.getLoanAccountNumber().isBlank()) {
            warnings.add("Loan account number is null/blank — orphaned payment");
            log.error("[{}] Payment has null/blank loan account number", id);
        }

        validateStatusCode(pmt.getTypeCode(), VALID_PAYMENT_TYPES, "paymentType", id);
        validateStatusCode(pmt.getStatusCode(), VALID_PAYMENT_STATUSES, "paymentStatus", id);

        parseAndValidateDate(pmt.getPaymentDate(), "paymentDate", id);
        parseAndValidateDate(pmt.getReceivedDate(), "receivedDate", id);
        parseAndValidateDate(pmt.getProcessedDate(), "processedDate", id);
        parseAndValidateDate(pmt.getCreatedDate(), "createdDate", id);
        parseAndValidateDate(pmt.getUpdatedDate(), "updatedDate", id);

        BigDecimal total = parseAndValidateAmount(pmt.getTotalAmount(), "totalAmount", id);
        BigDecimal principal = parseAndValidateAmount(pmt.getPrincipalAmount(), "principalAmount", id);
        BigDecimal interest = parseAndValidateAmount(pmt.getInterestAmount(), "interestAmount", id);
        BigDecimal escrow = parseAndValidateAmount(pmt.getEscrowAmount(), "escrowAmount", id);
        BigDecimal lateFee = parseAndValidateAmount(pmt.getLateFee(), "lateFee", id);

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal difference = componentSum.subtract(total).abs();
        if (difference.compareTo(PAYMENT_TOLERANCE) > 0) {
            warnings.add("Payment components sum (" + componentSum.setScale(2, RoundingMode.HALF_UP)
                    + ") does not equal total (" + total.setScale(2, RoundingMode.HALF_UP)
                    + ") — difference: " + difference.setScale(2, RoundingMode.HALF_UP));
            log.warn("[{}] Payment component mismatch: components={}, total={}, diff={}",
                    id, componentSum, total, difference);
        }

        return warnings;
    }

    public Set<String> getValidLoanStatuses() {
        return VALID_LOAN_STATUSES;
    }

    public Set<String> getValidPaymentTypes() {
        return VALID_PAYMENT_TYPES;
    }

    public Set<String> getValidPaymentStatuses() {
        return VALID_PAYMENT_STATUSES;
    }

    public Set<String> getValidPropertyTypes() {
        return VALID_PROPERTY_TYPES;
    }

    public Set<String> getValidBorrowerStatuses() {
        return VALID_BORROWER_STATUSES;
    }
}
