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
import java.time.format.ResolverStyle;
import java.util.Set;

/**
 * Validates legacy CDW records at ingestion time, detecting known
 * data-quality anomalies before they reach the translation layer.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FMT =
            DateTimeFormatter.ofPattern("MM/dd/uuuu")
                    .withResolverStyle(ResolverStyle.STRICT);

    private static final Set<String> VALID_LOAN_STATUSES =
            Set.of("ACT", "CLO", "DFT", "FRB");

    private static final Set<String> VALID_PAYMENT_STATUSES =
            Set.of("PST", "REV", "NSF", "PND");

    private static final Set<String> VALID_PAYMENT_TYPES =
            Set.of("REG", "EXT", "PRT", "PRE");

    private static final Set<String> VALID_PROPERTY_TYPES =
            Set.of("SFR", "CND", "MFR", "TWN");

    private static final Set<String> VALID_BORROWER_STATUSES =
            Set.of("ACT", "INA");

    // --- Borrower validation ---

    public ValidationResult validateBorrower(LegacyBorrower b) {
        ValidationResult result = new ValidationResult();

        requireNonBlank(result, "BORR_ID", b.getBorrowerId());
        requireNonBlank(result, "BORR_FST_NM", b.getFirstName());
        requireNonBlank(result, "BORR_LST_NM", b.getLastName());

        validateDate(result, "BORR_DOB_DT", b.getDateOfBirth(), true);
        validateDate(result, "BORR_CRET_DT", b.getCreatedDate(), true);
        validateDate(result, "BORR_UPDT_DT", b.getUpdatedDate(), false);

        validateInteger(result, "BORR_CRDT_SCR", b.getCreditScore(), 300, 850);
        validateAmount(result, "BORR_ANN_INCM", b.getAnnualIncome(), false);

        if (b.getStatusCode() != null && !VALID_BORROWER_STATUSES.contains(b.getStatusCode())) {
            result.addWarning("BORR_STAT_CD",
                    "Unknown borrower status code: '" + b.getStatusCode() + "'");
        }

        if (!result.isClean()) {
            log.warn("Borrower {} has {} validation issue(s): {}",
                    b.getBorrowerId(), result.getIssues().size(), summarize(result));
        }
        return result;
    }

    // --- Loan account validation ---

    public ValidationResult validateLoanAccount(LegacyLoanAccount acct,
                                                 LegacyBorrower borrower) {
        ValidationResult result = new ValidationResult();

        requireNonBlank(result, "LN_ACCT_NBR", acct.getLoanAccountNumber());
        requireNonBlank(result, "BORR_ID", acct.getBorrowerId());

        // ANO-001: SSN last-4 vs phone last-4 cross-check
        if (borrower != null && acct.getBorrowerSsnLast4() != null
                && borrower.getPhoneNumber() != null) {
            String phoneLast4 = borrower.getPhoneNumber()
                    .replaceAll("[^0-9]", "");
            if (phoneLast4.length() >= 4) {
                phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
                if (phoneLast4.equals(acct.getBorrowerSsnLast4())) {
                    result.addError("BORR_SSN_LST4",
                            "SSN last-4 '" + acct.getBorrowerSsnLast4()
                                    + "' matches phone last-4 — likely column mapping error");
                }
            }
        }

        // ANO-005: denormalized name drift
        if (borrower != null) {
            if (acct.getBorrowerFirstName() != null
                    && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
                result.addWarning("BORR_FST_NM",
                        "Denormalized first name '" + acct.getBorrowerFirstName()
                                + "' differs from master '" + borrower.getFirstName() + "'");
            }
            if (acct.getBorrowerLastName() != null
                    && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
                result.addWarning("BORR_LST_NM",
                        "Denormalized last name '" + acct.getBorrowerLastName()
                                + "' differs from master '" + borrower.getLastName() + "'");
            }
        }

        // Financial field validation
        validateAmount(result, "LN_ORIG_AMT", acct.getOriginalAmount(), true);
        validateAmount(result, "LN_CURR_BAL", acct.getCurrentBalance(), true);
        validateAmount(result, "LN_PMT_AMT", acct.getMonthlyPayment(), true);
        validateAmount(result, "LN_ESCROW_BAL", acct.getEscrowBalance(), false);
        validateAmount(result, "PROP_APRS_VAL", acct.getAppraisedValue(), false);
        validateDecimal(result, "LN_INT_RT", acct.getInterestRate(), true);
        validateDecimal(result, "LN_LTV_PCT", acct.getLtvPercent(), false);

        // Date validation
        validateDate(result, "LN_ORIG_DT", acct.getOriginationDate(), true);
        validateDate(result, "LN_MAT_DT", acct.getMaturityDate(), true);
        validateDate(result, "LN_1ST_PMT_DT", acct.getFirstPaymentDate(), false);
        validateDate(result, "LN_NXT_PMT_DT", acct.getNextPaymentDate(), false);

        // Status code validation
        if (acct.getStatusCode() != null && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            result.addWarning("LN_STAT_CD",
                    "Unknown loan status code: '" + acct.getStatusCode() + "'");
        }
        if (acct.getPropertyType() != null && !VALID_PROPERTY_TYPES.contains(acct.getPropertyType())) {
            result.addWarning("PROP_TYP_CD",
                    "Unknown property type code: '" + acct.getPropertyType() + "'");
        }

        // ANO-007: LTV computation cross-check
        validateLtvConsistency(result, acct);

        if (!result.isClean()) {
            log.warn("Loan account {} has {} validation issue(s): {}",
                    acct.getLoanAccountNumber(), result.getIssues().size(), summarize(result));
        }
        return result;
    }

    // --- Payment validation ---

    public ValidationResult validatePayment(LegacyPayment pmt) {
        ValidationResult result = new ValidationResult();

        requireNonBlank(result, "PMT_SEQ_NBR", pmt.getPaymentSequenceNumber());
        requireNonBlank(result, "LN_ACCT_NBR", pmt.getLoanAccountNumber());

        validateAmount(result, "PMT_AMT", pmt.getTotalAmount(), true);
        validateAmount(result, "PMT_PRIN_AMT", pmt.getPrincipalAmount(), false);
        validateAmount(result, "PMT_INT_AMT", pmt.getInterestAmount(), false);
        validateAmount(result, "PMT_ESCROW_AMT", pmt.getEscrowAmount(), false);
        validateAmount(result, "PMT_LATE_FEE", pmt.getLateFee(), false);

        validateDate(result, "PMT_DT", pmt.getPaymentDate(), true);
        validateDate(result, "PMT_RECV_DT", pmt.getReceivedDate(), false);
        validateDate(result, "PMT_PROC_DT", pmt.getProcessedDate(), false);

        if (pmt.getStatusCode() != null && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            result.addWarning("PMT_STAT_CD",
                    "Unknown payment status code: '" + pmt.getStatusCode() + "'");
        }
        if (pmt.getTypeCode() != null && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            result.addWarning("PMT_TYP_CD",
                    "Unknown payment type code: '" + pmt.getTypeCode() + "'");
        }

        // ANO-002: payment component sum cross-check
        validatePaymentComponentSum(result, pmt);

        if (!result.isClean()) {
            log.warn("Payment {} has {} validation issue(s): {}",
                    pmt.getPaymentSequenceNumber(), result.getIssues().size(), summarize(result));
        }
        return result;
    }

    // =========================================================================
    // Field-level validation helpers
    // =========================================================================

    private void requireNonBlank(ValidationResult result, String field, String value) {
        if (value == null || value.isBlank()) {
            result.addError(field, "Required field is null or blank");
        }
    }

    void validateDate(ValidationResult result, String field,
                              String value, boolean required) {
        if (value == null || value.isBlank()) {
            if (required) {
                result.addError(field, "Required date field is null or blank");
            }
            return;
        }
        try {
            LocalDate.parse(value, LEGACY_DATE_FMT);
        } catch (DateTimeParseException e) {
            result.addError(field,
                    "Invalid date format '" + value + "' — expected MM/DD/YYYY");
        }
    }

    void validateAmount(ValidationResult result, String field,
                                String value, boolean required) {
        if (value == null || value.isBlank()) {
            if (required) {
                result.addError(field, "Required amount field is null or blank");
            }
            return;
        }
        try {
            String cleaned = value.replace(",", "").trim();
            if (cleaned.startsWith("$")) {
                cleaned = cleaned.substring(1);
            }
            new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            result.addError(field,
                    "Cannot parse amount '" + value + "' as a number");
        }
    }

    private void validateDecimal(ValidationResult result, String field,
                                 String value, boolean required) {
        if (value == null || value.isBlank()) {
            if (required) {
                result.addError(field, "Required decimal field is null or blank");
            }
            return;
        }
        try {
            new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            result.addError(field,
                    "Cannot parse decimal '" + value + "' as a number");
        }
    }

    private void validateInteger(ValidationResult result, String field,
                                 String value, int min, int max) {
        if (value == null || value.isBlank()) {
            result.addWarning(field, "Integer field is null or blank");
            return;
        }
        try {
            int parsed = Integer.parseInt(value.trim());
            if (parsed < min || parsed > max) {
                result.addWarning(field,
                        "Value " + parsed + " is outside expected range [" + min + ", " + max + "]");
            }
        } catch (NumberFormatException e) {
            result.addError(field,
                    "Cannot parse '" + value + "' as an integer");
        }
    }

    // =========================================================================
    // Cross-field validation
    // =========================================================================

    private void validatePaymentComponentSum(ValidationResult result, LegacyPayment pmt) {
        BigDecimal total = safeParse(pmt.getTotalAmount());
        BigDecimal principal = safeParse(pmt.getPrincipalAmount());
        BigDecimal interest = safeParse(pmt.getInterestAmount());
        BigDecimal escrow = safeParse(pmt.getEscrowAmount());
        BigDecimal lateFee = safeParse(pmt.getLateFee());

        if (total == null || principal == null || interest == null) {
            return; // individual field errors already recorded
        }
        BigDecimal componentSum = principal
                .add(interest)
                .add(escrow != null ? escrow : BigDecimal.ZERO)
                .add(lateFee != null ? lateFee : BigDecimal.ZERO);

        if (total.compareTo(componentSum) != 0) {
            result.addError("PMT_AMT",
                    "Component sum (" + componentSum + ") does not match total ("
                            + total + "), difference = "
                            + componentSum.subtract(total));
        }
    }

    private void validateLtvConsistency(ValidationResult result, LegacyLoanAccount acct) {
        BigDecimal origAmount = safeParse(acct.getOriginalAmount());
        BigDecimal appraisedValue = safeParse(acct.getAppraisedValue());
        BigDecimal statedLtv = safeParseDecimal(acct.getLtvPercent());

        if (origAmount == null || appraisedValue == null || statedLtv == null
                || appraisedValue.compareTo(BigDecimal.ZERO) == 0) {
            return;
        }
        BigDecimal computedLtv = origAmount
                .multiply(new BigDecimal("100"))
                .divide(appraisedValue, 1, RoundingMode.HALF_UP);

        if (computedLtv.subtract(statedLtv).abs().compareTo(new BigDecimal("0.15")) > 0) {
            result.addWarning("LN_LTV_PCT",
                    "Stated LTV (" + statedLtv + "%) differs from computed ("
                            + computedLtv + "%)");
        }
    }

    // =========================================================================
    // Safe parsing (returns null on failure — used only in cross-field checks)
    // =========================================================================

    private BigDecimal safeParse(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return new BigDecimal(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private BigDecimal safeParseDecimal(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private String summarize(ValidationResult result) {
        StringBuilder sb = new StringBuilder();
        for (ValidationResult.Issue issue : result.getIssues()) {
            if (!sb.isEmpty()) sb.append("; ");
            sb.append("[").append(issue.severity()).append("] ")
                    .append(issue.field()).append(": ").append(issue.message());
        }
        return sb.toString();
    }
}
