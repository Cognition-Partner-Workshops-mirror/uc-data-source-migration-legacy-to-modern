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
 * Validates and safely converts legacy CDW data at ingestion time.
 * Catches anomalies documented in docs/DATA_ANOMALY_REPORT.md:
 * - Numeric strings that fail to parse (ANM-003)
 * - Invalid/unparseable date strings (ANM-004)
 * - Null values in required fields (ANM-006)
 * - Payment component sum mismatches (ANM-001)
 * - Status/delinquency inconsistencies (ANM-002)
 * - Invalid status codes
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final BigDecimal PAYMENT_SUM_TOLERANCE = new BigDecimal("0.02");
    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");

    /**
     * Safely parse a legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal.
     * Strips commas, dollar signs, and whitespace. Returns fallback on failure.
     */
    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount field '{}' value '{}' for record '{}': {}",
                    fieldName, amount, recordId, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy decimal string (e.g., "5.250") to BigDecimal.
     */
    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal field '{}' value '{}' for record '{}': {}",
                    fieldName, value, recordId, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy integer string (e.g., "745") to Integer.
     * Returns fallback on failure instead of throwing NumberFormatException.
     */
    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer field '{}' value '{}' for record '{}': {}",
                    fieldName, value, recordId, e.getMessage());
            return null;
        }
    }

    /**
     * Parse a legacy date string in MM/DD/YYYY format to LocalDate.
     * Returns null on failure instead of throwing DateTimeParseException.
     */
    public LocalDate parseDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date field '{}' value '{}' for record '{}': {}",
                    fieldName, dateStr, recordId, e.getMessage());
            return null;
        }
    }

    /**
     * Format a LocalDate as ISO-8601 string (yyyy-MM-dd), or return the original
     * raw string if parsing failed.
     */
    public String formatDateToIso(String legacyDateStr, String fieldName, String recordId) {
        LocalDate parsed = parseDate(legacyDateStr, fieldName, recordId);
        if (parsed != null) {
            return parsed.toString();
        }
        return legacyDateStr;
    }

    /**
     * Validate a borrower record for required fields.
     * Returns a list of warning messages (empty if valid).
     */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add("Borrower " + id + ": missing first name");
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add("Borrower " + id + ": missing last name");
        }
        if (borrower.getStatusCode() == null || borrower.getStatusCode().isBlank()) {
            warnings.add("Borrower " + id + ": missing status code");
        }

        Integer creditScore = parseInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", id);
        if (creditScore != null && (creditScore < 300 || creditScore > 850)) {
            warnings.add("Borrower " + id + ": credit score " + creditScore + " outside valid range [300-850]");
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    /**
     * Validate a loan account for status/delinquency consistency and required fields.
     * Returns a list of warning messages (empty if valid).
     */
    public List<String> validateLoanAccount(LegacyLoanAccount acct) {
        List<String> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        if (acct.getBorrowerId() == null || acct.getBorrowerId().isBlank()) {
            warnings.add("Loan " + id + ": missing borrower ID");
        }
        if (acct.getStatusCode() == null || acct.getStatusCode().isBlank()) {
            warnings.add("Loan " + id + ": missing status code");
        } else if (!VALID_LOAN_STATUS_CODES.contains(acct.getStatusCode())) {
            warnings.add("Loan " + id + ": unrecognized status code '" + acct.getStatusCode() + "'");
        }
        if (acct.getPropertyType() != null && !acct.getPropertyType().isBlank()
                && !VALID_PROPERTY_TYPE_CODES.contains(acct.getPropertyType())) {
            warnings.add("Loan " + id + ": unrecognized property type code '" + acct.getPropertyType() + "'");
        }

        Integer dlqDays = parseInteger(acct.getDelinquencyDays(), "LN_DLQ_DAYS", id);
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            warnings.add("Loan " + id + ": has " + dlqDays
                    + " delinquency days but status is ACT (Active) — possible status/delinquency mismatch");
        }

        if (acct.getBorrowerFirstName() == null || acct.getBorrowerLastName() == null) {
            warnings.add("Loan " + id + ": denormalized borrower name fields contain null values");
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    /**
     * Validate a payment record for component sum consistency and valid codes.
     * Returns a list of warning messages (empty if valid).
     */
    public List<String> validatePayment(LegacyPayment pmt) {
        List<String> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        if (pmt.getStatusCode() == null || pmt.getStatusCode().isBlank()) {
            warnings.add("Payment " + id + ": missing status code");
        } else if (!VALID_PAYMENT_STATUS_CODES.contains(pmt.getStatusCode())) {
            warnings.add("Payment " + id + ": unrecognized status code '" + pmt.getStatusCode() + "'");
        }

        if (pmt.getTypeCode() == null || pmt.getTypeCode().isBlank()) {
            warnings.add("Payment " + id + ": missing type code");
        } else if (!VALID_PAYMENT_TYPE_CODES.contains(pmt.getTypeCode())) {
            warnings.add("Payment " + id + ": unrecognized type code '" + pmt.getTypeCode() + "'");
        }

        BigDecimal total = parseAmount(pmt.getTotalAmount(), "PMT_AMT", id);
        BigDecimal principal = parseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id);
        BigDecimal interest = parseAmount(pmt.getInterestAmount(), "PMT_INT_AMT", id);
        BigDecimal escrow = parseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id);
        BigDecimal lateFee = parseAmount(pmt.getLateFee(), "PMT_LATE_FEE", id);

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal difference = componentSum.subtract(total).abs();
        if (difference.compareTo(PAYMENT_SUM_TOLERANCE) > 0) {
            warnings.add("Payment " + id + ": component sum (" + componentSum.setScale(2, RoundingMode.HALF_UP)
                    + ") does not match total (" + total.setScale(2, RoundingMode.HALF_UP)
                    + "), difference: " + difference.setScale(2, RoundingMode.HALF_UP));
        }

        for (String warning : warnings) {
            log.warn(warning);
        }
        return warnings;
    }

    /**
     * Build a safe borrower display name, handling null first/last names.
     */
    public String safeBorrowerName(String firstName, String lastName) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName : "Unknown";
        String last = (lastName != null && !lastName.isBlank()) ? lastName : "Unknown";
        return first + " " + last;
    }

    /**
     * Build a safe full name with optional middle initial.
     */
    public String safeFullName(String firstName, String middleInitial, String lastName) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName : "Unknown";
        String last = (lastName != null && !lastName.isBlank()) ? lastName : "Unknown";
        String middle = (middleInitial != null && !middleInitial.isBlank()) ? " " + middleInitial + "." : "";
        return first + middle + " " + last;
    }
}
