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
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_EMPLOYMENT_STATUSES = Set.of("EMPLOYED", "SELF-EMP", "RETIRED", "UNEMPLOYED");
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.02");

    public BigDecimal parseSafeAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("ANO-003: Unparseable amount '{}' in field {} for record {}; defaulting to ZERO",
                    amount, fieldName, recordId);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal parseSafeDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("ANO-003: Unparseable decimal '{}' in field {} for record {}; defaulting to ZERO",
                    value, fieldName, recordId);
            return BigDecimal.ZERO;
        }
    }

    public Integer parseSafeInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            String cleaned = value.replace(",", "").trim();
            if (cleaned.contains(".")) {
                return (int) Double.parseDouble(cleaned);
            }
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.warn("ANO-003: Unparseable integer '{}' in field {} for record {}; defaulting to null",
                    value, fieldName, recordId);
            return null;
        }
    }

    public LocalDate parseSafeDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("ANO-008: Unparseable date '{}' in field {} for record {}",
                    dateStr, fieldName, recordId);
            return null;
        }
    }

    public List<ValidationWarning> validateBorrower(LegacyBorrower borrower) {
        List<ValidationWarning> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add(new ValidationWarning("ANO-007", "Critical",
                    "CDW_BORR_MSTR", "BORR_FST_NM", id,
                    "Required field first name is null or blank"));
        }

        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add(new ValidationWarning("ANO-007", "Critical",
                    "CDW_BORR_MSTR", "BORR_LST_NM", id,
                    "Required field last name is null or blank"));
        }

        Integer creditScore = parseSafeInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", id);
        if (creditScore != null && (creditScore < CREDIT_SCORE_MIN || creditScore > CREDIT_SCORE_MAX)) {
            warnings.add(new ValidationWarning("ANO-003", "High",
                    "CDW_BORR_MSTR", "BORR_CRDT_SCR", id,
                    "Credit score " + creditScore + " outside valid range [" + CREDIT_SCORE_MIN + "-" + CREDIT_SCORE_MAX + "]"));
        }

        if (borrower.getEmploymentStatus() != null
                && !VALID_EMPLOYMENT_STATUSES.contains(borrower.getEmploymentStatus())) {
            warnings.add(new ValidationWarning("ANO-003", "Medium",
                    "CDW_BORR_MSTR", "BORR_EMP_STAT", id,
                    "Unknown employment status: " + borrower.getEmploymentStatus()));
        }

        if (borrower.getDateOfBirth() != null) {
            parseSafeDate(borrower.getDateOfBirth(), "BORR_DOB_DT", id);
        }

        if (borrower.getEmail() == null || borrower.getEmail().isBlank()) {
            warnings.add(new ValidationWarning("ANO-007", "Medium",
                    "CDW_BORR_MSTR", "BORR_EMAIL_ADDR", id,
                    "Email address is null or blank"));
        }

        for (ValidationWarning w : warnings) {
            log.warn("{}: {} — table={}, column={}, record={}, detail={}",
                    w.anomalyId(), w.severity(), w.table(), w.column(), w.recordId(), w.detail());
        }

        return warnings;
    }

    public List<ValidationWarning> validateLoanAccount(LegacyLoanAccount acct, LegacyBorrower borrower) {
        List<ValidationWarning> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (acct.getStatusCode() != null && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            warnings.add(new ValidationWarning("ANO-003", "High",
                    "CDW_LN_ACCT", "LN_STAT_CD", id,
                    "Invalid loan status code: " + acct.getStatusCode()));
        }

        if (acct.getPropertyType() != null && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            warnings.add(new ValidationWarning("ANO-003", "Medium",
                    "CDW_LN_ACCT", "PROP_TYP_CD", id,
                    "Invalid property type code: " + acct.getPropertyType()));
        }

        Integer delinquencyDays = parseSafeInteger(acct.getDelinquencyDays(), "LN_DLQ_DAYS", id);
        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(acct.getStatusCode())) {
            warnings.add(new ValidationWarning("ANO-004", "High",
                    "CDW_LN_ACCT", "LN_STAT_CD/LN_DLQ_DAYS", id,
                    "Loan is Active but has " + delinquencyDays + " delinquency days"));
        }

        if (borrower != null) {
            if (acct.getBorrowerFirstName() != null && borrower.getFirstName() != null
                    && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
                warnings.add(new ValidationWarning("ANO-006", "High",
                        "CDW_LN_ACCT", "BORR_FST_NM", id,
                        "Denormalized first name '" + acct.getBorrowerFirstName()
                                + "' differs from master '" + borrower.getFirstName() + "'"));
            }

            if (acct.getBorrowerLastName() != null && borrower.getLastName() != null
                    && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
                warnings.add(new ValidationWarning("ANO-006", "High",
                        "CDW_LN_ACCT", "BORR_LST_NM", id,
                        "Denormalized last name '" + acct.getBorrowerLastName()
                                + "' differs from master '" + borrower.getLastName() + "'"));
            }

            if (borrower.getPhoneNumber() != null && acct.getBorrowerSsnLast4() != null) {
                String phoneLast4 = borrower.getPhoneNumber().replaceAll("[^0-9]", "");
                if (phoneLast4.length() >= 4) {
                    phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
                    if (phoneLast4.equals(acct.getBorrowerSsnLast4())) {
                        warnings.add(new ValidationWarning("ANO-002", "Critical",
                                "CDW_LN_ACCT", "BORR_SSN_LST4", id,
                                "SSN last-4 '" + acct.getBorrowerSsnLast4()
                                        + "' matches phone last-4 — likely data corruption"));
                    }
                }
            }
        }

        if (acct.getBorrowerId() == null || acct.getBorrowerId().isBlank()) {
            warnings.add(new ValidationWarning("ANO-005", "Critical",
                    "CDW_LN_ACCT", "BORR_ID", id,
                    "Borrower ID is null — orphaned loan account"));
        }

        if (acct.getProductCode() == null || acct.getProductCode().isBlank()) {
            warnings.add(new ValidationWarning("ANO-005", "Critical",
                    "CDW_LN_ACCT", "PROD_CD", id,
                    "Product code is null — orphaned loan account"));
        }

        for (ValidationWarning w : warnings) {
            log.warn("{}: {} — table={}, column={}, record={}, detail={}",
                    w.anomalyId(), w.severity(), w.table(), w.column(), w.recordId(), w.detail());
        }

        return warnings;
    }

    public List<ValidationWarning> validatePayment(LegacyPayment pmt) {
        List<ValidationWarning> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        BigDecimal total = parseSafeAmount(pmt.getTotalAmount(), "PMT_AMT", id);
        BigDecimal principal = parseSafeAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id);
        BigDecimal interest = parseSafeAmount(pmt.getInterestAmount(), "PMT_INT_AMT", id);
        BigDecimal escrow = parseSafeAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id);
        BigDecimal lateFee = parseSafeAmount(pmt.getLateFee(), "PMT_LATE_FEE", id);

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal discrepancy = componentSum.subtract(total).abs();
        if (discrepancy.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            warnings.add(new ValidationWarning("ANO-001", "Critical",
                    "CDW_PMT_HIST", "PMT_AMT", id,
                    "Payment component sum " + componentSum + " != total " + total
                            + " (discrepancy: " + discrepancy + ")"));
        }

        if (pmt.getTypeCode() != null && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            warnings.add(new ValidationWarning("ANO-003", "Medium",
                    "CDW_PMT_HIST", "PMT_TYP_CD", id,
                    "Invalid payment type code: " + pmt.getTypeCode()));
        }

        if (pmt.getStatusCode() != null && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            warnings.add(new ValidationWarning("ANO-003", "Medium",
                    "CDW_PMT_HIST", "PMT_STAT_CD", id,
                    "Invalid payment status code: " + pmt.getStatusCode()));
        }

        LocalDate paymentDate = parseSafeDate(pmt.getPaymentDate(), "PMT_DT", id);
        LocalDate receivedDate = parseSafeDate(pmt.getReceivedDate(), "PMT_RECV_DT", id);
        if (paymentDate != null && receivedDate != null && receivedDate.isAfter(paymentDate)) {
            long daysLate = java.time.temporal.ChronoUnit.DAYS.between(paymentDate, receivedDate);
            warnings.add(new ValidationWarning("ANO-009", "Medium",
                    "CDW_PMT_HIST", "PMT_RECV_DT", id,
                    "Payment received " + daysLate + " days after due date"));
        }

        if (pmt.getLoanAccountNumber() == null || pmt.getLoanAccountNumber().isBlank()) {
            warnings.add(new ValidationWarning("ANO-005", "Critical",
                    "CDW_PMT_HIST", "LN_ACCT_NBR", id,
                    "Loan account number is null — orphaned payment"));
        }

        for (ValidationWarning w : warnings) {
            log.warn("{}: {} — table={}, column={}, record={}, detail={}",
                    w.anomalyId(), w.severity(), w.table(), w.column(), w.recordId(), w.detail());
        }

        return warnings;
    }
}
