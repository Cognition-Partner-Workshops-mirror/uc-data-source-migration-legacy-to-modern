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

/**
 * Validates legacy CDW data at ingestion time, catching known anomaly patterns
 * (see docs/DATA_ANOMALY_REPORT.md). Each method returns a list of validation
 * warnings rather than throwing, so a single bad record does not crash the
 * entire request.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    // Expected date format in legacy CDW tables
    private static final DateTimeFormatter LEGACY_DATE_FMT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    // Valid status codes for loan accounts
    private static final Set<String> VALID_LOAN_STATUSES =
            Set.of("ACT", "CLO", "DFT", "FRB");

    // Valid status codes for borrowers
    private static final Set<String> VALID_BORROWER_STATUSES =
            Set.of("ACT", "INA");

    // Valid payment type codes
    private static final Set<String> VALID_PAYMENT_TYPES =
            Set.of("REG", "EXT", "PRT", "PRE");

    // Valid payment status codes
    private static final Set<String> VALID_PAYMENT_STATUSES =
            Set.of("PST", "REV", "NSF", "PND");

    // -----------------------------------------------------------------
    // Borrower validation
    // -----------------------------------------------------------------

    /**
     * Validates a legacy borrower record for null required fields, unparseable
     * numeric/date strings, and invalid status codes.
     */
    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        // Required field null checks (ANO-004)
        if (isBlank(borrower.getFirstName())) {
            warnings.add(warn(id, "BORR_FST_NM is null/blank — required field"));
        }
        if (isBlank(borrower.getLastName())) {
            warnings.add(warn(id, "BORR_LST_NM is null/blank — required field"));
        }
        if (isBlank(borrower.getSsnEncrypted())) {
            warnings.add(warn(id, "BORR_SSN_ENCR is null/blank — required field"));
        }

        // Credit score parse check (ANO-004)
        if (!isBlank(borrower.getCreditScore())) {
            Integer score = safeParseInt(borrower.getCreditScore());
            if (score == null) {
                warnings.add(warn(id, "BORR_CRDT_SCR '" + borrower.getCreditScore()
                        + "' is not a valid integer"));
            } else if (score < 300 || score > 850) {
                warnings.add(warn(id, "BORR_CRDT_SCR " + score
                        + " is outside valid FICO range 300-850"));
            }
        }

        // Annual income parse check (ANO-004)
        if (!isBlank(borrower.getAnnualIncome())) {
            BigDecimal income = safeParseAmount(borrower.getAnnualIncome());
            if (income == null) {
                warnings.add(warn(id, "BORR_ANN_INCM '" + borrower.getAnnualIncome()
                        + "' is not a valid amount"));
            } else if (income.compareTo(BigDecimal.ZERO) < 0) {
                warnings.add(warn(id, "BORR_ANN_INCM is negative: " + income));
            }
        }

        // Date format checks (ANO-005)
        validateDate(borrower.getDateOfBirth(), "BORR_DOB_DT", id, warnings);
        validateDate(borrower.getCreatedDate(), "BORR_CRET_DT", id, warnings);
        validateDate(borrower.getUpdatedDate(), "BORR_UPDT_DT", id, warnings);

        // Status code validation
        if (!isBlank(borrower.getStatusCode())
                && !VALID_BORROWER_STATUSES.contains(borrower.getStatusCode())) {
            warnings.add(warn(id, "BORR_STAT_CD '" + borrower.getStatusCode()
                    + "' is not a recognized status code"));
        }

        // Log all warnings
        warnings.forEach(w -> log.warn("Borrower validation: {}", w));
        return warnings;
    }

    // -----------------------------------------------------------------
    // Loan account validation
    // -----------------------------------------------------------------

    /**
     * Validates a legacy loan account record for unparseable amounts, date
     * format issues, status/delinquency inconsistency (ANO-003), and
     * SSN-phone cross-contamination (ANO-002).
     */
    public List<String> validateLoanAccount(LegacyLoanAccount acct,
                                            LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        // Required field null checks
        if (isBlank(acct.getBorrowerId())) {
            warnings.add(warn(id, "BORR_ID is null/blank — required field"));
        }
        if (isBlank(acct.getProductCode())) {
            warnings.add(warn(id, "PROD_CD is null/blank — required field"));
        }

        // Numeric parsing checks (ANO-004)
        validateAmount(acct.getOriginalAmount(), "LN_ORIG_AMT", id, warnings);
        validateAmount(acct.getCurrentBalance(), "LN_CURR_BAL", id, warnings);
        validateAmount(acct.getMonthlyPayment(), "LN_PMT_AMT", id, warnings);
        validateAmount(acct.getEscrowBalance(), "LN_ESCROW_BAL", id, warnings);
        validateAmount(acct.getAppraisedValue(), "PROP_APRS_VAL", id, warnings);

        // Interest rate check
        if (!isBlank(acct.getInterestRate())) {
            BigDecimal rate = safeParseDecimal(acct.getInterestRate());
            if (rate == null) {
                warnings.add(warn(id, "LN_INT_RT '" + acct.getInterestRate()
                        + "' is not a valid decimal"));
            } else if (rate.compareTo(BigDecimal.ZERO) < 0
                    || rate.compareTo(new BigDecimal("30")) > 0) {
                warnings.add(warn(id, "LN_INT_RT " + rate
                        + " is outside plausible range 0-30%"));
            }
        }

        // Term months check
        if (!isBlank(acct.getTermMonths())) {
            Integer term = safeParseInt(acct.getTermMonths());
            if (term == null) {
                warnings.add(warn(id, "LN_TERM_MOS '" + acct.getTermMonths()
                        + "' is not a valid integer"));
            }
        }

        // Delinquency days check
        if (!isBlank(acct.getDelinquencyDays())) {
            Integer dlqDays = safeParseInt(acct.getDelinquencyDays());
            if (dlqDays == null) {
                warnings.add(warn(id, "LN_DLQ_DAYS '" + acct.getDelinquencyDays()
                        + "' is not a valid integer"));
            }
        }

        // LTV check
        if (!isBlank(acct.getLtvPercent())) {
            BigDecimal ltv = safeParseDecimal(acct.getLtvPercent());
            if (ltv == null) {
                warnings.add(warn(id, "LN_LTV_PCT '" + acct.getLtvPercent()
                        + "' is not a valid decimal"));
            } else if (ltv.compareTo(new BigDecimal("200")) > 0) {
                warnings.add(warn(id, "LN_LTV_PCT " + ltv + " exceeds 200% — suspicious"));
            }
        }

        // Date format checks (ANO-005)
        validateDate(acct.getOriginationDate(), "LN_ORIG_DT", id, warnings);
        validateDate(acct.getMaturityDate(), "LN_MAT_DT", id, warnings);
        validateDate(acct.getFirstPaymentDate(), "LN_1ST_PMT_DT", id, warnings);
        validateDate(acct.getNextPaymentDate(), "LN_NXT_PMT_DT", id, warnings);
        validateDate(acct.getCreatedDate(), "LN_CRET_DT", id, warnings);
        validateDate(acct.getUpdatedDate(), "LN_UPDT_DT", id, warnings);

        // Status code validation
        if (!isBlank(acct.getStatusCode())
                && !VALID_LOAN_STATUSES.contains(acct.getStatusCode())) {
            warnings.add(warn(id, "LN_STAT_CD '" + acct.getStatusCode()
                    + "' is not a recognized loan status code"));
        }

        // ANO-003: Delinquency vs. status consistency
        if (!isBlank(acct.getDelinquencyDays()) && !isBlank(acct.getStatusCode())) {
            Integer dlqDays = safeParseInt(acct.getDelinquencyDays());
            if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
                warnings.add(warn(id, "LN_DLQ_DAYS=" + dlqDays
                        + " but LN_STAT_CD='ACT' — delinquent loan shows as Active"));
            }
        }

        // ANO-002: SSN last-4 vs phone number cross-contamination
        if (borrower != null && !isBlank(acct.getBorrowerSsnLast4())
                && !isBlank(borrower.getPhoneNumber())) {
            String phoneLast4 = extractLast4Digits(borrower.getPhoneNumber());
            if (phoneLast4 != null
                    && phoneLast4.equals(acct.getBorrowerSsnLast4())) {
                warnings.add(warn(id,
                        "BORR_SSN_LST4 '" + acct.getBorrowerSsnLast4()
                                + "' matches phone last-4 '" + phoneLast4
                                + "' — possible data corruption (ANO-002)"));
            }
        }

        // ANO-007: Denormalized name drift check
        if (borrower != null) {
            if (!isBlank(acct.getBorrowerFirstName())
                    && !isBlank(borrower.getFirstName())
                    && !acct.getBorrowerFirstName().equals(borrower.getFirstName())) {
                warnings.add(warn(id,
                        "Denormalized BORR_FST_NM '" + acct.getBorrowerFirstName()
                                + "' differs from master '" + borrower.getFirstName() + "'"));
            }
            if (!isBlank(acct.getBorrowerLastName())
                    && !isBlank(borrower.getLastName())
                    && !acct.getBorrowerLastName().equals(borrower.getLastName())) {
                warnings.add(warn(id,
                        "Denormalized BORR_LST_NM '" + acct.getBorrowerLastName()
                                + "' differs from master '" + borrower.getLastName() + "'"));
            }
        }

        // Log all warnings
        warnings.forEach(w -> log.warn("LoanAccount validation: {}", w));
        return warnings;
    }

    // -----------------------------------------------------------------
    // Payment validation
    // -----------------------------------------------------------------

    /**
     * Validates a legacy payment record for unparseable amounts, date format
     * issues, component-sum mismatch (ANO-001), and invalid type/status codes.
     */
    public List<String> validatePayment(LegacyPayment pmt) {
        List<String> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        // Required field null checks
        if (isBlank(pmt.getLoanAccountNumber())) {
            warnings.add(warn(id, "LN_ACCT_NBR is null/blank — required field"));
        }

        // Numeric parsing checks (ANO-004)
        validateAmount(pmt.getTotalAmount(), "PMT_AMT", id, warnings);
        validateAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id, warnings);
        validateAmount(pmt.getInterestAmount(), "PMT_INT_AMT", id, warnings);
        validateAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id, warnings);
        validateAmount(pmt.getLateFee(), "PMT_LATE_FEE", id, warnings);

        // Date checks (ANO-005)
        validateDate(pmt.getPaymentDate(), "PMT_DT", id, warnings);
        validateDate(pmt.getReceivedDate(), "PMT_RECV_DT", id, warnings);
        validateDate(pmt.getProcessedDate(), "PMT_PROC_DT", id, warnings);
        validateDate(pmt.getCreatedDate(), "PMT_CRET_DT", id, warnings);
        validateDate(pmt.getUpdatedDate(), "PMT_UPDT_DT", id, warnings);

        // Type code validation
        if (!isBlank(pmt.getTypeCode())
                && !VALID_PAYMENT_TYPES.contains(pmt.getTypeCode())) {
            warnings.add(warn(id, "PMT_TYP_CD '" + pmt.getTypeCode()
                    + "' is not a recognized payment type"));
        }

        // Status code validation
        if (!isBlank(pmt.getStatusCode())
                && !VALID_PAYMENT_STATUSES.contains(pmt.getStatusCode())) {
            warnings.add(warn(id, "PMT_STAT_CD '" + pmt.getStatusCode()
                    + "' is not a recognized payment status"));
        }

        // ANO-001: Payment component sum mismatch
        BigDecimal total = safeParseAmount(pmt.getTotalAmount());
        BigDecimal principal = safeParseAmount(pmt.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(pmt.getInterestAmount());
        BigDecimal escrow = safeParseAmount(pmt.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(pmt.getLateFee());

        if (total != null && principal != null && interest != null
                && escrow != null && lateFee != null) {
            BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
            if (total.compareTo(componentSum) != 0) {
                warnings.add(warn(id,
                        "PMT_AMT " + total + " != component sum " + componentSum
                                + " (principal=" + principal + " + interest=" + interest
                                + " + escrow=" + escrow + " + lateFee=" + lateFee
                                + ") — discrepancy of "
                                + componentSum.subtract(total)));
            }
        }

        // Log all warnings
        warnings.forEach(w -> log.warn("Payment validation: {}", w));
        return warnings;
    }

    // -----------------------------------------------------------------
    // Safe parsing utilities — return null on failure instead of throwing
    // -----------------------------------------------------------------

    /**
     * Parses a legacy amount string (may contain commas) to BigDecimal.
     * Returns null if unparseable instead of throwing.
     */
    public BigDecimal safeParseAmount(String amount) {
        if (isBlank(amount)) return null;
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
            return null;
        }
    }

    /**
     * Parses a plain decimal string to BigDecimal.
     * Returns null if unparseable instead of throwing.
     */
    public BigDecimal safeParseDecimal(String value) {
        if (isBlank(value)) return null;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Parses a string to Integer.
     * Returns null if unparseable instead of throwing.
     */
    public Integer safeParseInt(String value) {
        if (isBlank(value)) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    /**
     * Parses a legacy MM/dd/yyyy date string to LocalDate.
     * Returns null if unparseable instead of throwing.
     */
    public LocalDate safeParseDate(String dateStr) {
        if (isBlank(dateStr)) return null;
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FMT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    // -----------------------------------------------------------------
    // Internal helpers
    // -----------------------------------------------------------------

    /** Extracts the last 4 digit characters from a phone number string. */
    String extractLast4Digits(String phone) {
        if (isBlank(phone)) return null;
        String digitsOnly = phone.replaceAll("[^0-9]", "");
        if (digitsOnly.length() < 4) return null;
        return digitsOnly.substring(digitsOnly.length() - 4);
    }

    private void validateDate(String dateStr, String column,
                              String recordId, List<String> warnings) {
        if (!isBlank(dateStr) && safeParseDate(dateStr) == null) {
            warnings.add(warn(recordId, column + " '" + dateStr
                    + "' is not a valid MM/dd/yyyy date"));
        }
    }

    private void validateAmount(String amount, String column,
                                String recordId, List<String> warnings) {
        if (!isBlank(amount) && safeParseAmount(amount) == null) {
            warnings.add(warn(recordId, column + " '" + amount
                    + "' is not a valid numeric amount"));
        }
    }

    private boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    private String warn(String recordId, String message) {
        return "[" + recordId + "] " + message;
    }
}
