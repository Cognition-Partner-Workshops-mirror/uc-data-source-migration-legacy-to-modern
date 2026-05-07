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

@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    public BigDecimal parseAmount(String amount, String fieldName, List<DataQualityWarning> warnings) {
        if (amount == null || amount.isBlank()) {
            warnings.add(DataQualityWarning.high(fieldName, "Missing value — null amount is not the same as $0.00"));
            return null;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            if (cleaned.startsWith("(") && cleaned.endsWith(")")) {
                cleaned = "-" + cleaned.substring(1, cleaned.length() - 1);
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            warnings.add(DataQualityWarning.critical(fieldName,
                    "Unparseable numeric value: '" + amount + "'"));
            log.warn("Failed to parse amount field '{}': '{}'", fieldName, amount);
            return null;
        }
    }

    public BigDecimal parseDecimal(String value, String fieldName, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            warnings.add(DataQualityWarning.high(fieldName, "Missing decimal value"));
            return null;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            warnings.add(DataQualityWarning.critical(fieldName,
                    "Unparseable decimal value: '" + value + "'"));
            log.warn("Failed to parse decimal field '{}': '{}'", fieldName, value);
            return null;
        }
    }

    public Integer parseInteger(String value, String fieldName, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            String cleaned = value.trim().replace(",", "");
            if (cleaned.contains(".")) {
                cleaned = cleaned.substring(0, cleaned.indexOf('.'));
            }
            return Integer.parseInt(cleaned);
        } catch (NumberFormatException e) {
            warnings.add(DataQualityWarning.critical(fieldName,
                    "Unparseable integer value: '" + value + "'"));
            log.warn("Failed to parse integer field '{}': '{}'", fieldName, value);
            return null;
        }
    }

    public String parseDate(String dateStr, String fieldName, List<DataQualityWarning> warnings) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate parsed = LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return parsed.toString();
        } catch (DateTimeParseException e) {
            warnings.add(DataQualityWarning.high(fieldName,
                    "Invalid date format (expected MM/DD/YYYY): '" + dateStr + "'"));
            log.warn("Failed to parse date field '{}': '{}'", fieldName, dateStr);
            return dateStr.trim();
        }
    }

    public String validateStatusCode(String code, Set<String> validCodes, String fieldName,
                                     List<DataQualityWarning> warnings) {
        if (code == null || code.isBlank()) {
            warnings.add(DataQualityWarning.high(fieldName, "Missing status code"));
            return null;
        }
        String trimmed = code.trim();
        if (!validCodes.contains(trimmed)) {
            warnings.add(DataQualityWarning.medium(fieldName,
                    "Unrecognized status code: '" + trimmed + "'"));
        }
        return trimmed;
    }

    public void validateRequiredString(String value, String fieldName, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            warnings.add(DataQualityWarning.critical(fieldName, "Required field is null or blank"));
        }
    }

    public List<DataQualityWarning> validateBorrower(LegacyBorrower borrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        validateRequiredString(borrower.getBorrowerId(), "borrowerId", warnings);
        validateRequiredString(borrower.getFirstName(), "firstName", warnings);
        validateRequiredString(borrower.getLastName(), "lastName", warnings);
        validateRequiredString(borrower.getEmail(), "email", warnings);

        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            Integer score = parseInteger(borrower.getCreditScore(), "creditScore", warnings);
            if (score != null && (score < 300 || score > 850)) {
                warnings.add(DataQualityWarning.medium("creditScore",
                        "Credit score out of valid range (300-850): " + score));
            }
        }

        if (borrower.getStatusCode() != null) {
            validateStatusCode(borrower.getStatusCode(), VALID_BORROWER_STATUSES,
                    "borrowerStatusCode", warnings);
        }

        return warnings;
    }

    public List<DataQualityWarning> validateLoanAccount(LegacyLoanAccount acct) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        validateRequiredString(acct.getLoanAccountNumber(), "loanAccountNumber", warnings);
        validateRequiredString(acct.getBorrowerId(), "borrowerId", warnings);
        validateRequiredString(acct.getProductCode(), "productCode", warnings);

        if (acct.getStatusCode() != null) {
            validateStatusCode(acct.getStatusCode(), VALID_LOAN_STATUSES,
                    "loanStatusCode", warnings);
        }

        if (acct.getPropertyType() != null) {
            validateStatusCode(acct.getPropertyType(), VALID_PROPERTY_TYPES,
                    "propertyType", warnings);
        }

        return warnings;
    }

    public List<DataQualityWarning> validatePayment(LegacyPayment pmt) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        validateRequiredString(pmt.getPaymentSequenceNumber(), "paymentSequenceNumber", warnings);
        validateRequiredString(pmt.getLoanAccountNumber(), "loanAccountNumber", warnings);

        if (pmt.getStatusCode() != null) {
            validateStatusCode(pmt.getStatusCode(), VALID_PAYMENT_STATUSES,
                    "paymentStatusCode", warnings);
        }

        if (pmt.getTypeCode() != null) {
            validateStatusCode(pmt.getTypeCode(), VALID_PAYMENT_TYPES,
                    "paymentTypeCode", warnings);
        }

        return warnings;
    }

    public List<DataQualityWarning> validatePaymentComponents(BigDecimal total,
                                                               BigDecimal principal,
                                                               BigDecimal interest,
                                                               BigDecimal escrow,
                                                               BigDecimal lateFee) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        if (total == null || principal == null || interest == null) {
            return warnings;
        }

        BigDecimal componentSum = principal.add(interest);
        if (escrow != null) {
            componentSum = componentSum.add(escrow);
        }
        if (lateFee != null) {
            componentSum = componentSum.add(lateFee);
        }

        if (total.compareTo(componentSum) != 0) {
            BigDecimal diff = componentSum.subtract(total).abs();
            warnings.add(DataQualityWarning.critical("paymentComponents",
                    "Component sum (" + componentSum + ") does not match total ("
                            + total + "). Discrepancy: " + diff));
        }

        return warnings;
    }

    public List<DataQualityWarning> validateDenormalizedBorrowerData(
            LegacyLoanAccount acct, LegacyBorrower masterBorrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        if (masterBorrower == null) {
            warnings.add(DataQualityWarning.critical("borrowerId",
                    "Orphaned loan — borrower '" + acct.getBorrowerId()
                            + "' not found in CDW_BORR_MSTR"));
            return warnings;
        }

        if (acct.getBorrowerFirstName() != null && masterBorrower.getFirstName() != null
                && !acct.getBorrowerFirstName().equals(masterBorrower.getFirstName())) {
            warnings.add(DataQualityWarning.high("borrowerFirstName",
                    "Denormalized name mismatch: loan has '"
                            + acct.getBorrowerFirstName() + "', master has '"
                            + masterBorrower.getFirstName() + "'"));
        }

        if (acct.getBorrowerLastName() != null && masterBorrower.getLastName() != null
                && !acct.getBorrowerLastName().equals(masterBorrower.getLastName())) {
            warnings.add(DataQualityWarning.high("borrowerLastName",
                    "Denormalized name mismatch: loan has '"
                            + acct.getBorrowerLastName() + "', master has '"
                            + masterBorrower.getLastName() + "'"));
        }

        return warnings;
    }

    public List<DataQualityWarning> validatePaymentDates(String paymentDate, String receivedDate,
                                                          String processedDate) {
        List<DataQualityWarning> warnings = new ArrayList<>();

        LocalDate recv = safeParseLegacyDate(receivedDate);
        LocalDate proc = safeParseLegacyDate(processedDate);

        if (recv != null && proc != null && recv.isAfter(proc)) {
            warnings.add(DataQualityWarning.medium("paymentDates",
                    "Received date (" + receivedDate + ") is after processed date ("
                            + processedDate + ")"));
        }

        return warnings;
    }

    private LocalDate safeParseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    public Set<String> getValidLoanStatuses() { return VALID_LOAN_STATUSES; }
    public Set<String> getValidPaymentStatuses() { return VALID_PAYMENT_STATUSES; }
    public Set<String> getValidPaymentTypes() { return VALID_PAYMENT_TYPES; }
    public Set<String> getValidBorrowerStatuses() { return VALID_BORROWER_STATUSES; }
    public Set<String> getValidPropertyTypes() { return VALID_PROPERTY_TYPES; }
}
