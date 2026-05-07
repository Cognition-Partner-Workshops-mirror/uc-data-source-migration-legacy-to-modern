package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.DataQualityWarning.Severity;
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
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FMT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.01");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");

    // --- Borrower validation ---

    public List<DataQualityWarning> validateBorrower(LegacyBorrower b) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = b.getBorrowerId();

        if (isBlank(b.getFirstName())) {
            warnings.add(new DataQualityWarning("ANM-010", Severity.HIGH,
                    "CDW_BORR_MSTR", "BORR_FST_NM", id, "Required field first name is null/blank"));
        }
        if (isBlank(b.getLastName())) {
            warnings.add(new DataQualityWarning("ANM-010", Severity.HIGH,
                    "CDW_BORR_MSTR", "BORR_LST_NM", id, "Required field last name is null/blank"));
        }
        if (!isBlank(b.getCreditScore())) {
            Integer score = safeParseInteger(b.getCreditScore());
            if (score == null) {
                warnings.add(new DataQualityWarning("ANM-004", Severity.HIGH,
                        "CDW_BORR_MSTR", "BORR_CRDT_SCR", id,
                        "Credit score is not a valid integer: '" + b.getCreditScore() + "'"));
            } else if (score < 300 || score > 850) {
                warnings.add(new DataQualityWarning("ANM-004", Severity.MEDIUM,
                        "CDW_BORR_MSTR", "BORR_CRDT_SCR", id,
                        "Credit score out of valid range (300-850): " + score));
            }
        }
        if (!isBlank(b.getAnnualIncome())) {
            BigDecimal income = safeParseAmount(b.getAnnualIncome());
            if (income == null) {
                warnings.add(new DataQualityWarning("ANM-004", Severity.HIGH,
                        "CDW_BORR_MSTR", "BORR_ANN_INCM", id,
                        "Annual income is not a valid amount: '" + b.getAnnualIncome() + "'"));
            }
        }
        if (!isBlank(b.getDateOfBirth())) {
            if (safeParseLegacyDate(b.getDateOfBirth()) == null) {
                warnings.add(new DataQualityWarning("ANM-007", Severity.MEDIUM,
                        "CDW_BORR_MSTR", "BORR_DOB_DT", id,
                        "Date of birth is not valid MM/DD/YYYY: '" + b.getDateOfBirth() + "'"));
            }
        }
        if (!isBlank(b.getStatusCode()) && !VALID_BORROWER_STATUSES.contains(b.getStatusCode())) {
            warnings.add(new DataQualityWarning("ANM-004", Severity.MEDIUM,
                    "CDW_BORR_MSTR", "BORR_STAT_CD", id,
                    "Unknown borrower status code: '" + b.getStatusCode() + "'"));
        }

        for (DataQualityWarning w : warnings) {
            log.warn("Data quality: {}", w);
        }
        return warnings;
    }

    // --- Loan account validation ---

    public List<DataQualityWarning> validateLoanAccount(LegacyLoanAccount acct,
                                                         LegacyBorrower borrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (isBlank(acct.getStatusCode())) {
            warnings.add(new DataQualityWarning("ANM-010", Severity.HIGH,
                    "CDW_LN_ACCT", "LN_STAT_CD", id, "Required field status code is null/blank"));
        } else if (!VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            warnings.add(new DataQualityWarning("ANM-004", Severity.MEDIUM,
                    "CDW_LN_ACCT", "LN_STAT_CD", id,
                    "Unknown loan status code: '" + acct.getStatusCode() + "'"));
        }

        // ANM-005: delinquent loan with active status
        Integer dlqDays = safeParseInteger(acct.getDelinquencyDays());
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            warnings.add(new DataQualityWarning("ANM-005", Severity.HIGH,
                    "CDW_LN_ACCT", "LN_DLQ_DAYS+LN_STAT_CD", id,
                    "Loan is " + dlqDays + " days delinquent but status is ACT"));
        }

        // ANM-001: SSN last-4 matches phone last-4
        if (borrower != null && !isBlank(acct.getBorrowerSsnLast4())
                && !isBlank(borrower.getPhoneNumber())) {
            String phoneLast4 = extractLast4(borrower.getPhoneNumber());
            if (acct.getBorrowerSsnLast4().equals(phoneLast4)) {
                warnings.add(new DataQualityWarning("ANM-001", Severity.CRITICAL,
                        "CDW_LN_ACCT", "BORR_SSN_LST4", id,
                        "SSN last-4 '" + acct.getBorrowerSsnLast4()
                                + "' matches phone last-4 — likely wrong source field"));
            }
        }

        // ANM-006: denormalized name drift
        if (borrower != null) {
            if (!isBlank(acct.getBorrowerFirstName())
                    && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
                warnings.add(new DataQualityWarning("ANM-006", Severity.MEDIUM,
                        "CDW_LN_ACCT", "BORR_FST_NM", id,
                        "Denormalized first name '" + acct.getBorrowerFirstName()
                                + "' differs from master '" + borrower.getFirstName() + "'"));
            }
            if (!isBlank(acct.getBorrowerLastName())
                    && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
                warnings.add(new DataQualityWarning("ANM-006", Severity.MEDIUM,
                        "CDW_LN_ACCT", "BORR_LST_NM", id,
                        "Denormalized last name '" + acct.getBorrowerLastName()
                                + "' differs from master '" + borrower.getLastName() + "'"));
            }
        }

        if (!isBlank(acct.getPropertyType()) && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            warnings.add(new DataQualityWarning("ANM-004", Severity.MEDIUM,
                    "CDW_LN_ACCT", "PROP_TYP_CD", id,
                    "Unknown property type code: '" + acct.getPropertyType() + "'"));
        }

        // ANM-009: LTV rounding check
        BigDecimal origAmt = safeParseAmount(acct.getOriginalAmount());
        BigDecimal appraisedVal = safeParseAmount(acct.getAppraisedValue());
        BigDecimal storedLtv = safeParseDecimal(acct.getLtvPercent());
        if (origAmt != null && appraisedVal != null && storedLtv != null
                && appraisedVal.compareTo(BigDecimal.ZERO) > 0) {
            BigDecimal computedLtv = origAmt.multiply(new BigDecimal("100"))
                    .divide(appraisedVal, 2, RoundingMode.HALF_UP);
            if (computedLtv.subtract(storedLtv).abs().compareTo(new BigDecimal("0.2")) > 0) {
                warnings.add(new DataQualityWarning("ANM-009", Severity.LOW,
                        "CDW_LN_ACCT", "LN_LTV_PCT", id,
                        "Stored LTV " + storedLtv + "% differs from computed "
                                + computedLtv + "%"));
            }
        }

        // Validate numeric fields parse correctly
        validateAmount(warnings, id, "CDW_LN_ACCT", "LN_ORIG_AMT", acct.getOriginalAmount());
        validateAmount(warnings, id, "CDW_LN_ACCT", "LN_CURR_BAL", acct.getCurrentBalance());
        validateAmount(warnings, id, "CDW_LN_ACCT", "LN_PMT_AMT", acct.getMonthlyPayment());
        validateDecimal(warnings, id, "CDW_LN_ACCT", "LN_INT_RT", acct.getInterestRate());
        validateDate(warnings, id, "CDW_LN_ACCT", "LN_ORIG_DT", acct.getOriginationDate());
        validateDate(warnings, id, "CDW_LN_ACCT", "LN_MAT_DT", acct.getMaturityDate());

        for (DataQualityWarning w : warnings) {
            log.warn("Data quality: {}", w);
        }
        return warnings;
    }

    // --- Payment validation ---

    public List<DataQualityWarning> validatePayment(LegacyPayment pmt) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        // ANM-002: component sum check
        BigDecimal total = safeParseAmount(pmt.getTotalAmount());
        BigDecimal principal = safeParseAmount(pmt.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(pmt.getInterestAmount());
        BigDecimal escrow = safeParseAmount(pmt.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(pmt.getLateFee());

        if (total != null && principal != null && interest != null
                && escrow != null && lateFee != null) {
            BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
            BigDecimal discrepancy = componentSum.subtract(total).abs();
            if (discrepancy.compareTo(PAYMENT_TOLERANCE) > 0) {
                warnings.add(new DataQualityWarning("ANM-002", Severity.CRITICAL,
                        "CDW_PMT_HIST", "PMT_AMT", id,
                        "Component sum (" + componentSum + ") differs from total ("
                                + total + ") by " + discrepancy));
            }
        }

        if (!isBlank(pmt.getTypeCode()) && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            warnings.add(new DataQualityWarning("ANM-004", Severity.MEDIUM,
                    "CDW_PMT_HIST", "PMT_TYP_CD", id,
                    "Unknown payment type code: '" + pmt.getTypeCode() + "'"));
        }
        if (!isBlank(pmt.getStatusCode()) && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            warnings.add(new DataQualityWarning("ANM-004", Severity.MEDIUM,
                    "CDW_PMT_HIST", "PMT_STAT_CD", id,
                    "Unknown payment status code: '" + pmt.getStatusCode() + "'"));
        }

        // ANM-011: received after payment date with no late fee
        LocalDate pmtDate = safeParseLegacyDate(pmt.getPaymentDate());
        LocalDate rcvDate = safeParseLegacyDate(pmt.getReceivedDate());
        if (pmtDate != null && rcvDate != null && rcvDate.isAfter(pmtDate)) {
            long daysLate = rcvDate.toEpochDay() - pmtDate.toEpochDay();
            if (daysLate > 15 && (lateFee == null || lateFee.compareTo(BigDecimal.ZERO) == 0)) {
                warnings.add(new DataQualityWarning("ANM-011", Severity.LOW,
                        "CDW_PMT_HIST", "PMT_LATE_FEE", id,
                        "Payment received " + daysLate + " days late but no late fee charged"));
            }
        }

        validateAmount(warnings, id, "CDW_PMT_HIST", "PMT_AMT", pmt.getTotalAmount());
        validateAmount(warnings, id, "CDW_PMT_HIST", "PMT_PRIN_AMT", pmt.getPrincipalAmount());
        validateAmount(warnings, id, "CDW_PMT_HIST", "PMT_INT_AMT", pmt.getInterestAmount());
        validateDate(warnings, id, "CDW_PMT_HIST", "PMT_DT", pmt.getPaymentDate());

        for (DataQualityWarning w : warnings) {
            log.warn("Data quality: {}", w);
        }
        return warnings;
    }

    // --- Safe parsing utilities (public for reuse in LoanService) ---

    public BigDecimal safeParseAmount(String amount) {
        if (isBlank(amount)) return null;
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public BigDecimal safeParseDecimal(String value) {
        if (isBlank(value)) return null;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public Integer safeParseInteger(String value) {
        if (isBlank(value)) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public LocalDate safeParseLegacyDate(String value) {
        if (isBlank(value)) return null;
        try {
            return LocalDate.parse(value.trim(), LEGACY_DATE_FMT);
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    // --- Private helpers ---

    private void validateAmount(List<DataQualityWarning> warnings, String recordId,
                                String table, String column, String value) {
        if (!isBlank(value) && safeParseAmount(value) == null) {
            warnings.add(new DataQualityWarning("ANM-004", Severity.HIGH,
                    table, column, recordId,
                    "Value is not a valid amount: '" + value + "'"));
        }
    }

    private void validateDecimal(List<DataQualityWarning> warnings, String recordId,
                                 String table, String column, String value) {
        if (!isBlank(value) && safeParseDecimal(value) == null) {
            warnings.add(new DataQualityWarning("ANM-004", Severity.HIGH,
                    table, column, recordId,
                    "Value is not a valid decimal: '" + value + "'"));
        }
    }

    private void validateDate(List<DataQualityWarning> warnings, String recordId,
                              String table, String column, String value) {
        if (!isBlank(value) && safeParseLegacyDate(value) == null) {
            warnings.add(new DataQualityWarning("ANM-007", Severity.MEDIUM,
                    table, column, recordId,
                    "Value is not valid MM/DD/YYYY: '" + value + "'"));
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private String extractLast4(String phone) {
        if (phone == null) return "";
        String digits = phone.replaceAll("[^0-9]", "");
        return digits.length() >= 4 ? digits.substring(digits.length() - 4) : digits;
    }
}
