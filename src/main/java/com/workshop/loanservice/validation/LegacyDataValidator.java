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

/**
 * Validates legacy CDW data at ingestion time, detecting anomalies
 * documented in docs/DATA_ANOMALY_REPORT.md.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.01");

    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_BORROWER_STATUS_CODES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");

    // --- Amount parsing with error handling ---

    public BigDecimal parseAmount(String amount, String recordId, String field,
                                  List<DataQualityWarning> warnings) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(amount.replace(",", ""));
        } catch (NumberFormatException e) {
            warnings.add(new DataQualityWarning(
                    Severity.CRITICAL, recordId, field,
                    "Unparseable amount value; defaulting to 0", amount));
            log.warn("Failed to parse amount for {}.{}: '{}'", recordId, field, amount);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal parseDecimal(String value, String recordId, String field,
                                   List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            warnings.add(new DataQualityWarning(
                    Severity.CRITICAL, recordId, field,
                    "Unparseable decimal value; defaulting to 0", value));
            log.warn("Failed to parse decimal for {}.{}: '{}'", recordId, field, value);
            return BigDecimal.ZERO;
        }
    }

    public Integer parseInteger(String value, String recordId, String field,
                                List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            warnings.add(new DataQualityWarning(
                    Severity.CRITICAL, recordId, field,
                    "Unparseable integer value; defaulting to null", value));
            log.warn("Failed to parse integer for {}.{}: '{}'", recordId, field, value);
            return null;
        }
    }

    // --- Date validation ---

    public String validateAndFormatDate(String dateStr, String recordId, String field,
                                        List<DataQualityWarning> warnings) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate parsed = LocalDate.parse(dateStr, LEGACY_DATE_FORMAT);
            return parsed.toString(); // ISO-8601: yyyy-MM-dd
        } catch (DateTimeParseException e) {
            warnings.add(new DataQualityWarning(
                    Severity.MEDIUM, recordId, field,
                    "Invalid date format (expected MM/DD/YYYY); passing through raw value",
                    dateStr));
            log.warn("Invalid date for {}.{}: '{}'", recordId, field, dateStr);
            return dateStr;
        }
    }

    // --- Null-safe string helpers ---

    public String safeString(String value, String fallback) {
        return (value != null && !value.isBlank()) ? value : fallback;
    }

    public String buildBorrowerName(String firstName, String lastName,
                                    String recordId, List<DataQualityWarning> warnings) {
        if (firstName == null || firstName.isBlank()) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, recordId, "borrowerFirstName",
                    "Null/blank first name in loan account", firstName));
        }
        if (lastName == null || lastName.isBlank()) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, recordId, "borrowerLastName",
                    "Null/blank last name in loan account", lastName));
        }
        String first = safeString(firstName, "Unknown");
        String last = safeString(lastName, "Unknown");
        return first + " " + last;
    }

    public String buildPropertyAddress(String address, String city, String state,
                                       String zip, String recordId,
                                       List<DataQualityWarning> warnings) {
        if (address == null && city == null && state == null && zip == null) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, recordId, "propertyAddress",
                    "All property address fields are null", null));
            return "Unknown";
        }
        return safeString(address, "") + ", "
                + safeString(city, "") + ", "
                + safeString(state, "") + " "
                + safeString(zip, "");
    }

    // --- Status code validation ---

    public String validateStatusCode(String code, Set<String> validCodes,
                                     String recordId, String field,
                                     List<DataQualityWarning> warnings) {
        if (code == null || code.isBlank()) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, recordId, field,
                    "Null/blank status code", code));
            return code;
        }
        if (!validCodes.contains(code)) {
            warnings.add(new DataQualityWarning(
                    Severity.MEDIUM, recordId, field,
                    "Unrecognized status code", code));
        }
        return code;
    }

    // --- Cross-field validation ---

    public void validatePaymentComponents(String paymentId, BigDecimal total,
                                          BigDecimal principal, BigDecimal interest,
                                          BigDecimal escrow, BigDecimal lateFee,
                                          List<DataQualityWarning> warnings) {
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal diff = total.subtract(componentSum).abs();
        if (diff.compareTo(PAYMENT_TOLERANCE) > 0) {
            warnings.add(new DataQualityWarning(
                    Severity.CRITICAL, paymentId, "paymentComponents",
                    "Component sum (" + componentSum.setScale(2, RoundingMode.HALF_UP)
                            + ") does not match total (" + total.setScale(2, RoundingMode.HALF_UP)
                            + "); difference: " + diff.setScale(2, RoundingMode.HALF_UP),
                    "total=" + total + " components=" + componentSum));
        }
    }

    public void validateSsnLast4AgainstPhone(String ssnLast4, String phoneNumber,
                                             String recordId,
                                             List<DataQualityWarning> warnings) {
        if (ssnLast4 == null || phoneNumber == null) {
            return;
        }
        String phoneLast4 = phoneNumber.replaceAll("[^0-9]", "");
        if (phoneLast4.length() >= 4) {
            phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
            if (ssnLast4.equals(phoneLast4)) {
                warnings.add(new DataQualityWarning(
                        Severity.CRITICAL, recordId, "borrowerSsnLast4",
                        "SSN last-4 matches phone number last-4 — likely populated from wrong source",
                        "ssn4=" + ssnLast4 + " phone=" + phoneNumber));
            }
        }
    }

    public void validateDenormalizedBorrowerName(LegacyLoanAccount acct,
                                                 LegacyBorrower borrower,
                                                 List<DataQualityWarning> warnings) {
        if (borrower == null || acct == null) {
            return;
        }
        if (acct.getBorrowerFirstName() != null && borrower.getFirstName() != null
                && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
            warnings.add(new DataQualityWarning(
                    Severity.MEDIUM, acct.getLoanAccountNumber(), "borrowerFirstName",
                    "Denormalized first name differs from master record",
                    "loan=" + acct.getBorrowerFirstName() + " master=" + borrower.getFirstName()));
        }
        if (acct.getBorrowerLastName() != null && borrower.getLastName() != null
                && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
            warnings.add(new DataQualityWarning(
                    Severity.MEDIUM, acct.getLoanAccountNumber(), "borrowerLastName",
                    "Denormalized last name differs from master record",
                    "loan=" + acct.getBorrowerLastName() + " master=" + borrower.getLastName()));
        }
    }

    public void validateLateFeeConsistency(LegacyPayment payment,
                                           List<DataQualityWarning> warnings) {
        if (payment.getReceivedDate() == null || payment.getPaymentDate() == null) {
            return;
        }
        try {
            LocalDate dueDate = LocalDate.parse(payment.getPaymentDate(), LEGACY_DATE_FORMAT);
            LocalDate recvDate = LocalDate.parse(payment.getReceivedDate(), LEGACY_DATE_FORMAT);
            long daysLate = java.time.temporal.ChronoUnit.DAYS.between(dueDate, recvDate);
            BigDecimal lateFee = parseAmountQuiet(payment.getLateFee());
            if (daysLate > 3 && lateFee.compareTo(BigDecimal.ZERO) == 0) {
                warnings.add(new DataQualityWarning(
                        Severity.LOW, payment.getPaymentSequenceNumber(), "lateFee",
                        "Payment received " + daysLate + " days late but no late fee charged",
                        "dueDate=" + payment.getPaymentDate()
                                + " recvDate=" + payment.getReceivedDate()));
            }
        } catch (DateTimeParseException e) {
            // Date validation handled separately
        }
    }

    // --- Borrower-level validation ---

    public List<DataQualityWarning> validateBorrower(LegacyBorrower borrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, id, "firstName",
                    "Required field is null/blank", borrower.getFirstName()));
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, id, "lastName",
                    "Required field is null/blank", borrower.getLastName()));
        }
        if (borrower.getSsnEncrypted() == null || borrower.getSsnEncrypted().isBlank()) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, id, "ssnEncrypted",
                    "Required field is null/blank", borrower.getSsnEncrypted()));
        }

        validateAndFormatDate(borrower.getDateOfBirth(), id, "dateOfBirth", warnings);
        validateAndFormatDate(borrower.getCreatedDate(), id, "createdDate", warnings);
        validateAndFormatDate(borrower.getUpdatedDate(), id, "updatedDate", warnings);

        Integer creditScore = parseInteger(borrower.getCreditScore(), id, "creditScore", warnings);
        if (creditScore != null && (creditScore < 300 || creditScore > 850)) {
            warnings.add(new DataQualityWarning(
                    Severity.MEDIUM, id, "creditScore",
                    "Credit score outside valid range (300-850)",
                    borrower.getCreditScore()));
        }

        parseAmount(borrower.getAnnualIncome(), id, "annualIncome", warnings);

        validateStatusCode(borrower.getStatusCode(), VALID_BORROWER_STATUS_CODES,
                id, "statusCode", warnings);

        return warnings;
    }

    // --- Loan account-level validation ---

    public List<DataQualityWarning> validateLoanAccount(LegacyLoanAccount acct) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (acct.getBorrowerId() == null || acct.getBorrowerId().isBlank()) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, id, "borrowerId",
                    "Required field is null/blank", acct.getBorrowerId()));
        }
        if (acct.getProductCode() == null || acct.getProductCode().isBlank()) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, id, "productCode",
                    "Required field is null/blank", acct.getProductCode()));
        }

        parseAmount(acct.getOriginalAmount(), id, "originalAmount", warnings);
        parseAmount(acct.getCurrentBalance(), id, "currentBalance", warnings);
        parseDecimal(acct.getInterestRate(), id, "interestRate", warnings);
        parseAmount(acct.getMonthlyPayment(), id, "monthlyPayment", warnings);
        parseAmount(acct.getEscrowBalance(), id, "escrowBalance", warnings);
        parseDecimal(acct.getLtvPercent(), id, "ltvPercent", warnings);
        parseAmount(acct.getAppraisedValue(), id, "appraisedValue", warnings);
        parseInteger(acct.getTermMonths(), id, "termMonths", warnings);
        parseInteger(acct.getDelinquencyDays(), id, "delinquencyDays", warnings);

        validateAndFormatDate(acct.getOriginationDate(), id, "originationDate", warnings);
        validateAndFormatDate(acct.getMaturityDate(), id, "maturityDate", warnings);
        validateAndFormatDate(acct.getFirstPaymentDate(), id, "firstPaymentDate", warnings);
        validateAndFormatDate(acct.getNextPaymentDate(), id, "nextPaymentDate", warnings);

        validateStatusCode(acct.getStatusCode(), VALID_LOAN_STATUS_CODES,
                id, "statusCode", warnings);
        if (acct.getPropertyType() != null) {
            validateStatusCode(acct.getPropertyType(), VALID_PROPERTY_TYPE_CODES,
                    id, "propertyType", warnings);
        }

        return warnings;
    }

    // --- Payment-level validation ---

    public List<DataQualityWarning> validatePayment(LegacyPayment pmt) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (pmt.getLoanAccountNumber() == null || pmt.getLoanAccountNumber().isBlank()) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, id, "loanAccountNumber",
                    "Required field is null/blank", pmt.getLoanAccountNumber()));
        }

        BigDecimal total = parseAmount(pmt.getTotalAmount(), id, "totalAmount", warnings);
        BigDecimal principal = parseAmount(pmt.getPrincipalAmount(), id, "principalAmount", warnings);
        BigDecimal interest = parseAmount(pmt.getInterestAmount(), id, "interestAmount", warnings);
        BigDecimal escrow = parseAmount(pmt.getEscrowAmount(), id, "escrowAmount", warnings);
        BigDecimal lateFee = parseAmount(pmt.getLateFee(), id, "lateFee", warnings);

        validatePaymentComponents(id, total, principal, interest, escrow, lateFee, warnings);

        validateAndFormatDate(pmt.getPaymentDate(), id, "paymentDate", warnings);
        validateAndFormatDate(pmt.getReceivedDate(), id, "receivedDate", warnings);
        validateAndFormatDate(pmt.getProcessedDate(), id, "processedDate", warnings);

        validateStatusCode(pmt.getTypeCode(), VALID_PAYMENT_TYPE_CODES,
                id, "typeCode", warnings);
        validateStatusCode(pmt.getStatusCode(), VALID_PAYMENT_STATUS_CODES,
                id, "statusCode", warnings);

        validateLateFeeConsistency(pmt, warnings);

        return warnings;
    }

    // --- Referential integrity checks ---

    public void validateBorrowerExists(String borrowerId, boolean exists,
                                       String loanAccountNumber,
                                       List<DataQualityWarning> warnings) {
        if (borrowerId != null && !exists) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, loanAccountNumber, "borrowerId",
                    "Orphaned record: borrower ID not found in CDW_BORR_MSTR",
                    borrowerId));
        }
    }

    public void validateProductExists(String productCode, boolean exists,
                                      String loanAccountNumber,
                                      List<DataQualityWarning> warnings) {
        if (productCode != null && !exists) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, loanAccountNumber, "productCode",
                    "Orphaned record: product code not found in CDW_LN_PROD",
                    productCode));
        }
    }

    public void validateLoanAccountExists(String loanAccountNumber, boolean exists,
                                          String paymentId,
                                          List<DataQualityWarning> warnings) {
        if (loanAccountNumber != null && !exists) {
            warnings.add(new DataQualityWarning(
                    Severity.HIGH, paymentId, "loanAccountNumber",
                    "Orphaned record: loan account not found in CDW_LN_ACCT",
                    loanAccountNumber));
        }
    }

    private BigDecimal parseAmountQuiet(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(amount.replace(",", ""));
        } catch (NumberFormatException e) {
            return BigDecimal.ZERO;
        }
    }
}
