package com.workshop.loanservice.service;

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

/**
 * Validates legacy CDW data at ingestion time, catching known anomalies
 * before they propagate to API responses.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/uuuu").withResolverStyle(ResolverStyle.STRICT);

    private static final Set<String> VALID_LOAN_STATUSES =
            Set.of("ACT", "CLO", "DFT", "FRB");

    private static final Set<String> VALID_BORROWER_STATUSES =
            Set.of("ACT", "INA");

    private static final Set<String> VALID_PAYMENT_TYPES =
            Set.of("REG", "EXT", "PRT", "PRE");

    private static final Set<String> VALID_PAYMENT_STATUSES =
            Set.of("PST", "REV", "NSF", "PND");

    private static final Set<String> VALID_PROPERTY_TYPES =
            Set.of("SFR", "CND", "MFR", "TWN");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    /**
     * Parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Returns BigDecimal.ZERO and logs a warning for unparseable values.
     */
    public BigDecimal parseLegacyAmount(String amount, String recordId, String fieldName) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("ANO-003: Unparseable amount in record={} field={} value='{}': {}",
                    recordId, fieldName, amount, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., "4.750") to BigDecimal.
     * Returns BigDecimal.ZERO and logs a warning for unparseable values.
     */
    public BigDecimal parseLegacyDecimal(String value, String recordId, String fieldName) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = value.replace(",", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("ANO-003: Unparseable decimal in record={} field={} value='{}': {}",
                    recordId, fieldName, value, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., "745") to Integer.
     * Returns null and logs a warning for unparseable values.
     */
    public Integer parseLegacyInteger(String value, String recordId, String fieldName) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("ANO-003: Unparseable integer in record={} field={} value='{}': {}",
                    recordId, fieldName, value, e.getMessage());
            return null;
        }
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format.
     * Returns null and logs a warning for unparseable dates.
     */
    public LocalDate parseLegacyDate(String dateStr, String recordId, String fieldName) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("ANO-006: Invalid date in record={} field={} value='{}': {}",
                    recordId, fieldName, dateStr, e.getMessage());
            return null;
        }
    }

    /**
     * Build a null-safe display name from first and last name.
     */
    public String safeFullName(String firstName, String lastName) {
        String first = (firstName != null) ? firstName : "Unknown";
        String last = (lastName != null) ? lastName : "Unknown";
        return first + " " + last;
    }

    /**
     * Build a null-safe display name including optional middle initial.
     */
    public String safeFullNameWithMiddle(String firstName, String middleInitial, String lastName) {
        String first = (firstName != null) ? firstName : "Unknown";
        String last = (lastName != null) ? lastName : "Unknown";
        String middle = (middleInitial != null) ? " " + middleInitial + "." : "";
        return first + middle + " " + last;
    }

    /**
     * Validate a borrower record and return a list of anomaly warnings.
     */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add("ANO-007: Null/blank first name for borrower " + id);
            log.warn("ANO-007: Null/blank first name for borrower={}", id);
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add("ANO-007: Null/blank last name for borrower " + id);
            log.warn("ANO-007: Null/blank last name for borrower={}", id);
        }

        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            warnings.add("ANO-009: Unrecognized borrower status '" + borrower.getStatusCode() + "' for " + id);
            log.warn("ANO-009: Unrecognized borrower status='{}' for borrower={}", borrower.getStatusCode(), id);
        }

        Integer creditScore = parseLegacyInteger(borrower.getCreditScore(), id, "BORR_CRDT_SCR");
        if (creditScore != null && (creditScore < CREDIT_SCORE_MIN || creditScore > CREDIT_SCORE_MAX)) {
            warnings.add("ANO-003: Credit score out of range (" + creditScore + ") for " + id);
            log.warn("ANO-003: Credit score out of range value={} for borrower={}", creditScore, id);
        }

        parseLegacyDate(borrower.getDateOfBirth(), id, "BORR_DOB_DT");
        parseLegacyDate(borrower.getCreatedDate(), id, "BORR_CRET_DT");
        parseLegacyDate(borrower.getUpdatedDate(), id, "BORR_UPDT_DT");

        return warnings;
    }

    /**
     * Validate a loan account record and return a list of anomaly warnings.
     */
    public List<String> validateLoanAccount(LegacyLoanAccount acct) {
        List<String> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (acct.getStatusCode() != null && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            warnings.add("ANO-009: Unrecognized loan status '" + acct.getStatusCode() + "' for " + id);
            log.warn("ANO-009: Unrecognized loan status='{}' for loan={}", acct.getStatusCode(), id);
        }

        if (acct.getPropertyType() != null && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            warnings.add("ANO-009: Unrecognized property type '" + acct.getPropertyType() + "' for " + id);
            log.warn("ANO-009: Unrecognized property type='{}' for loan={}", acct.getPropertyType(), id);
        }

        Integer dlqDays = parseLegacyInteger(acct.getDelinquencyDays(), id, "LN_DLQ_DAYS");
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            warnings.add("ANO-005: Active loan with " + dlqDays + " delinquency days for " + id);
            log.warn("ANO-005: Active loan with delinquencyDays={} for loan={}", dlqDays, id);
        }

        parseLegacyDate(acct.getOriginationDate(), id, "LN_ORIG_DT");
        parseLegacyDate(acct.getMaturityDate(), id, "LN_MAT_DT");
        parseLegacyDate(acct.getFirstPaymentDate(), id, "LN_1ST_PMT_DT");
        parseLegacyDate(acct.getNextPaymentDate(), id, "LN_NXT_PMT_DT");
        parseLegacyDate(acct.getCreatedDate(), id, "LN_CRET_DT");
        parseLegacyDate(acct.getUpdatedDate(), id, "LN_UPDT_DT");

        if (acct.getBorrowerFirstName() == null || acct.getBorrowerLastName() == null) {
            warnings.add("ANO-007: Null borrower name in denormalized loan record " + id);
            log.warn("ANO-007: Null borrower name in denormalized loan record={}", id);
        }

        return warnings;
    }

    /**
     * Validate a payment record and return a list of anomaly warnings.
     * Checks component sum integrity (ANO-002).
     */
    public List<String> validatePayment(LegacyPayment pmt) {
        List<String> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (pmt.getTypeCode() != null && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            warnings.add("ANO-009: Unrecognized payment type '" + pmt.getTypeCode() + "' for " + id);
            log.warn("ANO-009: Unrecognized payment type='{}' for payment={}", pmt.getTypeCode(), id);
        }

        if (pmt.getStatusCode() != null && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            warnings.add("ANO-009: Unrecognized payment status '" + pmt.getStatusCode() + "' for " + id);
            log.warn("ANO-009: Unrecognized payment status='{}' for payment={}", pmt.getStatusCode(), id);
        }

        BigDecimal total = parseLegacyAmount(pmt.getTotalAmount(), id, "PMT_AMT");
        BigDecimal principal = parseLegacyAmount(pmt.getPrincipalAmount(), id, "PMT_PRIN_AMT");
        BigDecimal interest = parseLegacyAmount(pmt.getInterestAmount(), id, "PMT_INT_AMT");
        BigDecimal escrow = parseLegacyAmount(pmt.getEscrowAmount(), id, "PMT_ESCROW_AMT");
        BigDecimal lateFee = parseLegacyAmount(pmt.getLateFee(), id, "PMT_LATE_FEE");

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        if (total.compareTo(BigDecimal.ZERO) > 0 && componentSum.compareTo(total) != 0) {
            BigDecimal discrepancy = componentSum.subtract(total);
            warnings.add("ANO-002: Payment component sum mismatch for " + id
                    + " (total=" + total + ", components=" + componentSum
                    + ", discrepancy=" + discrepancy + ")");
            log.warn("ANO-002: Payment component sum mismatch for payment={} total={} componentSum={} discrepancy={}",
                    id, total, componentSum, discrepancy);
        }

        parseLegacyDate(pmt.getPaymentDate(), id, "PMT_DT");
        parseLegacyDate(pmt.getReceivedDate(), id, "PMT_RECV_DT");
        parseLegacyDate(pmt.getProcessedDate(), id, "PMT_PROC_DT");

        return warnings;
    }

    /**
     * Check for SSN/phone correlation anomaly (ANO-001).
     */
    public boolean isSsnPhoneCorrelated(String ssnLast4, String phoneNumber) {
        if (ssnLast4 == null || phoneNumber == null) {
            return false;
        }
        String phoneLast4 = phoneNumber.replaceAll("[^0-9]", "");
        if (phoneLast4.length() >= 4) {
            phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
            return ssnLast4.equals(phoneLast4);
        }
        return false;
    }

    /**
     * Validate referential integrity: check that a borrower ID exists in the provided set.
     */
    public boolean isOrphanedLoan(String borrowerId, Set<String> validBorrowerIds) {
        return borrowerId == null || !validBorrowerIds.contains(borrowerId);
    }

    /**
     * Validate referential integrity: check that a product code exists in the provided set.
     */
    public boolean isOrphanedProduct(String productCode, Set<String> validProductCodes) {
        return productCode == null || !validProductCodes.contains(productCode);
    }

    /**
     * Validate referential integrity: check that a loan account number exists in the provided set.
     */
    public boolean isOrphanedPayment(String loanAccountNumber, Set<String> validLoanAccountNumbers) {
        return loanAccountNumber == null || !validLoanAccountNumbers.contains(loanAccountNumber);
    }

    /**
     * Check for denormalized data drift between loan account and borrower master.
     */
    public List<String> checkDenormalizedDrift(LegacyLoanAccount acct, LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        if (borrower == null) {
            return warnings;
        }

        String loanId = acct.getLoanAccountNumber();
        if (acct.getBorrowerFirstName() != null && borrower.getFirstName() != null
                && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
            warnings.add("ANO-008: First name drift for loan " + loanId
                    + " (loan='" + acct.getBorrowerFirstName()
                    + "', master='" + borrower.getFirstName() + "')");
            log.warn("ANO-008: First name drift for loan={} loanValue='{}' masterValue='{}'",
                    loanId, acct.getBorrowerFirstName(), borrower.getFirstName());
        }
        if (acct.getBorrowerLastName() != null && borrower.getLastName() != null
                && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
            warnings.add("ANO-008: Last name drift for loan " + loanId
                    + " (loan='" + acct.getBorrowerLastName()
                    + "', master='" + borrower.getLastName() + "')");
            log.warn("ANO-008: Last name drift for loan={} loanValue='{}' masterValue='{}'",
                    loanId, acct.getBorrowerLastName(), borrower.getLastName());
        }

        if (isSsnPhoneCorrelated(acct.getBorrowerSsnLast4(), borrower.getPhoneNumber())) {
            warnings.add("ANO-001: SSN last-4 matches phone last-4 for loan " + loanId
                    + " (ssnLast4='" + acct.getBorrowerSsnLast4() + "')");
            log.warn("ANO-001: SSN last-4 matches phone last-4 for loan={} ssnLast4='{}'",
                    loanId, acct.getBorrowerSsnLast4());
        }

        return warnings;
    }
}
