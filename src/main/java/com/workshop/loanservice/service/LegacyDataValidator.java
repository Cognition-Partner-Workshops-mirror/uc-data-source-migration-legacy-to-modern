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

/**
 * Validates legacy CDW data at ingestion time, catching known anomaly
 * patterns before they cause runtime failures or silent data corruption.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.01");

    // --- Safe parsing helpers with error handling ---

    public BigDecimal safeParseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse legacy amount '{}': {}", amount, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal safeParseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse legacy decimal '{}': {}", value, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    public Integer safeParseLegacyInteger(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse legacy integer '{}': {}", value, e.getMessage());
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
            log.warn("Failed to parse legacy date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    public String formatDateForApi(String legacyDate) {
        LocalDate parsed = safeParseLegacyDate(legacyDate);
        if (parsed == null) {
            return legacyDate;
        }
        return parsed.toString();
    }

    // --- Safe string helpers ---

    public String safeString(String value, String fallback) {
        return (value == null || value.isBlank()) ? fallback : value;
    }

    public String buildFullName(String firstName, String middleInitial, String lastName) {
        String first = safeString(firstName, "[Unknown]");
        String last = safeString(lastName, "[Unknown]");
        String middle = (middleInitial != null && !middleInitial.isBlank())
                ? " " + middleInitial + "."
                : "";
        return first + middle + " " + last;
    }

    public String buildBorrowerName(String firstName, String lastName) {
        String first = safeString(firstName, "[Unknown]");
        String last = safeString(lastName, "[Unknown]");
        return first + " " + last;
    }

    public String buildPropertyAddress(String address, String city, String state, String zip) {
        String addr = safeString(address, "");
        String cty = safeString(city, "");
        String st = safeString(state, "");
        String zp = safeString(zip, "");
        return addr + ", " + cty + ", " + st + " " + zp;
    }

    // --- Borrower validation ---

    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();

        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add("Borrower " + borrower.getBorrowerId() + ": first name is null/blank");
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add("Borrower " + borrower.getBorrowerId() + ": last name is null/blank");
        }
        if (borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            Integer score = safeParseLegacyInteger(borrower.getCreditScore());
            if (score != null && (score < 300 || score > 850)) {
                warnings.add("Borrower " + borrower.getBorrowerId()
                        + ": credit score " + score + " outside valid range 300-850");
            }
        }
        if (borrower.getDateOfBirth() != null && safeParseLegacyDate(borrower.getDateOfBirth()) == null) {
            warnings.add("Borrower " + borrower.getBorrowerId()
                    + ": unparseable date of birth '" + borrower.getDateOfBirth() + "'");
        }

        logWarnings(warnings);
        return warnings;
    }

    // --- Loan account validation ---

    public List<String> validateLoanAccount(LegacyLoanAccount acct) {
        List<String> warnings = new ArrayList<>();

        if (acct.getStatusCode() != null && acct.getDelinquencyDays() != null) {
            Integer dlqDays = safeParseLegacyInteger(acct.getDelinquencyDays());
            if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
                warnings.add("Loan " + acct.getLoanAccountNumber()
                        + ": " + dlqDays + " delinquency days but status is ACT");
            }
        }

        validateLtvConsistency(acct, warnings);
        validateSsnLast4(acct, warnings);

        logWarnings(warnings);
        return warnings;
    }

    private void validateLtvConsistency(LegacyLoanAccount acct, List<String> warnings) {
        BigDecimal origAmt = safeParseLegacyAmount(acct.getOriginalAmount());
        BigDecimal appraisedVal = safeParseLegacyAmount(acct.getAppraisedValue());
        BigDecimal storedLtv = safeParseLegacyDecimal(acct.getLtvPercent());

        if (appraisedVal.compareTo(BigDecimal.ZERO) > 0 && origAmt.compareTo(BigDecimal.ZERO) > 0) {
            BigDecimal calculatedLtv = origAmt
                    .multiply(new BigDecimal("100"))
                    .divide(appraisedVal, 1, RoundingMode.HALF_UP);
            BigDecimal diff = storedLtv.subtract(calculatedLtv).abs();
            if (diff.compareTo(new BigDecimal("0.5")) > 0) {
                warnings.add("Loan " + acct.getLoanAccountNumber()
                        + ": stored LTV " + storedLtv + " differs from calculated "
                        + calculatedLtv + " by " + diff + "%");
            }
        }
    }

    private void validateSsnLast4(LegacyLoanAccount acct, List<String> warnings) {
        // No-op if either field is absent on the entity
    }

    public void crossValidateSsnLast4(LegacyLoanAccount acct, LegacyBorrower borrower) {
        if (acct.getBorrowerSsnLast4() == null || borrower.getPhoneNumber() == null) {
            return;
        }
        String phoneLast4 = borrower.getPhoneNumber().replaceAll("[^0-9]", "");
        if (phoneLast4.length() >= 4) {
            phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
            if (phoneLast4.equals(acct.getBorrowerSsnLast4())) {
                log.warn("Loan {}: SSN last-4 '{}' matches phone last-4 — likely data quality issue",
                        acct.getLoanAccountNumber(), acct.getBorrowerSsnLast4());
            }
        }
    }

    // --- Payment validation ---

    public List<String> validatePayment(LegacyPayment pmt) {
        List<String> warnings = new ArrayList<>();

        BigDecimal total = safeParseLegacyAmount(pmt.getTotalAmount());
        BigDecimal principal = safeParseLegacyAmount(pmt.getPrincipalAmount());
        BigDecimal interest = safeParseLegacyAmount(pmt.getInterestAmount());
        BigDecimal escrow = safeParseLegacyAmount(pmt.getEscrowAmount());
        BigDecimal lateFee = safeParseLegacyAmount(pmt.getLateFee());

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal diff = componentSum.subtract(total).abs();

        if (diff.compareTo(PAYMENT_TOLERANCE) > 0) {
            warnings.add("Payment " + pmt.getPaymentSequenceNumber()
                    + ": component sum " + componentSum
                    + " differs from total " + total
                    + " by " + diff);
        }

        if (pmt.getPaymentDate() != null && safeParseLegacyDate(pmt.getPaymentDate()) == null) {
            warnings.add("Payment " + pmt.getPaymentSequenceNumber()
                    + ": unparseable payment date '" + pmt.getPaymentDate() + "'");
        }

        logWarnings(warnings);
        return warnings;
    }

    // --- Expand status codes with validation ---

    public String expandLoanStatus(String code) {
        if (code == null || code.isBlank()) {
            log.warn("Loan status code is null/blank, defaulting to 'Unknown'");
            return "Unknown";
        }
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> {
                log.warn("Unrecognized loan status code '{}', passing through as-is", code);
                yield code;
            }
        };
    }

    public String expandPropertyType(String code) {
        if (code == null || code.isBlank()) {
            return "Unknown";
        }
        return switch (code) {
            case "SFR" -> "Single Family Residence";
            case "CND" -> "Condominium";
            case "MFR" -> "Multi-Family Residence";
            case "TWN" -> "Townhouse";
            default -> {
                log.warn("Unrecognized property type code '{}'", code);
                yield code;
            }
        };
    }

    public String expandPaymentType(String code) {
        if (code == null || code.isBlank()) {
            return "Unknown";
        }
        return switch (code) {
            case "REG" -> "Regular";
            case "EXT" -> "Extra";
            case "PRT" -> "Partial";
            case "PRE" -> "Prepayment";
            default -> {
                log.warn("Unrecognized payment type code '{}'", code);
                yield code;
            }
        };
    }

    public String expandPaymentStatus(String code) {
        if (code == null || code.isBlank()) {
            return "Unknown";
        }
        return switch (code) {
            case "PST" -> "Posted";
            case "REV" -> "Reversed";
            case "NSF" -> "Non-Sufficient Funds";
            case "PND" -> "Pending";
            default -> {
                log.warn("Unrecognized payment status code '{}'", code);
                yield code;
            }
        };
    }

    private void logWarnings(List<String> warnings) {
        for (String w : warnings) {
            log.warn("Data quality: {}", w);
        }
    }
}
