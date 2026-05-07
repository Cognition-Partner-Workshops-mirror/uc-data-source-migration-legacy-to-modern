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
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final BigDecimal COMPONENT_SUM_TOLERANCE = new BigDecimal("0.02");

    // --- Safe parsing with fallback defaults ---

    public BigDecimal parseLegacyAmountSafe(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        String cleaned = amount.replace(",", "").replace("$", "").trim();
        try {
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Unparseable amount in {} for record {}: '{}' -- defaulting to ZERO", fieldName, recordId, amount);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal parseLegacyDecimalSafe(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal in {} for record {}: '{}' -- defaulting to ZERO", fieldName, recordId, value);
            return BigDecimal.ZERO;
        }
    }

    public Integer parseLegacyIntegerSafe(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String cleaned = value.replace(",", "").trim();
        try {
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer in {} for record {}: '{}' -- defaulting to null", fieldName, recordId, value);
            return null;
        }
    }

    public LocalDate parseLegacyDateSafe(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Unparseable date in {} for record {}: '{}' -- expected MM/DD/YYYY", fieldName, recordId, dateStr);
            return null;
        }
    }

    public String formatDateToIso(String legacyDate, String fieldName, String recordId) {
        LocalDate parsed = parseLegacyDateSafe(legacyDate, fieldName, recordId);
        if (parsed == null) {
            return legacyDate;
        }
        return parsed.toString();
    }

    // --- Validation methods ---

    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add("Borrower " + id + ": missing first name");
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add("Borrower " + id + ": missing last name");
        }

        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            Integer score = parseLegacyIntegerSafe(borrower.getCreditScore(), "BORR_CRDT_SCR", id);
            if (score != null && (score < 300 || score > 850)) {
                warnings.add("Borrower " + id + ": credit score " + score + " outside valid range 300-850");
            }
        }

        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            warnings.add("Borrower " + id + ": unrecognized status code '" + borrower.getStatusCode() + "'");
        }

        if (borrower.getDateOfBirth() != null) {
            parseLegacyDateSafe(borrower.getDateOfBirth(), "BORR_DOB_DT", id);
        }
        if (borrower.getCreatedDate() != null) {
            parseLegacyDateSafe(borrower.getCreatedDate(), "BORR_CRET_DT", id);
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    public List<String> validateLoanAccount(LegacyLoanAccount acct) {
        List<String> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (acct.getStatusCode() == null || !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            warnings.add("Loan " + id + ": invalid status code '" + acct.getStatusCode() + "'");
        }

        if (acct.getPropertyType() != null && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            warnings.add("Loan " + id + ": unrecognized property type '" + acct.getPropertyType() + "'");
        }

        // Delinquency vs status cross-check
        Integer dlqDays = parseLegacyIntegerSafe(acct.getDelinquencyDays(), "LN_DLQ_DAYS", id);
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            warnings.add("Loan " + id + ": " + dlqDays + " delinquent days but status is ACT -- possible status lag");
        }

        // LTV consistency check
        BigDecimal origAmt = parseLegacyAmountSafe(acct.getOriginalAmount(), "LN_ORIG_AMT", id);
        BigDecimal appraisedVal = parseLegacyAmountSafe(acct.getAppraisedValue(), "PROP_APRS_VAL", id);
        BigDecimal storedLtv = parseLegacyDecimalSafe(acct.getLtvPercent(), "LN_LTV_PCT", id);
        if (appraisedVal.compareTo(BigDecimal.ZERO) > 0 && origAmt.compareTo(BigDecimal.ZERO) > 0) {
            BigDecimal calculatedLtv = origAmt.multiply(new BigDecimal("100"))
                    .divide(appraisedVal, 2, RoundingMode.HALF_UP);
            BigDecimal ltvDiff = calculatedLtv.subtract(storedLtv).abs();
            if (ltvDiff.compareTo(new BigDecimal("0.5")) > 0) {
                warnings.add("Loan " + id + ": stored LTV " + storedLtv + " differs from calculated "
                        + calculatedLtv + " by " + ltvDiff);
            }
        }

        // Date validation
        if (acct.getOriginationDate() != null) {
            parseLegacyDateSafe(acct.getOriginationDate(), "LN_ORIG_DT", id);
        }
        if (acct.getMaturityDate() != null) {
            parseLegacyDateSafe(acct.getMaturityDate(), "LN_MAT_DT", id);
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    public List<String> validatePayment(LegacyPayment pmt) {
        List<String> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (pmt.getTypeCode() == null || !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            warnings.add("Payment " + id + ": invalid type code '" + pmt.getTypeCode() + "'");
        }
        if (pmt.getStatusCode() == null || !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            warnings.add("Payment " + id + ": invalid status code '" + pmt.getStatusCode() + "'");
        }

        // Component sum check
        BigDecimal total = parseLegacyAmountSafe(pmt.getTotalAmount(), "PMT_AMT", id);
        BigDecimal principal = parseLegacyAmountSafe(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id);
        BigDecimal interest = parseLegacyAmountSafe(pmt.getInterestAmount(), "PMT_INT_AMT", id);
        BigDecimal escrow = parseLegacyAmountSafe(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id);
        BigDecimal lateFee = parseLegacyAmountSafe(pmt.getLateFee(), "PMT_LATE_FEE", id);

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal diff = componentSum.subtract(total).abs();
        if (diff.compareTo(COMPONENT_SUM_TOLERANCE) > 0) {
            warnings.add("Payment " + id + ": component sum " + componentSum
                    + " != total " + total + " (diff=" + diff + ")");
        }

        // Date ordering check
        LocalDate pmtDate = parseLegacyDateSafe(pmt.getPaymentDate(), "PMT_DT", id);
        LocalDate recvDate = parseLegacyDateSafe(pmt.getReceivedDate(), "PMT_RECV_DT", id);
        LocalDate procDate = parseLegacyDateSafe(pmt.getProcessedDate(), "PMT_PROC_DT", id);

        if (pmtDate != null && recvDate != null && recvDate.isBefore(pmtDate)) {
            warnings.add("Payment " + id + ": received date " + recvDate + " is before payment date " + pmtDate);
        }
        if (recvDate != null && procDate != null && procDate.isBefore(recvDate)) {
            warnings.add("Payment " + id + ": processed date " + procDate + " is before received date " + recvDate);
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    public String resolveEffectiveLoanStatus(String statusCode, String delinquencyDaysStr, String loanId) {
        if (statusCode == null) {
            return "Unknown";
        }
        Integer dlqDays = parseLegacyIntegerSafe(delinquencyDaysStr, "LN_DLQ_DAYS", loanId);
        if ("ACT".equals(statusCode) && dlqDays != null && dlqDays > 0) {
            return "Active (Delinquent)";
        }
        return switch (statusCode) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> statusCode;
        };
    }
}
