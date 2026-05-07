package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.DataAnomaly.Severity;
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

    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_BORROWER_STATUS_CODES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");

    private static final BigDecimal COMPONENT_SUM_TOLERANCE = new BigDecimal("0.01");

    public List<DataAnomaly> validateBorrower(LegacyBorrower borrower) {
        List<DataAnomaly> anomalies = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (isBlank(borrower.getFirstName())) {
            anomalies.add(new DataAnomaly(Severity.CRITICAL, "CDW_BORR_MSTR", "BORR_FST_NM", id,
                    "First name is null or blank"));
        }
        if (isBlank(borrower.getLastName())) {
            anomalies.add(new DataAnomaly(Severity.CRITICAL, "CDW_BORR_MSTR", "BORR_LST_NM", id,
                    "Last name is null or blank"));
        }

        if (!isBlank(borrower.getCreditScore())) {
            Integer score = parseSafeInteger(borrower.getCreditScore());
            if (score == null) {
                anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_BORR_MSTR", "BORR_CRDT_SCR", id,
                        "Credit score is not a valid integer: '" + borrower.getCreditScore() + "'"));
            } else if (score < 300 || score > 850) {
                anomalies.add(new DataAnomaly(Severity.MEDIUM, "CDW_BORR_MSTR", "BORR_CRDT_SCR", id,
                        "Credit score out of valid range (300-850): " + score));
            }
        }

        if (!isBlank(borrower.getAnnualIncome())) {
            BigDecimal income = parseSafeAmount(borrower.getAnnualIncome());
            if (income == null) {
                anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_BORR_MSTR", "BORR_ANN_INCM", id,
                        "Annual income is not a valid amount: '" + borrower.getAnnualIncome() + "'"));
            } else if (income.compareTo(BigDecimal.ZERO) < 0) {
                anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_BORR_MSTR", "BORR_ANN_INCM", id,
                        "Annual income is negative: " + income));
            }
        }

        validateDateField(anomalies, borrower.getDateOfBirth(), "CDW_BORR_MSTR", "BORR_DOB_DT", id);
        validateDateField(anomalies, borrower.getCreatedDate(), "CDW_BORR_MSTR", "BORR_CRET_DT", id);
        validateDateField(anomalies, borrower.getUpdatedDate(), "CDW_BORR_MSTR", "BORR_UPDT_DT", id);

        if (!isBlank(borrower.getStatusCode()) && !VALID_BORROWER_STATUS_CODES.contains(borrower.getStatusCode())) {
            anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_BORR_MSTR", "BORR_STAT_CD", id,
                    "Invalid borrower status code: '" + borrower.getStatusCode() + "'"));
        }

        for (DataAnomaly anomaly : anomalies) {
            log.warn("Data anomaly detected: {}", anomaly);
        }

        return anomalies;
    }

    public List<DataAnomaly> validateLoanAccount(LegacyLoanAccount acct,
                                                  boolean borrowerExists,
                                                  boolean productExists) {
        List<DataAnomaly> anomalies = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (!borrowerExists) {
            anomalies.add(new DataAnomaly(Severity.CRITICAL, "CDW_LN_ACCT", "BORR_ID", id,
                    "Orphaned loan: borrower '" + acct.getBorrowerId() + "' does not exist in CDW_BORR_MSTR"));
        }

        if (!productExists) {
            anomalies.add(new DataAnomaly(Severity.CRITICAL, "CDW_LN_ACCT", "PROD_CD", id,
                    "Orphaned loan: product '" + acct.getProductCode() + "' does not exist in CDW_LN_PROD"));
        }

        BigDecimal origAmount = validateAmountField(anomalies, acct.getOriginalAmount(),
                "CDW_LN_ACCT", "LN_ORIG_AMT", id);
        validateAmountField(anomalies, acct.getCurrentBalance(), "CDW_LN_ACCT", "LN_CURR_BAL", id);
        validateAmountField(anomalies, acct.getMonthlyPayment(), "CDW_LN_ACCT", "LN_PMT_AMT", id);
        validateAmountField(anomalies, acct.getEscrowBalance(), "CDW_LN_ACCT", "LN_ESCROW_BAL", id);
        BigDecimal appraisedValue = validateAmountField(anomalies, acct.getAppraisedValue(),
                "CDW_LN_ACCT", "PROP_APRS_VAL", id);

        if (!isBlank(acct.getInterestRate())) {
            BigDecimal rate = parseSafeDecimal(acct.getInterestRate());
            if (rate == null) {
                anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_LN_ACCT", "LN_INT_RT", id,
                        "Interest rate is not a valid decimal: '" + acct.getInterestRate() + "'"));
            } else if (rate.compareTo(BigDecimal.ZERO) <= 0 || rate.compareTo(new BigDecimal("30")) > 0) {
                anomalies.add(new DataAnomaly(Severity.MEDIUM, "CDW_LN_ACCT", "LN_INT_RT", id,
                        "Interest rate out of expected range (0-30%): " + rate));
            }
        }

        validateDateField(anomalies, acct.getOriginationDate(), "CDW_LN_ACCT", "LN_ORIG_DT", id);
        validateDateField(anomalies, acct.getMaturityDate(), "CDW_LN_ACCT", "LN_MAT_DT", id);
        validateDateField(anomalies, acct.getFirstPaymentDate(), "CDW_LN_ACCT", "LN_1ST_PMT_DT", id);
        validateDateField(anomalies, acct.getNextPaymentDate(), "CDW_LN_ACCT", "LN_NXT_PMT_DT", id);

        if (!isBlank(acct.getStatusCode()) && !VALID_LOAN_STATUS_CODES.contains(acct.getStatusCode())) {
            anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_LN_ACCT", "LN_STAT_CD", id,
                    "Invalid loan status code: '" + acct.getStatusCode() + "'"));
        }

        Integer dlqDays = parseSafeInteger(acct.getDelinquencyDays());
        if (!isBlank(acct.getDelinquencyDays()) && dlqDays == null) {
            anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_LN_ACCT", "LN_DLQ_DAYS", id,
                    "Delinquency days is not a valid integer: '" + acct.getDelinquencyDays() + "'"));
        }

        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_LN_ACCT", "LN_STAT_CD", id,
                    "Loan is " + dlqDays + " days delinquent but status is ACT (Active)"));
        }

        if (!isBlank(acct.getPropertyType()) && !VALID_PROPERTY_TYPE_CODES.contains(acct.getPropertyType())) {
            anomalies.add(new DataAnomaly(Severity.MEDIUM, "CDW_LN_ACCT", "PROP_TYP_CD", id,
                    "Invalid property type code: '" + acct.getPropertyType() + "'"));
        }

        if (origAmount != null && appraisedValue != null
                && appraisedValue.compareTo(BigDecimal.ZERO) > 0 && !isBlank(acct.getLtvPercent())) {
            BigDecimal storedLtv = parseSafeDecimal(acct.getLtvPercent());
            if (storedLtv != null) {
                BigDecimal calculatedLtv = origAmount
                        .divide(appraisedValue, 4, RoundingMode.HALF_UP)
                        .multiply(new BigDecimal("100"))
                        .setScale(1, RoundingMode.HALF_UP);
                BigDecimal ltvDelta = storedLtv.subtract(calculatedLtv).abs();
                if (ltvDelta.compareTo(new BigDecimal("0.5")) > 0) {
                    anomalies.add(new DataAnomaly(Severity.MEDIUM, "CDW_LN_ACCT", "LN_LTV_PCT", id,
                            "LTV mismatch: stored=" + storedLtv + "%, calculated=" + calculatedLtv
                                    + "% (delta=" + ltvDelta + "%)"));
                }
            }
        }

        for (DataAnomaly anomaly : anomalies) {
            log.warn("Data anomaly detected: {}", anomaly);
        }

        return anomalies;
    }

    public List<DataAnomaly> validatePayment(LegacyPayment pmt, boolean loanAccountExists) {
        List<DataAnomaly> anomalies = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (!loanAccountExists) {
            anomalies.add(new DataAnomaly(Severity.CRITICAL, "CDW_PMT_HIST", "LN_ACCT_NBR", id,
                    "Orphaned payment: loan account '" + pmt.getLoanAccountNumber()
                            + "' does not exist in CDW_LN_ACCT"));
        }

        BigDecimal total = validateAmountField(anomalies, pmt.getTotalAmount(),
                "CDW_PMT_HIST", "PMT_AMT", id);
        BigDecimal principal = validateAmountField(anomalies, pmt.getPrincipalAmount(),
                "CDW_PMT_HIST", "PMT_PRIN_AMT", id);
        BigDecimal interest = validateAmountField(anomalies, pmt.getInterestAmount(),
                "CDW_PMT_HIST", "PMT_INT_AMT", id);
        BigDecimal escrow = validateAmountField(anomalies, pmt.getEscrowAmount(),
                "CDW_PMT_HIST", "PMT_ESCROW_AMT", id);
        BigDecimal lateFee = validateAmountField(anomalies, pmt.getLateFee(),
                "CDW_PMT_HIST", "PMT_LATE_FEE", id);

        if (total != null && principal != null && interest != null && escrow != null && lateFee != null) {
            BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
            BigDecimal delta = total.subtract(componentSum).abs();
            if (delta.compareTo(COMPONENT_SUM_TOLERANCE) > 0) {
                anomalies.add(new DataAnomaly(Severity.CRITICAL, "CDW_PMT_HIST", "PMT_AMT", id,
                        "Payment component mismatch: total=" + total + " but components sum to "
                                + componentSum + " (delta=" + delta + ")"));
            }
        }

        if (!isBlank(pmt.getTypeCode()) && !VALID_PAYMENT_TYPE_CODES.contains(pmt.getTypeCode())) {
            anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_PMT_HIST", "PMT_TYP_CD", id,
                    "Invalid payment type code: '" + pmt.getTypeCode() + "'"));
        }

        if (!isBlank(pmt.getStatusCode()) && !VALID_PAYMENT_STATUS_CODES.contains(pmt.getStatusCode())) {
            anomalies.add(new DataAnomaly(Severity.HIGH, "CDW_PMT_HIST", "PMT_STAT_CD", id,
                    "Invalid payment status code: '" + pmt.getStatusCode() + "'"));
        }

        LocalDate paymentDate = validateDateField(anomalies, pmt.getPaymentDate(),
                "CDW_PMT_HIST", "PMT_DT", id);
        LocalDate receivedDate = validateDateField(anomalies, pmt.getReceivedDate(),
                "CDW_PMT_HIST", "PMT_RECV_DT", id);
        LocalDate processedDate = validateDateField(anomalies, pmt.getProcessedDate(),
                "CDW_PMT_HIST", "PMT_PROC_DT", id);

        if (paymentDate != null && receivedDate != null && receivedDate.isBefore(paymentDate)) {
            anomalies.add(new DataAnomaly(Severity.MEDIUM, "CDW_PMT_HIST", "PMT_RECV_DT", id,
                    "Received date (" + pmt.getReceivedDate() + ") is before payment date ("
                            + pmt.getPaymentDate() + ")"));
        }
        if (receivedDate != null && processedDate != null && processedDate.isBefore(receivedDate)) {
            anomalies.add(new DataAnomaly(Severity.MEDIUM, "CDW_PMT_HIST", "PMT_PROC_DT", id,
                    "Processed date (" + pmt.getProcessedDate() + ") is before received date ("
                            + pmt.getReceivedDate() + ")"));
        }

        for (DataAnomaly anomaly : anomalies) {
            log.warn("Data anomaly detected: {}", anomaly);
        }

        return anomalies;
    }

    public BigDecimal parseSafeAmount(String amount) {
        if (isBlank(amount)) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").replace(" ", "").trim();
            if (cleaned.startsWith("(") && cleaned.endsWith(")")) {
                cleaned = "-" + cleaned.substring(1, cleaned.length() - 1);
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
            return null;
        }
    }

    public BigDecimal parseSafeDecimal(String value) {
        if (isBlank(value)) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}': {}", value, e.getMessage());
            return null;
        }
    }

    public Integer parseSafeInteger(String value) {
        if (isBlank(value)) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    public LocalDate parseSafeDate(String dateStr) {
        if (isBlank(dateStr)) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    private LocalDate validateDateField(List<DataAnomaly> anomalies, String dateStr,
                                        String table, String column, String recordId) {
        if (isBlank(dateStr)) {
            return null;
        }
        LocalDate parsed = parseSafeDate(dateStr);
        if (parsed == null) {
            anomalies.add(new DataAnomaly(Severity.HIGH, table, column, recordId,
                    "Date is not in expected MM/DD/YYYY format: '" + dateStr + "'"));
        }
        return parsed;
    }

    private BigDecimal validateAmountField(List<DataAnomaly> anomalies, String amount,
                                           String table, String column, String recordId) {
        if (isBlank(amount)) {
            return BigDecimal.ZERO;
        }
        BigDecimal parsed = parseSafeAmount(amount);
        if (parsed == null) {
            anomalies.add(new DataAnomaly(Severity.HIGH, table, column, recordId,
                    "Amount is not a valid number: '" + amount + "'"));
        }
        return parsed;
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
