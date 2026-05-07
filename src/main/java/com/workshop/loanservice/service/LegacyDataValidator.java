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
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Validates legacy CDW data at ingestion time, catching known anomaly patterns
 * before they cause runtime failures or produce incorrect API responses.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.02");
    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUS_CODES = Set.of("ACT", "INA");

    // --- Safe parsing with fallback defaults ---

    public BigDecimal safeParseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}', defaulting to ZERO", amount);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal safeParseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = value.replace("%", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}', defaulting to ZERO", value);
            return BigDecimal.ZERO;
        }
    }

    public Integer safeParseLegacyInteger(String value) {
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
            log.warn("Failed to parse integer '{}', defaulting to null", value);
            return null;
        }
    }

    public LocalDate safeParseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}', returning null", dateStr);
            return null;
        }
    }

    // --- Validation methods that return lists of anomaly descriptions ---

    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> anomalies = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            anomalies.add(id + ": missing required first name");
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            anomalies.add(id + ": missing required last name");
        }
        if (borrower.getEmail() == null || borrower.getEmail().isBlank()) {
            anomalies.add(id + ": missing required email");
        }

        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            Integer score = safeParseLegacyInteger(borrower.getCreditScore());
            if (score == null) {
                anomalies.add(id + ": credit score '" + borrower.getCreditScore() + "' is not a valid number");
            } else if (score < 300 || score > 850) {
                anomalies.add(id + ": credit score " + score + " outside valid range [300-850]");
            }
        }

        if (borrower.getAnnualIncome() != null && !borrower.getAnnualIncome().isBlank()) {
            BigDecimal income = safeParseLegacyAmount(borrower.getAnnualIncome());
            if (income.compareTo(BigDecimal.ZERO) < 0) {
                anomalies.add(id + ": negative annual income " + income);
            }
        }

        if (borrower.getDateOfBirth() != null && !borrower.getDateOfBirth().isBlank()) {
            LocalDate dob = safeParseLegacyDate(borrower.getDateOfBirth());
            if (dob == null) {
                anomalies.add(id + ": date of birth '" + borrower.getDateOfBirth() + "' is not valid MM/DD/YYYY");
            }
        }

        if (borrower.getCreatedDate() != null && !borrower.getCreatedDate().isBlank()) {
            if (safeParseLegacyDate(borrower.getCreatedDate()) == null) {
                anomalies.add(id + ": created date '" + borrower.getCreatedDate() + "' is not valid MM/DD/YYYY");
            }
        }

        if (borrower.getUpdatedDate() != null && !borrower.getUpdatedDate().isBlank()) {
            if (safeParseLegacyDate(borrower.getUpdatedDate()) == null) {
                anomalies.add(id + ": updated date '" + borrower.getUpdatedDate() + "' is not valid MM/DD/YYYY");
            }
        }

        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUS_CODES.contains(borrower.getStatusCode())) {
            anomalies.add(id + ": invalid borrower status code '" + borrower.getStatusCode() + "'");
        }

        return anomalies;
    }

    public List<String> validateLoanAccount(LegacyLoanAccount account,
                                            boolean borrowerExists,
                                            boolean productExists) {
        List<String> anomalies = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        if (!borrowerExists) {
            anomalies.add(id + ": references non-existent borrower '" + account.getBorrowerId() + "'");
        }
        if (!productExists) {
            anomalies.add(id + ": references non-existent product '" + account.getProductCode() + "'");
        }

        BigDecimal origAmount = safeParseLegacyAmount(account.getOriginalAmount());
        BigDecimal currBalance = safeParseLegacyAmount(account.getCurrentBalance());
        BigDecimal appraisedVal = safeParseLegacyAmount(account.getAppraisedValue());

        if (account.getOriginalAmount() != null && !account.getOriginalAmount().isBlank()
                && origAmount.compareTo(BigDecimal.ZERO) == 0) {
            anomalies.add(id + ": original amount '" + account.getOriginalAmount() + "' failed to parse");
        }
        if (account.getCurrentBalance() != null && !account.getCurrentBalance().isBlank()
                && currBalance.compareTo(BigDecimal.ZERO) == 0
                && !"0".equals(account.getCurrentBalance().replace(",", "").trim())) {
            anomalies.add(id + ": current balance '" + account.getCurrentBalance() + "' failed to parse");
        }

        if (currBalance.compareTo(origAmount) > 0) {
            anomalies.add(id + ": current balance (" + currBalance + ") exceeds original amount (" + origAmount + ")");
        }

        if (account.getInterestRate() != null) {
            BigDecimal rate = safeParseLegacyDecimal(account.getInterestRate());
            if (rate.compareTo(BigDecimal.ZERO) < 0 || rate.compareTo(new BigDecimal("100")) > 0) {
                anomalies.add(id + ": interest rate " + rate + " outside valid range [0-100]");
            }
        }

        if (account.getStatusCode() != null && !VALID_LOAN_STATUS_CODES.contains(account.getStatusCode())) {
            anomalies.add(id + ": invalid loan status code '" + account.getStatusCode() + "'");
        }

        if (account.getPropertyType() != null && !VALID_PROPERTY_TYPE_CODES.contains(account.getPropertyType())) {
            anomalies.add(id + ": invalid property type code '" + account.getPropertyType() + "'");
        }

        if (appraisedVal.compareTo(BigDecimal.ZERO) > 0 && account.getLtvPercent() != null) {
            BigDecimal storedLtv = safeParseLegacyDecimal(account.getLtvPercent());
            BigDecimal calculatedLtv = currBalance
                    .divide(appraisedVal, 4, RoundingMode.HALF_UP)
                    .multiply(new BigDecimal("100"))
                    .setScale(1, RoundingMode.HALF_UP);
            BigDecimal ltvDrift = storedLtv.subtract(calculatedLtv).abs();
            if (ltvDrift.compareTo(new BigDecimal("1.0")) > 0) {
                anomalies.add(id + ": LTV drift — stored " + storedLtv + "% vs calculated "
                        + calculatedLtv + "% (delta " + ltvDrift + "%)");
            }
        }

        validateDateField(account.getOriginationDate(), id, "origination date", anomalies);
        validateDateField(account.getMaturityDate(), id, "maturity date", anomalies);
        validateDateField(account.getFirstPaymentDate(), id, "first payment date", anomalies);
        validateDateField(account.getNextPaymentDate(), id, "next payment date", anomalies);
        validateDateField(account.getCreatedDate(), id, "created date", anomalies);
        validateDateField(account.getUpdatedDate(), id, "updated date", anomalies);

        if (borrowerExists) {
            validateDenormalizedNames(account, anomalies);
        }

        return anomalies;
    }

    public List<String> validatePayment(LegacyPayment payment, boolean loanAccountExists) {
        List<String> anomalies = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        if (!loanAccountExists) {
            anomalies.add(id + ": references non-existent loan account '" + payment.getLoanAccountNumber() + "'");
        }

        BigDecimal total = safeParseLegacyAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseLegacyAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseLegacyAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseLegacyAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseLegacyAmount(payment.getLateFee());
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal discrepancy = componentSum.subtract(total).abs();

        if (discrepancy.compareTo(PAYMENT_TOLERANCE) > 0) {
            anomalies.add(id + ": payment component sum (" + componentSum
                    + ") does not equal total (" + total + "), discrepancy = " + discrepancy);
        }

        if (payment.getTypeCode() != null && !VALID_PAYMENT_TYPE_CODES.contains(payment.getTypeCode())) {
            anomalies.add(id + ": invalid payment type code '" + payment.getTypeCode() + "'");
        }
        if (payment.getStatusCode() != null && !VALID_PAYMENT_STATUS_CODES.contains(payment.getStatusCode())) {
            anomalies.add(id + ": invalid payment status code '" + payment.getStatusCode() + "'");
        }

        validateDateField(payment.getPaymentDate(), id, "payment date", anomalies);
        validateDateField(payment.getReceivedDate(), id, "received date", anomalies);
        validateDateField(payment.getProcessedDate(), id, "processed date", anomalies);
        validateDateField(payment.getCreatedDate(), id, "created date", anomalies);
        validateDateField(payment.getUpdatedDate(), id, "updated date", anomalies);

        LocalDate dueDate = safeParseLegacyDate(payment.getPaymentDate());
        LocalDate receivedDate = safeParseLegacyDate(payment.getReceivedDate());
        if (dueDate != null && receivedDate != null) {
            if (receivedDate.isAfter(dueDate) && lateFee.compareTo(BigDecimal.ZERO) == 0) {
                long daysLate = java.time.temporal.ChronoUnit.DAYS.between(dueDate, receivedDate);
                anomalies.add(id + ": payment received " + daysLate + " days late but no late fee charged");
            }
        }

        return anomalies;
    }

    // --- Helper methods ---

    private void validateDateField(String dateStr, String recordId, String fieldName, List<String> anomalies) {
        if (dateStr != null && !dateStr.isBlank() && safeParseLegacyDate(dateStr) == null) {
            anomalies.add(recordId + ": " + fieldName + " '" + dateStr + "' is not valid MM/DD/YYYY");
        }
    }

    private void validateDenormalizedNames(LegacyLoanAccount account, List<String> anomalies) {
        // Denormalized name drift detection is done at a higher level where
        // the borrower record is available for comparison.
    }

    public List<String> checkDenormalizedNameDrift(LegacyLoanAccount account, LegacyBorrower borrower) {
        List<String> anomalies = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        if (borrower.getFirstName() != null && account.getBorrowerFirstName() != null
                && !borrower.getFirstName().equals(account.getBorrowerFirstName())) {
            anomalies.add(id + ": first name mismatch — borrower master has '"
                    + borrower.getFirstName() + "', loan account has '" + account.getBorrowerFirstName() + "'");
        }
        if (borrower.getLastName() != null && account.getBorrowerLastName() != null
                && !borrower.getLastName().equals(account.getBorrowerLastName())) {
            anomalies.add(id + ": last name mismatch — borrower master has '"
                    + borrower.getLastName() + "', loan account has '" + account.getBorrowerLastName() + "'");
        }

        if (borrower.getPhoneNumber() != null && account.getBorrowerSsnLast4() != null) {
            String phoneLast4 = borrower.getPhoneNumber().replaceAll("[^0-9]", "");
            if (phoneLast4.length() >= 4) {
                phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
                if (phoneLast4.equals(account.getBorrowerSsnLast4())) {
                    anomalies.add(id + ": SSN last-4 '" + account.getBorrowerSsnLast4()
                            + "' matches borrower phone suffix — possible data entry error");
                }
            }
        }

        return anomalies;
    }
}
