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
 * Validates legacy CDW data at ingestion time, catching known anomalies
 * (see docs/DATA_ANOMALY_REPORT.md) before they propagate to API responses.
 * Returns a list of human-readable warning strings per record.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Legacy CDW stores all dates as MM/DD/YYYY VARCHAR strings
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    // Allow-lists for status/type codes recognized by the expansion methods in LoanService
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_EMPLOYMENT_STATUSES = Set.of("EMPLOYED", "SELF-EMP", "RETIRED", "UNEMPLOYED");

    // FICO score valid range
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    /** Validates a borrower record for null required fields, unparseable values, and invalid codes. */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (isBlank(borrower.getFirstName())) {
            warnings.add(String.format("Borrower %s: first name is null or blank", id));
        }
        if (isBlank(borrower.getLastName())) {
            warnings.add(String.format("Borrower %s: last name is null or blank", id));
        }
        if (isBlank(borrower.getEmail())) {
            warnings.add(String.format("Borrower %s: email is null or blank", id));
        }

        if (!isBlank(borrower.getCreditScore())) {
            Integer score = safeParseInteger(borrower.getCreditScore());
            if (score == null) {
                warnings.add(String.format("Borrower %s: credit score '%s' is not a valid integer",
                        id, borrower.getCreditScore()));
            } else if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
                warnings.add(String.format("Borrower %s: credit score %d is outside valid range [%d-%d]",
                        id, score, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX));
            }
        }

        if (!isBlank(borrower.getAnnualIncome())) {
            BigDecimal income = safeParseAmount(borrower.getAnnualIncome());
            if (income == null) {
                warnings.add(String.format("Borrower %s: annual income '%s' is not parseable",
                        id, borrower.getAnnualIncome()));
            }
        }

        if (!isBlank(borrower.getDateOfBirth())) {
            LocalDate dob = safeParseLegacyDate(borrower.getDateOfBirth());
            if (dob == null) {
                warnings.add(String.format("Borrower %s: date of birth '%s' does not match MM/DD/YYYY format",
                        id, borrower.getDateOfBirth()));
            }
        }

        validateLegacyDate(borrower.getCreatedDate(), "created date", id, "Borrower", warnings);
        validateLegacyDate(borrower.getUpdatedDate(), "updated date", id, "Borrower", warnings);

        if (!isBlank(borrower.getEmploymentStatus())
                && !VALID_EMPLOYMENT_STATUSES.contains(borrower.getEmploymentStatus())) {
            warnings.add(String.format("Borrower %s: unknown employment status '%s'",
                    id, borrower.getEmploymentStatus()));
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    /** Validates a loan account for missing FKs, unparseable amounts, status mismatches, and SSN/phone anomaly. */
    public List<String> validateLoanAccount(LegacyLoanAccount acct, LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (isBlank(acct.getBorrowerId())) {
            warnings.add(String.format("Loan %s: borrower ID is null or blank", id));
        }
        if (isBlank(acct.getProductCode())) {
            warnings.add(String.format("Loan %s: product code is null or blank", id));
        }

        validateAmountField(acct.getOriginalAmount(), "original amount", id, "Loan", warnings);
        validateAmountField(acct.getCurrentBalance(), "current balance", id, "Loan", warnings);
        validateAmountField(acct.getMonthlyPayment(), "monthly payment", id, "Loan", warnings);
        validateAmountField(acct.getEscrowBalance(), "escrow balance", id, "Loan", warnings);
        validateAmountField(acct.getAppraisedValue(), "appraised value", id, "Loan", warnings);

        if (!isBlank(acct.getInterestRate())) {
            BigDecimal rate = safeParseDecimal(acct.getInterestRate());
            if (rate == null) {
                warnings.add(String.format("Loan %s: interest rate '%s' is not parseable", id, acct.getInterestRate()));
            }
        }

        if (!isBlank(acct.getTermMonths())) {
            Integer term = safeParseInteger(acct.getTermMonths());
            if (term == null) {
                warnings.add(String.format("Loan %s: term months '%s' is not a valid integer",
                        id, acct.getTermMonths()));
            }
        }

        if (!isBlank(acct.getDelinquencyDays())) {
            Integer dlqDays = safeParseInteger(acct.getDelinquencyDays());
            if (dlqDays == null) {
                warnings.add(String.format("Loan %s: delinquency days '%s' is not a valid integer",
                        id, acct.getDelinquencyDays()));
            } else if (dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
                warnings.add(String.format(
                        "Loan %s: %d delinquency days but status is ACT (Active) — status/delinquency mismatch",
                        id, dlqDays));
            }
        }

        if (!isBlank(acct.getStatusCode()) && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            warnings.add(String.format("Loan %s: unknown status code '%s'", id, acct.getStatusCode()));
        }

        if (!isBlank(acct.getPropertyType()) && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            warnings.add(String.format("Loan %s: unknown property type '%s'", id, acct.getPropertyType()));
        }

        validateLegacyDate(acct.getOriginationDate(), "origination date", id, "Loan", warnings);
        validateLegacyDate(acct.getMaturityDate(), "maturity date", id, "Loan", warnings);
        validateLegacyDate(acct.getFirstPaymentDate(), "first payment date", id, "Loan", warnings);
        validateLegacyDate(acct.getNextPaymentDate(), "next payment date", id, "Loan", warnings);

        if (borrower != null) {
            validateSsnLast4(acct, borrower, warnings);
            validateBorrowerNameConsistency(acct, borrower, warnings);
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    /** Validates a payment record for missing FK, unparseable amounts, component-sum mismatch, and invalid codes. */
    public List<String> validatePayment(LegacyPayment pmt) {
        List<String> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (isBlank(pmt.getLoanAccountNumber())) {
            warnings.add(String.format("Payment %s: loan account number is null or blank", id));
        }

        validateAmountField(pmt.getTotalAmount(), "total amount", id, "Payment", warnings);
        validateAmountField(pmt.getPrincipalAmount(), "principal amount", id, "Payment", warnings);
        validateAmountField(pmt.getInterestAmount(), "interest amount", id, "Payment", warnings);
        validateAmountField(pmt.getEscrowAmount(), "escrow amount", id, "Payment", warnings);
        validateAmountField(pmt.getLateFee(), "late fee", id, "Payment", warnings);

        validatePaymentComponentSum(pmt, warnings);

        if (!isBlank(pmt.getStatusCode()) && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            warnings.add(String.format("Payment %s: unknown status code '%s'", id, pmt.getStatusCode()));
        }

        if (!isBlank(pmt.getTypeCode()) && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            warnings.add(String.format("Payment %s: unknown payment type '%s'", id, pmt.getTypeCode()));
        }

        validateLegacyDate(pmt.getPaymentDate(), "payment date", id, "Payment", warnings);
        validateLegacyDate(pmt.getReceivedDate(), "received date", id, "Payment", warnings);
        validateLegacyDate(pmt.getProcessedDate(), "processed date", id, "Payment", warnings);

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    // ANO-002: checks that principal + interest + escrow + late_fee == total amount
    private void validatePaymentComponentSum(LegacyPayment pmt, List<String> warnings) {
        BigDecimal total = safeParseAmount(pmt.getTotalAmount());
        BigDecimal principal = safeParseAmount(pmt.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(pmt.getInterestAmount());
        BigDecimal escrow = safeParseAmount(pmt.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(pmt.getLateFee());

        if (total == null || principal == null || interest == null || escrow == null || lateFee == null) {
            return;
        }

        BigDecimal computedSum = principal.add(interest).add(escrow).add(lateFee);
        if (computedSum.compareTo(total) != 0) {
            warnings.add(String.format(
                    "Payment %s: component sum %s (P:%s + I:%s + E:%s + L:%s) != total %s, difference: %s",
                    pmt.getPaymentSequenceNumber(), computedSum,
                    principal, interest, escrow, lateFee,
                    total, computedSum.subtract(total)));
        }
    }

    // ANO-001: detects when BORR_SSN_LST4 actually contains phone-number last-4 digits
    private void validateSsnLast4(LegacyLoanAccount acct, LegacyBorrower borrower, List<String> warnings) {
        String ssnLast4 = acct.getBorrowerSsnLast4();
        if (isBlank(ssnLast4) || isBlank(borrower.getPhoneNumber())) {
            return;
        }
        String phoneDigits = borrower.getPhoneNumber().replaceAll("[^0-9]", "");
        if (phoneDigits.length() >= 4) {
            String phoneLast4 = phoneDigits.substring(phoneDigits.length() - 4);
            if (phoneLast4.equals(ssnLast4)) {
                warnings.add(String.format(
                        "Loan %s: BORR_SSN_LST4 '%s' matches phone last-4 '%s' — likely contains phone digits instead of SSN",
                        acct.getLoanAccountNumber(), ssnLast4, phoneLast4));
            }
        }
    }

    // ANO-009: detects denormalized borrower name drift between loan account and master record
    private void validateBorrowerNameConsistency(LegacyLoanAccount acct, LegacyBorrower borrower,
                                                  List<String> warnings) {
        if (!isBlank(acct.getBorrowerFirstName()) && !isBlank(borrower.getFirstName())
                && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
            warnings.add(String.format(
                    "Loan %s: denormalized first name '%s' differs from master '%s'",
                    acct.getLoanAccountNumber(), acct.getBorrowerFirstName(), borrower.getFirstName()));
        }
        if (!isBlank(acct.getBorrowerLastName()) && !isBlank(borrower.getLastName())
                && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
            warnings.add(String.format(
                    "Loan %s: denormalized last name '%s' differs from master '%s'",
                    acct.getLoanAccountNumber(), acct.getBorrowerLastName(), borrower.getLastName()));
        }
    }

    private void validateAmountField(String value, String fieldName, String recordId,
                                     String entityType, List<String> warnings) {
        if (!isBlank(value) && safeParseAmount(value) == null) {
            warnings.add(String.format("%s %s: %s '%s' is not parseable as a numeric amount",
                    entityType, recordId, fieldName, value));
        }
    }

    private void validateLegacyDate(String value, String fieldName, String recordId,
                                    String entityType, List<String> warnings) {
        if (!isBlank(value) && safeParseLegacyDate(value) == null) {
            warnings.add(String.format("%s %s: %s '%s' does not match MM/DD/YYYY format",
                    entityType, recordId, fieldName, value));
        }
    }

    // --- Safe parsing utilities (public for reuse in LoanService) ---
    // ANO-003 fix: all parse methods wrap exceptions and return null on bad input
    //              instead of throwing uncaught NumberFormatException / DateTimeParseException

    /** Strips commas then parses to BigDecimal; returns ZERO for null/blank, null for unparseable. */
    public BigDecimal safeParseAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(amount.replace(",", ""));
        } catch (NumberFormatException e) {
            log.warn("Unparseable amount '{}', returning null", amount);
            return null;
        }
    }

    public BigDecimal safeParseDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal '{}', returning null", value);
            return null;
        }
    }

    public Integer safeParseInteger(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer '{}', returning null", value);
            return null;
        }
    }

    /** Parses legacy MM/DD/YYYY string to LocalDate; returns null for null/blank/unparseable. */
    public LocalDate safeParseLegacyDate(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Unparseable date '{}', returning null", value);
            return null;
        }
    }

    /** Returns value if non-null, otherwise the fallback — prevents "null" in string concatenation. */
    public String safeString(String value, String fallback) {
        return (value != null) ? value : fallback;
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
