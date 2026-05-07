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
import java.util.regex.Pattern;

@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final Pattern NUMERIC_WITH_COMMAS = Pattern.compile("^-?\\d{1,3}(,\\d{3})*(\\.\\d+)?$");
    private static final Pattern PLAIN_DECIMAL = Pattern.compile("^-?\\d+(\\.\\d+)?$");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.02");

    public BigDecimal safeParseLegacyAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        String sanitized = sanitizeNumericString(amount);
        try {
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            log.warn("Unparseable amount in {} for record {}: '{}' (sanitized: '{}')",
                    fieldName, recordId, amount, sanitized);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal safeParseLegacyDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        String trimmed = value.trim();
        try {
            return new BigDecimal(trimmed);
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal in {} for record {}: '{}'", fieldName, recordId, value);
            return BigDecimal.ZERO;
        }
    }

    public Integer safeParseLegacyInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String trimmed = value.trim();
        try {
            return Integer.parseInt(trimmed);
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer in {} for record {}: '{}'", fieldName, recordId, value);
            return null;
        }
    }

    public String safeParseLegacyDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate parsed = LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return parsed.toString();
        } catch (DateTimeParseException e) {
            log.warn("Unparseable date in {} for record {}: '{}'", fieldName, recordId, dateStr);
            return dateStr;
        }
    }

    public String safeJoinName(String firstName, String lastName, String recordId) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName.trim() : "Unknown";
        String last = (lastName != null && !lastName.isBlank()) ? lastName.trim() : "Unknown";
        if ("Unknown".equals(first) || "Unknown".equals(last)) {
            log.warn("Missing name component for record {}: first='{}', last='{}'",
                    recordId, firstName, lastName);
        }
        return first + " " + last;
    }

    public String safeJoinFullName(String firstName, String middleInitial, String lastName, String recordId) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName.trim() : "Unknown";
        String last = (lastName != null && !lastName.isBlank()) ? lastName.trim() : "Unknown";
        if ("Unknown".equals(first) || "Unknown".equals(last)) {
            log.warn("Missing name component for record {}: first='{}', last='{}'",
                    recordId, firstName, lastName);
        }
        String middle = (middleInitial != null && !middleInitial.isBlank())
                ? " " + middleInitial.trim() + "."
                : "";
        return first + middle + " " + last;
    }

    public String safeJoinAddress(String address, String city, String state, String zip, String recordId) {
        String addr = (address != null && !address.isBlank()) ? address.trim() : "Unknown Address";
        String c = (city != null && !city.isBlank()) ? city.trim() : "Unknown";
        String s = (state != null && !state.isBlank()) ? state.trim() : "??";
        String z = (zip != null && !zip.isBlank()) ? zip.trim() : "00000";
        return addr + ", " + c + ", " + s + " " + z;
    }

    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (isBlank(borrower.getFirstName())) {
            warnings.add("Borrower " + id + ": missing first name");
        }
        if (isBlank(borrower.getLastName())) {
            warnings.add("Borrower " + id + ": missing last name");
        }
        if (isBlank(borrower.getSsnEncrypted())) {
            warnings.add("Borrower " + id + ": missing SSN");
        }
        if (isBlank(borrower.getEmail())) {
            warnings.add("Borrower " + id + ": missing email");
        }
        if (!isBlank(borrower.getCreditScore())) {
            Integer score = safeParseLegacyInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", id);
            if (score != null && (score < 300 || score > 850)) {
                warnings.add("Borrower " + id + ": credit score out of range: " + score);
            }
        }
        if (!isBlank(borrower.getDateOfBirth())) {
            validateDateFormat(borrower.getDateOfBirth(), "BORR_DOB_DT", id, warnings);
        }
        if (!isBlank(borrower.getCreatedDate())) {
            validateDateFormat(borrower.getCreatedDate(), "BORR_CRET_DT", id, warnings);
        }
        if (!isBlank(borrower.getStatusCode()) && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            warnings.add("Borrower " + id + ": unrecognized status code: " + borrower.getStatusCode());
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    public List<String> validateLoanAccount(LegacyLoanAccount acct, Set<String> validBorrowerIds,
                                            Set<String> validProductCodes) {
        List<String> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (!isBlank(acct.getBorrowerId()) && !validBorrowerIds.contains(acct.getBorrowerId())) {
            warnings.add("Loan " + id + ": orphaned borrower reference: " + acct.getBorrowerId());
        }
        if (!isBlank(acct.getProductCode()) && !validProductCodes.contains(acct.getProductCode())) {
            warnings.add("Loan " + id + ": orphaned product reference: " + acct.getProductCode());
        }
        if (!isBlank(acct.getStatusCode()) && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            warnings.add("Loan " + id + ": unrecognized status code: " + acct.getStatusCode());
        }
        if (!isBlank(acct.getPropertyType()) && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            warnings.add("Loan " + id + ": unrecognized property type: " + acct.getPropertyType());
        }

        Integer dlqDays = safeParseLegacyInteger(acct.getDelinquencyDays(), "LN_DLQ_DAYS", id);
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            warnings.add("Loan " + id + ": delinquent (" + dlqDays + " days) but status is ACT");
        }

        if (isBlank(acct.getBorrowerFirstName()) || isBlank(acct.getBorrowerLastName())) {
            warnings.add("Loan " + id + ": missing denormalized borrower name");
        }

        if (!isBlank(acct.getOriginationDate())) {
            validateDateFormat(acct.getOriginationDate(), "LN_ORIG_DT", id, warnings);
        }
        if (!isBlank(acct.getMaturityDate())) {
            validateDateFormat(acct.getMaturityDate(), "LN_MAT_DT", id, warnings);
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    public List<String> validatePayment(LegacyPayment pmt, Set<String> validLoanAccountNumbers) {
        List<String> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (!isBlank(pmt.getLoanAccountNumber()) && !validLoanAccountNumbers.contains(pmt.getLoanAccountNumber())) {
            warnings.add("Payment " + id + ": orphaned loan reference: " + pmt.getLoanAccountNumber());
        }
        if (!isBlank(pmt.getStatusCode()) && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            warnings.add("Payment " + id + ": unrecognized status code: " + pmt.getStatusCode());
        }
        if (!isBlank(pmt.getTypeCode()) && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            warnings.add("Payment " + id + ": unrecognized type code: " + pmt.getTypeCode());
        }

        BigDecimal total = safeParseLegacyAmount(pmt.getTotalAmount(), "PMT_AMT", id);
        BigDecimal principal = safeParseLegacyAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id);
        BigDecimal interest = safeParseLegacyAmount(pmt.getInterestAmount(), "PMT_INT_AMT", id);
        BigDecimal escrow = safeParseLegacyAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id);
        BigDecimal lateFee = safeParseLegacyAmount(pmt.getLateFee(), "PMT_LATE_FEE", id);

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal delta = componentSum.subtract(total).abs();
        if (delta.compareTo(PAYMENT_TOLERANCE) > 0) {
            warnings.add("Payment " + id + ": component sum (" + componentSum.setScale(2, RoundingMode.HALF_UP)
                    + ") != total (" + total.setScale(2, RoundingMode.HALF_UP) + "), delta=" + delta.setScale(2, RoundingMode.HALF_UP));
        }

        if (!isBlank(pmt.getPaymentDate())) {
            validateDateFormat(pmt.getPaymentDate(), "PMT_DT", id, warnings);
        }
        if (!isBlank(pmt.getReceivedDate())) {
            validateDateFormat(pmt.getReceivedDate(), "PMT_RECV_DT", id, warnings);
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    private void validateDateFormat(String dateStr, String fieldName, String recordId, List<String> warnings) {
        try {
            LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            warnings.add("Record " + recordId + ": invalid date in " + fieldName + ": " + dateStr);
        }
    }

    private String sanitizeNumericString(String value) {
        String trimmed = value.trim();
        trimmed = trimmed.replace("$", "").replace("(", "-").replace(")", "");
        trimmed = trimmed.replace(",", "");
        return trimmed;
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
