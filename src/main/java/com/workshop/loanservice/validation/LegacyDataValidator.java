package com.workshop.loanservice.validation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Set;

@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.02");

    private static final Set<String> VALID_LOAN_STATUSES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUSES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPES = Set.of("SFR", "CND", "MFR", "TWN");

    public BigDecimal parseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "")
                    .replace("$", "")
                    .replace(" ", "")
                    .trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Unparseable amount in {}.{}: '{}' — defaulting to ZERO", recordId, fieldName, amount);
            return BigDecimal.ZERO;
        }
    }

    public BigDecimal parseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal in {}.{}: '{}' — defaulting to ZERO", recordId, fieldName, value);
            return BigDecimal.ZERO;
        }
    }

    public Integer parseInteger(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer in {}.{}: '{}' — defaulting to null", recordId, fieldName, value);
            return null;
        }
    }

    public LocalDate parseLegacyDate(String dateStr, String fieldName, String recordId) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Unparseable date in {}.{}: '{}' — defaulting to null", recordId, fieldName, dateStr);
            return null;
        }
    }

    public boolean validatePaymentComponents(String paymentId, BigDecimal total,
                                              BigDecimal principal, BigDecimal interest,
                                              BigDecimal escrow, BigDecimal lateFee) {
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal diff = total.subtract(componentSum).abs();
        if (diff.compareTo(PAYMENT_TOLERANCE) > 0) {
            log.warn("Payment component mismatch for {}: total={} but components sum to {} (delta={})",
                    paymentId, total, componentSum, diff);
            return false;
        }
        return true;
    }

    public boolean validateLoanStatus(String statusCode, String delinquencyDaysStr, String loanId) {
        if (statusCode != null && !VALID_LOAN_STATUSES.contains(statusCode)) {
            log.warn("Unrecognized loan status code '{}' for loan {}", statusCode, loanId);
            return false;
        }
        Integer delinquencyDays = parseInteger(delinquencyDaysStr, "LN_DLQ_DAYS", loanId);
        if (delinquencyDays != null && delinquencyDays > 0 && "ACT".equals(statusCode)) {
            log.warn("Loan {} has {} delinquency days but status is ACT", loanId, delinquencyDays);
        }
        return true;
    }

    public boolean validatePaymentType(String typeCode, String paymentId) {
        if (typeCode != null && !VALID_PAYMENT_TYPES.contains(typeCode)) {
            log.warn("Unrecognized payment type code '{}' for payment {}", typeCode, paymentId);
            return false;
        }
        return true;
    }

    public boolean validatePaymentStatus(String statusCode, String paymentId) {
        if (statusCode != null && !VALID_PAYMENT_STATUSES.contains(statusCode)) {
            log.warn("Unrecognized payment status code '{}' for payment {}", statusCode, paymentId);
            return false;
        }
        return true;
    }

    public boolean validatePropertyType(String typeCode, String loanId) {
        if (typeCode != null && !VALID_PROPERTY_TYPES.contains(typeCode)) {
            log.warn("Unrecognized property type code '{}' for loan {}", typeCode, loanId);
            return false;
        }
        return true;
    }

    public String buildSafeAddress(String address, String city, String state, String zip) {
        StringBuilder sb = new StringBuilder();
        if (address != null && !address.isBlank()) {
            sb.append(address.trim());
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
        return sb.length() > 0 ? sb.toString() : "Address unavailable";
    }

    public String buildSafeName(String firstName, String lastName) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName.trim() : "Unknown";
        String last = (lastName != null && !lastName.isBlank()) ? lastName.trim() : "Unknown";
        return first + " " + last;
    }

    public String buildSafeFullName(String firstName, String middleInitial, String lastName) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName.trim() : "Unknown";
        String last = (lastName != null && !lastName.isBlank()) ? lastName.trim() : "Unknown";
        String middle = (middleInitial != null && !middleInitial.isBlank())
                ? " " + middleInitial.trim() + "."
                : "";
        return first + middle + " " + last;
    }

    public boolean validateSsnNotPhoneSuffix(String ssnLast4, String phone, String recordId) {
        if (ssnLast4 == null || phone == null) {
            return true;
        }
        String phoneSuffix = phone.replaceAll("[^0-9]", "");
        if (phoneSuffix.length() >= 4) {
            phoneSuffix = phoneSuffix.substring(phoneSuffix.length() - 4);
            if (ssnLast4.equals(phoneSuffix)) {
                log.warn("SSN last-4 '{}' matches phone suffix for record {} — possible data entry error",
                        ssnLast4, recordId);
                return false;
            }
        }
        return true;
    }

    public BigDecimal calculateLtv(BigDecimal originalAmount, BigDecimal appraisedValue) {
        if (originalAmount == null || appraisedValue == null || appraisedValue.compareTo(BigDecimal.ZERO) == 0) {
            return BigDecimal.ZERO;
        }
        return originalAmount
                .multiply(new BigDecimal("100"))
                .divide(appraisedValue, 2, RoundingMode.HALF_UP);
    }

    public String formatLegacyDate(String dateStr, String fieldName, String recordId) {
        LocalDate parsed = parseLegacyDate(dateStr, fieldName, recordId);
        if (parsed != null) {
            return parsed.toString();
        }
        return dateStr;
    }
}
