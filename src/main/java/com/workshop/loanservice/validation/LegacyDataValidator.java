package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.DataQualityWarning.Severity;
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
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.01");
    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_BORROWER_STATUSES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    // --- Safe parsing methods with error handling ---

    public BigDecimal parseAmount(String value, String recordId, String fieldName, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String sanitized = value.replaceAll("[^\\d.\\-]", "");
            if (sanitized.isEmpty()) {
                warnings.add(new DataQualityWarning(recordId, fieldName,
                        "Non-numeric amount value: '" + value + "', defaulting to 0", Severity.HIGH));
                return BigDecimal.ZERO;
            }
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            warnings.add(new DataQualityWarning(recordId, fieldName,
                    "Unparseable amount: '" + value + "', defaulting to 0", Severity.HIGH));
            log.warn("Failed to parse amount for {}.{}: '{}'", recordId, fieldName, value);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal parseDecimal(String value, String recordId, String fieldName, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String sanitized = value.replaceAll("[^\\d.\\-]", "");
            if (sanitized.isEmpty()) {
                warnings.add(new DataQualityWarning(recordId, fieldName,
                        "Non-numeric decimal value: '" + value + "', defaulting to 0", Severity.HIGH));
                return BigDecimal.ZERO;
            }
            return new BigDecimal(sanitized);
        } catch (NumberFormatException e) {
            warnings.add(new DataQualityWarning(recordId, fieldName,
                    "Unparseable decimal: '" + value + "', defaulting to 0", Severity.HIGH));
            log.warn("Failed to parse decimal for {}.{}: '{}'", recordId, fieldName, value);
            return BigDecimal.ZERO;
        }
    }

    public Integer parseInteger(String value, String recordId, String fieldName, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            String sanitized = value.replaceAll("[^\\d\\-]", "");
            if (sanitized.isEmpty()) {
                warnings.add(new DataQualityWarning(recordId, fieldName,
                        "Non-numeric integer value: '" + value + "', defaulting to null", Severity.HIGH));
                return null;
            }
            return Integer.parseInt(sanitized);
        } catch (NumberFormatException e) {
            warnings.add(new DataQualityWarning(recordId, fieldName,
                    "Unparseable integer: '" + value + "', defaulting to null", Severity.HIGH));
            log.warn("Failed to parse integer for {}.{}: '{}'", recordId, fieldName, value);
            return null;
        }
    }

    public LocalDate parseDate(String value, String recordId, String fieldName, List<DataQualityWarning> warnings) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(value.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            warnings.add(new DataQualityWarning(recordId, fieldName,
                    "Unparseable date (expected MM/DD/YYYY): '" + value + "'", Severity.MEDIUM));
            log.warn("Failed to parse date for {}.{}: '{}'", recordId, fieldName, value);
            return null;
        }
    }

    public String formatDateToIso(String value, String recordId, String fieldName, List<DataQualityWarning> warnings) {
        LocalDate parsed = parseDate(value, recordId, fieldName, warnings);
        if (parsed == null) {
            return value;
        }
        return parsed.toString();
    }

    // --- Null-safe string helpers ---

    public String safeString(String value, String fallback) {
        return (value != null && !value.isBlank()) ? value.trim() : fallback;
    }

    public String buildAddress(String line1, String city, String state, String zip) {
        StringBuilder sb = new StringBuilder();
        if (line1 != null && !line1.isBlank()) {
            sb.append(line1.trim());
        }
        if (city != null && !city.isBlank()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(city.trim());
        }
        if (state != null && !state.isBlank()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(state.trim());
        }
        if (zip != null && !zip.isBlank()) {
            if (sb.length() > 0) sb.append(" ");
            sb.append(zip.trim());
        }
        return sb.length() > 0 ? sb.toString() : "Unknown";
    }

    public String buildFullName(String firstName, String lastName) {
        String first = safeString(firstName, "");
        String last = safeString(lastName, "");
        String name = (first + " " + last).trim();
        return name.isEmpty() ? "Unknown" : name;
    }

    // --- Business rule validations ---

    public List<DataQualityWarning> validateBorrower(LegacyBorrower borrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add(new DataQualityWarning(id, "BORR_FST_NM",
                    "Required field is null or blank", Severity.HIGH));
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add(new DataQualityWarning(id, "BORR_LST_NM",
                    "Required field is null or blank", Severity.HIGH));
        }
        if (borrower.getEmail() == null || borrower.getEmail().isBlank()) {
            warnings.add(new DataQualityWarning(id, "BORR_EMAIL_ADDR",
                    "Required field is null or blank", Severity.MEDIUM));
        }

        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            warnings.add(new DataQualityWarning(id, "BORR_STAT_CD",
                    "Unknown status code: '" + borrower.getStatusCode() + "'", Severity.MEDIUM));
        }

        parseDate(borrower.getDateOfBirth(), id, "BORR_DOB_DT", warnings);
        parseDate(borrower.getCreatedDate(), id, "BORR_CRET_DT", warnings);
        parseDate(borrower.getUpdatedDate(), id, "BORR_UPDT_DT", warnings);

        // Use temporary list to avoid duplicate warnings — creditScore is re-parsed in toBorrowerDto
        List<DataQualityWarning> tempWarnings = new ArrayList<>();
        Integer creditScore = parseInteger(borrower.getCreditScore(), id, "BORR_CRDT_SCR", tempWarnings);
        if (creditScore != null && (creditScore < 300 || creditScore > 850)) {
            warnings.add(new DataQualityWarning(id, "BORR_CRDT_SCR",
                    "Credit score " + creditScore + " outside valid range (300-850)", Severity.MEDIUM));
        }

        parseAmount(borrower.getAnnualIncome(), id, "BORR_ANN_INCM", warnings);

        logWarnings(warnings);
        return warnings;
    }

    public List<DataQualityWarning> validateLoanAccount(LegacyLoanAccount acct) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (acct.getBorrowerId() == null || acct.getBorrowerId().isBlank()) {
            warnings.add(new DataQualityWarning(id, "BORR_ID",
                    "Required foreign key is null or blank — potential orphaned record", Severity.CRITICAL));
        }
        if (acct.getProductCode() == null || acct.getProductCode().isBlank()) {
            warnings.add(new DataQualityWarning(id, "PROD_CD",
                    "Required product code is null or blank", Severity.HIGH));
        }

        if (acct.getStatusCode() != null && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            warnings.add(new DataQualityWarning(id, "LN_STAT_CD",
                    "Unknown loan status code: '" + acct.getStatusCode() + "'", Severity.HIGH));
        }

        if (acct.getPropertyType() != null && !acct.getPropertyType().isBlank()
                && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            warnings.add(new DataQualityWarning(id, "PROP_TYP_CD",
                    "Unknown property type code: '" + acct.getPropertyType() + "'", Severity.MEDIUM));
        }

        Integer dlqDays = parseInteger(acct.getDelinquencyDays(), id, "LN_DLQ_DAYS", warnings);
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            warnings.add(new DataQualityWarning(id, "LN_STAT_CD/LN_DLQ_DAYS",
                    "Status is ACT but delinquency days = " + dlqDays + " — status/delinquency mismatch",
                    Severity.HIGH));
        }

        if (acct.getBorrowerSsnLast4() != null && !acct.getBorrowerSsnLast4().isBlank()) {
            if (!acct.getBorrowerSsnLast4().matches("\\d{4}")) {
                warnings.add(new DataQualityWarning(id, "BORR_SSN_LST4",
                        "SSN last-4 is not a 4-digit value: '" + acct.getBorrowerSsnLast4() + "'", Severity.HIGH));
            }
        }

        // Fields re-parsed in toLoanSummary are omitted here to avoid duplicate warnings.
        // Validate fields NOT re-parsed in the DTO layer:
        parseAmount(acct.getEscrowBalance(), id, "LN_ESCROW_BAL", warnings);
        parseDecimal(acct.getLtvPercent(), id, "LN_LTV_PCT", warnings);
        parseAmount(acct.getAppraisedValue(), id, "PROP_APRS_VAL", warnings);

        parseDate(acct.getMaturityDate(), id, "LN_MAT_DT", warnings);
        parseDate(acct.getFirstPaymentDate(), id, "LN_1ST_PMT_DT", warnings);
        parseDate(acct.getNextPaymentDate(), id, "LN_NXT_PMT_DT", warnings);
        parseDate(acct.getCreatedDate(), id, "LN_CRET_DT", warnings);
        parseDate(acct.getUpdatedDate(), id, "LN_UPDT_DT", warnings);

        logWarnings(warnings);
        return warnings;
    }

    public List<DataQualityWarning> validatePayment(LegacyPayment pmt) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (pmt.getLoanAccountNumber() == null || pmt.getLoanAccountNumber().isBlank()) {
            warnings.add(new DataQualityWarning(id, "LN_ACCT_NBR",
                    "Required foreign key is null or blank — potential orphaned record", Severity.CRITICAL));
        }

        if (pmt.getTypeCode() != null && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            warnings.add(new DataQualityWarning(id, "PMT_TYP_CD",
                    "Unknown payment type code: '" + pmt.getTypeCode() + "'", Severity.HIGH));
        }
        if (pmt.getStatusCode() != null && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            warnings.add(new DataQualityWarning(id, "PMT_STAT_CD",
                    "Unknown payment status code: '" + pmt.getStatusCode() + "'", Severity.HIGH));
        }

        // Use temporary list for component sum validation — these fields are re-parsed in toPaymentDto
        List<DataQualityWarning> tempWarnings = new ArrayList<>();
        BigDecimal total = parseAmount(pmt.getTotalAmount(), id, "PMT_AMT", tempWarnings);
        BigDecimal principal = parseAmount(pmt.getPrincipalAmount(), id, "PMT_PRIN_AMT", tempWarnings);
        BigDecimal interest = parseAmount(pmt.getInterestAmount(), id, "PMT_INT_AMT", tempWarnings);
        BigDecimal escrow = parseAmount(pmt.getEscrowAmount(), id, "PMT_ESCROW_AMT", tempWarnings);
        BigDecimal lateFee = parseAmount(pmt.getLateFee(), id, "PMT_LATE_FEE", tempWarnings);

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        if (componentSum.subtract(total).abs().compareTo(PAYMENT_TOLERANCE) > 0) {
            warnings.add(new DataQualityWarning(id, "PMT_AMT",
                    "Payment components sum (" + componentSum + ") != total (" + total
                            + "), discrepancy: " + componentSum.subtract(total),
                    Severity.CRITICAL));
        }

        // Validate fields NOT re-parsed in the DTO layer:
        parseDate(pmt.getReceivedDate(), id, "PMT_RECV_DT", warnings);
        parseDate(pmt.getProcessedDate(), id, "PMT_PROC_DT", warnings);
        parseDate(pmt.getCreatedDate(), id, "PMT_CRET_DT", warnings);
        parseDate(pmt.getUpdatedDate(), id, "PMT_UPDT_DT", warnings);

        logWarnings(warnings);
        return warnings;
    }

    public String resolveEffectiveLoanStatus(String statusCode, String delinquencyDaysStr) {
        if (statusCode == null) return "Unknown";
        Integer dlqDays = null;
        try {
            if (delinquencyDaysStr != null && !delinquencyDaysStr.isBlank()) {
                dlqDays = Integer.parseInt(delinquencyDaysStr.replaceAll("[^\\d]", ""));
            }
        } catch (NumberFormatException ignored) {
            // fall through to raw status expansion
        }

        if ("ACT".equals(statusCode) && dlqDays != null && dlqDays > 0) {
            return "Active - Delinquent (" + dlqDays + " days)";
        }

        return switch (statusCode) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> statusCode;
        };
    }

    private void logWarnings(List<DataQualityWarning> warnings) {
        for (DataQualityWarning w : warnings) {
            switch (w.getSeverity()) {
                case CRITICAL -> log.error("DATA_QUALITY {}", w);
                case HIGH -> log.warn("DATA_QUALITY {}", w);
                case MEDIUM -> log.info("DATA_QUALITY {}", w);
                case LOW -> log.debug("DATA_QUALITY {}", w);
            }
        }
    }
}
