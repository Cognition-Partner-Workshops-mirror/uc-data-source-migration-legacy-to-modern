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
 * Validates and sanitizes legacy CDW data at ingestion time.
 *
 * Catches anomalies identified in DATA_ANOMALY_REPORT.md:
 *   - Null values in required fields (ANO-004)
 *   - Malformed numeric strings that would cause NumberFormatException (ANO-002)
 *   - Invalid date formats (ANO-007)
 *   - Payment component sum mismatches (ANO-001)
 *   - Delinquent loans with inconsistent status codes (ANO-003)
 *   - Credit score range violations (ANO-009)
 *   - Orphaned foreign key references (ANO-006)
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    /** Legacy date format used across all CDW tables */
    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    /** Valid FICO credit score range */
    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;

    /** Valid loan status codes from the legacy CDW system */
    private static final Set<String> VALID_LOAN_STATUS_CODES =
            Set.of("ACT", "CLO", "DFT", "FRB");

    /** Valid payment status codes */
    private static final Set<String> VALID_PAYMENT_STATUS_CODES =
            Set.of("PST", "REV", "NSF", "PND");

    /** Valid payment type codes */
    private static final Set<String> VALID_PAYMENT_TYPE_CODES =
            Set.of("REG", "EXT", "PRT", "PRE");

    /** Valid property type codes */
    private static final Set<String> VALID_PROPERTY_TYPE_CODES =
            Set.of("SFR", "CND", "MFR", "TWN");

    // =========================================================================
    // AMOUNT PARSING — safe coercion with error handling (fixes ANO-002)
    // =========================================================================

    /**
     * Safely parse a legacy amount string (e.g. "285,000" or "1,487.02") to BigDecimal.
     * Strips commas, currency symbols, and whitespace before parsing.
     * Returns BigDecimal.ZERO and logs a warning on parse failure instead of throwing.
     */
    public BigDecimal safeParseLegacyAmount(String amount, String recordId, String fieldName) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            // Strip currency symbols, commas, whitespace, and other non-numeric chars
            String cleaned = amount.replace(",", "")
                    .replace("$", "")
                    .replace(" ", "")
                    .trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("ANO-002: Failed to parse amount '{}' for record={}, field={}. " +
                    "Returning ZERO as fallback.", amount, recordId, fieldName);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy decimal string (e.g. "5.250" for interest rate) to BigDecimal.
     * Strips percent signs and whitespace before parsing.
     * Returns BigDecimal.ZERO and logs a warning on parse failure.
     */
    public BigDecimal safeParseLegacyDecimal(String value, String recordId, String fieldName) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            // Strip percent signs and whitespace
            String cleaned = value.replace("%", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("ANO-002: Failed to parse decimal '{}' for record={}, field={}. " +
                    "Returning ZERO as fallback.", value, recordId, fieldName);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parse a legacy integer string (e.g. "745" for credit score) to Integer.
     * Returns null and logs a warning on parse failure.
     */
    public Integer safeParseLegacyInteger(String value, String recordId, String fieldName) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("ANO-002: Failed to parse integer '{}' for record={}, field={}. " +
                    "Returning null as fallback.", value, recordId, fieldName);
            return null;
        }
    }

    // =========================================================================
    // DATE PARSING — validates MM/DD/YYYY format (fixes ANO-007)
    // =========================================================================

    /**
     * Parse a legacy date string in MM/DD/YYYY format to ISO-8601 (yyyy-MM-dd).
     * Returns the original string and logs a warning if the date is invalid.
     */
    public String safeParseLegacyDate(String dateStr, String recordId, String fieldName) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate parsed = LocalDate.parse(dateStr, LEGACY_DATE_FORMAT);
            // Return ISO-8601 format for API consistency
            return parsed.toString();
        } catch (DateTimeParseException e) {
            log.warn("ANO-007: Invalid date '{}' for record={}, field={}. " +
                    "Returning raw string as fallback.", dateStr, recordId, fieldName);
            return dateStr;
        }
    }

    // =========================================================================
    // BORROWER VALIDATION (fixes ANO-004, ANO-009)
    // =========================================================================

    /**
     * Validate a borrower record and return a list of anomaly warnings.
     * Checks required fields and credit score range.
     */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        // ANO-004: Required field null checks
        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add(String.format("ANO-004: Borrower %s has null/blank first name", id));
            log.warn("ANO-004: Borrower {} has null/blank BORR_FST_NM", id);
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add(String.format("ANO-004: Borrower %s has null/blank last name", id));
            log.warn("ANO-004: Borrower {} has null/blank BORR_LST_NM", id);
        }
        if (borrower.getSsnEncrypted() == null || borrower.getSsnEncrypted().isBlank()) {
            warnings.add(String.format("ANO-004: Borrower %s has null/blank SSN", id));
            log.warn("ANO-004: Borrower {} has null/blank BORR_SSN_ENCR", id);
        }

        // ANO-009: Credit score range validation
        Integer creditScore = safeParseLegacyInteger(
                borrower.getCreditScore(), id, "BORR_CRDT_SCR");
        if (creditScore != null && (creditScore < CREDIT_SCORE_MIN || creditScore > CREDIT_SCORE_MAX)) {
            warnings.add(String.format(
                    "ANO-009: Borrower %s has out-of-range credit score %d (valid: %d-%d)",
                    id, creditScore, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX));
            log.warn("ANO-009: Borrower {} has credit score {} outside valid range {}-{}",
                    id, creditScore, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX);
        }

        return warnings;
    }

    // =========================================================================
    // LOAN ACCOUNT VALIDATION (fixes ANO-003, ANO-006)
    // =========================================================================

    /**
     * Validate a loan account record and return a list of anomaly warnings.
     * Checks status/delinquency consistency, foreign key references, and status codes.
     */
    public List<String> validateLoanAccount(LegacyLoanAccount account,
                                            Set<String> validBorrowerIds,
                                            Set<String> validProductCodes) {
        List<String> warnings = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        // ANO-003: Delinquent loan with Active status
        Integer delinquencyDays = safeParseLegacyInteger(
                account.getDelinquencyDays(), id, "LN_DLQ_DAYS");
        if (delinquencyDays != null && delinquencyDays > 0
                && "ACT".equals(account.getStatusCode())) {
            warnings.add(String.format(
                    "ANO-003: Loan %s has %d delinquency days but status is ACT (Active). " +
                    "Expected DFT or FRB.", id, delinquencyDays));
            log.warn("ANO-003: Loan {} has {} delinquency days but status=ACT. " +
                    "Status/delinquency mismatch detected.", id, delinquencyDays);
        }

        // ANO-006: Orphaned borrower reference
        if (account.getBorrowerId() != null
                && !validBorrowerIds.contains(account.getBorrowerId())) {
            warnings.add(String.format(
                    "ANO-006: Loan %s references non-existent borrower %s",
                    id, account.getBorrowerId()));
            log.warn("ANO-006: Loan {} references orphan BORR_ID={}", id, account.getBorrowerId());
        }

        // ANO-006: Orphaned product reference
        if (account.getProductCode() != null
                && !validProductCodes.contains(account.getProductCode())) {
            warnings.add(String.format(
                    "ANO-006: Loan %s references non-existent product %s",
                    id, account.getProductCode()));
            log.warn("ANO-006: Loan {} references orphan PROD_CD={}", id, account.getProductCode());
        }

        // Validate status code is recognized
        if (account.getStatusCode() != null
                && !VALID_LOAN_STATUS_CODES.contains(account.getStatusCode())) {
            warnings.add(String.format(
                    "ANO-003: Loan %s has unrecognized status code '%s'",
                    id, account.getStatusCode()));
            log.warn("ANO-003: Loan {} has unrecognized LN_STAT_CD='{}'", id, account.getStatusCode());
        }

        // Validate property type code is recognized
        if (account.getPropertyType() != null
                && !VALID_PROPERTY_TYPE_CODES.contains(account.getPropertyType())) {
            warnings.add(String.format(
                    "Loan %s has unrecognized property type code '%s'",
                    id, account.getPropertyType()));
            log.warn("Loan {} has unrecognized PROP_TYP_CD='{}'", id, account.getPropertyType());
        }

        // ANO-004: Required field null checks for loan amounts
        if (account.getOriginalAmount() == null || account.getOriginalAmount().isBlank()) {
            warnings.add(String.format("ANO-004: Loan %s has null/blank original amount", id));
            log.warn("ANO-004: Loan {} has null/blank LN_ORIG_AMT", id);
        }
        if (account.getCurrentBalance() == null || account.getCurrentBalance().isBlank()) {
            warnings.add(String.format("ANO-004: Loan %s has null/blank current balance", id));
            log.warn("ANO-004: Loan {} has null/blank LN_CURR_BAL", id);
        }

        return warnings;
    }

    // =========================================================================
    // PAYMENT VALIDATION (fixes ANO-001, ANO-008)
    // =========================================================================

    /**
     * Validate a payment record and return a list of anomaly warnings.
     * Checks component sum integrity and late fee consistency.
     */
    public List<String> validatePayment(LegacyPayment payment, Set<String> validLoanAccountNumbers) {
        List<String> warnings = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        // ANO-001: Payment component sum mismatch
        BigDecimal total = safeParseLegacyAmount(payment.getTotalAmount(), id, "PMT_AMT");
        BigDecimal principal = safeParseLegacyAmount(payment.getPrincipalAmount(), id, "PMT_PRIN_AMT");
        BigDecimal interest = safeParseLegacyAmount(payment.getInterestAmount(), id, "PMT_INT_AMT");
        BigDecimal escrow = safeParseLegacyAmount(payment.getEscrowAmount(), id, "PMT_ESCROW_AMT");
        BigDecimal lateFee = safeParseLegacyAmount(payment.getLateFee(), id, "PMT_LATE_FEE");

        BigDecimal computedSum = principal.add(interest).add(escrow).add(lateFee);
        // Use scale of 2 for comparison to avoid precision issues
        BigDecimal difference = total.subtract(computedSum).setScale(2, RoundingMode.HALF_UP);
        if (difference.compareTo(BigDecimal.ZERO) != 0) {
            warnings.add(String.format(
                    "ANO-001: Payment %s total (%s) != component sum (%s). Difference: %s",
                    id, total, computedSum, difference));
            log.warn("ANO-001: Payment {} has PMT_AMT={} but component sum={}. Delta={}",
                    id, total, computedSum, difference);
        }

        // ANO-006: Orphaned loan account reference
        if (payment.getLoanAccountNumber() != null
                && !validLoanAccountNumbers.contains(payment.getLoanAccountNumber())) {
            warnings.add(String.format(
                    "ANO-006: Payment %s references non-existent loan account %s",
                    id, payment.getLoanAccountNumber()));
            log.warn("ANO-006: Payment {} references orphan LN_ACCT_NBR={}",
                    id, payment.getLoanAccountNumber());
        }

        // Validate payment status code
        if (payment.getStatusCode() != null
                && !VALID_PAYMENT_STATUS_CODES.contains(payment.getStatusCode())) {
            warnings.add(String.format(
                    "Payment %s has unrecognized status code '%s'",
                    id, payment.getStatusCode()));
            log.warn("Payment {} has unrecognized PMT_STAT_CD='{}'", id, payment.getStatusCode());
        }

        // Validate payment type code
        if (payment.getTypeCode() != null
                && !VALID_PAYMENT_TYPE_CODES.contains(payment.getTypeCode())) {
            warnings.add(String.format(
                    "Payment %s has unrecognized type code '%s'",
                    id, payment.getTypeCode()));
            log.warn("Payment {} has unrecognized PMT_TYP_CD='{}'", id, payment.getTypeCode());
        }

        // ANO-008: Late payment with inconsistent late fee
        LocalDate paymentDate = parseDateOrNull(payment.getPaymentDate());
        LocalDate receivedDate = parseDateOrNull(payment.getReceivedDate());
        if (paymentDate != null && receivedDate != null && receivedDate.isAfter(paymentDate)) {
            long daysLate = java.time.temporal.ChronoUnit.DAYS.between(paymentDate, receivedDate);
            boolean hasLateFee = lateFee.compareTo(BigDecimal.ZERO) > 0;
            // Flag if significantly late (>15 days) but no late fee assessed
            if (daysLate > 15 && !hasLateFee) {
                warnings.add(String.format(
                        "ANO-008: Payment %s received %d days late but has no late fee",
                        id, daysLate));
                log.warn("ANO-008: Payment {} received {} days late with no late fee",
                        id, daysLate);
            }
        }

        return warnings;
    }

    // =========================================================================
    // SAFE BORROWER NAME CONSTRUCTION (fixes ANO-004 null safety)
    // =========================================================================

    /**
     * Safely build a full name from borrower fields, handling null first/last names.
     * Returns "[MISSING]" placeholder for null required name fields.
     */
    public String safeBuildFullName(String firstName, String middleInitial, String lastName) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName : "[MISSING]";
        String last = (lastName != null && !lastName.isBlank()) ? lastName : "[MISSING]";
        String middle = (middleInitial != null && !middleInitial.isBlank())
                ? " " + middleInitial + "." : "";
        return first + middle + " " + last;
    }

    /**
     * Safely build a borrower display name from loan account denormalized fields.
     * Returns "[MISSING]" placeholder for null name fields.
     */
    public String safeBuildBorrowerName(String firstName, String lastName) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName : "[MISSING]";
        String last = (lastName != null && !lastName.isBlank()) ? lastName : "[MISSING]";
        return first + " " + last;
    }

    // =========================================================================
    // ENHANCED STATUS EXPANSION (fixes ANO-003 by including delinquency context)
    // =========================================================================

    /**
     * Expand a loan status code, cross-referencing delinquency days.
     * If the loan has delinquency days > 0 but status is ACT, appends a warning qualifier.
     */
    public String expandLoanStatusWithDelinquencyCheck(String statusCode, String delinquencyDaysStr,
                                                        String loanId) {
        String expandedStatus = expandStatusCode(statusCode);

        // ANO-003: Cross-field validation — flag inconsistent status/delinquency
        Integer delinquencyDays = safeParseLegacyInteger(delinquencyDaysStr, loanId, "LN_DLQ_DAYS");
        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(statusCode)) {
            log.warn("ANO-003: Loan {} reported as Active but has {} delinquency days. " +
                    "Appending delinquency qualifier.", loanId, delinquencyDays);
            return expandedStatus + " (Delinquent - " + delinquencyDays + " days)";
        }

        return expandedStatus;
    }

    /**
     * Standard status code expansion (ACT→Active, CLO→Closed, etc.)
     */
    public String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> code;
        };
    }

    /**
     * Expand property type codes to human-readable names.
     */
    public String expandPropertyType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "SFR" -> "Single Family Residence";
            case "CND" -> "Condominium";
            case "MFR" -> "Multi-Family Residence";
            case "TWN" -> "Townhouse";
            default -> code;
        };
    }

    /**
     * Expand payment type codes to human-readable names.
     */
    public String expandPaymentType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "REG" -> "Regular";
            case "EXT" -> "Extra";
            case "PRT" -> "Partial";
            case "PRE" -> "Prepayment";
            default -> code;
        };
    }

    /**
     * Expand payment status codes to human-readable names.
     */
    public String expandPaymentStatus(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "PST" -> "Posted";
            case "REV" -> "Reversed";
            case "NSF" -> "Non-Sufficient Funds";
            case "PND" -> "Pending";
            default -> code;
        };
    }

    // =========================================================================
    // INTERNAL HELPERS
    // =========================================================================

    /** Parse a legacy MM/DD/YYYY date string to LocalDate, returning null on failure. */
    private LocalDate parseDateOrNull(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        try {
            return LocalDate.parse(dateStr, LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            return null;
        }
    }
}
