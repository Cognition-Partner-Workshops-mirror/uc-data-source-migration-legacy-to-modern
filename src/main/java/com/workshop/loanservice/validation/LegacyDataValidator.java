package com.workshop.loanservice.validation;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class LegacyDataValidator {
    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    public static BigDecimal parseAmount(String amount, String fieldName) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount for field '{}': '{}'", fieldName, amount);
            return BigDecimal.ZERO;
        }
    }

    public static BigDecimal parseDecimal(String value, String fieldName) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal for field '{}': '{}'", fieldName, value);
            return BigDecimal.ZERO;
        }
    }

    public static Integer parseInteger(String value, String fieldName) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer for field '{}': '{}'", fieldName, value);
            return null;
        }
    }

    public static LocalDate parseDate(String dateStr, String fieldName) {
        if (dateStr == null || dateStr.isBlank()) return null;
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date for field '{}': '{}'", fieldName, dateStr);
            return null;
        }
    }

    public static String validateDateFormat(String dateStr, String fieldName) {
        if (dateStr == null || dateStr.isBlank()) return null;
        try {
            LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return dateStr.trim();
        } catch (DateTimeParseException e) {
            log.warn("Invalid date format for field '{}': '{}' (expected MM/DD/YYYY)", fieldName, dateStr);
            return null;
        }
    }

    public static List<String> validatePaymentComponents(BigDecimal total, BigDecimal principal,
            BigDecimal interest, BigDecimal escrow, BigDecimal lateFee, String paymentId) {
        List<String> warnings = new ArrayList<>();
        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        if (total.compareTo(componentSum) != 0) {
            String msg = String.format(
                "Payment %s: component sum (%.2f) != total (%.2f), difference: %.2f",
                paymentId, componentSum, total, componentSum.subtract(total));
            log.warn(msg);
            warnings.add(msg);
        }
        return warnings;
    }

    public static String validateLoanStatusConsistency(String statusCode, String delinquencyDays, String loanId) {
        if (statusCode == null || delinquencyDays == null) return null;
        Integer days = parseInteger(delinquencyDays, "delinquencyDays");
        if (days != null && days > 0 && "ACT".equals(statusCode)) {
            String msg = String.format("Loan %s: status is ACT but delinquency days = %d", loanId, days);
            log.warn(msg);
            return msg;
        }
        return null;
    }

    public static boolean isPresent(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            log.warn("Required field '{}' is null/blank for record '{}'", fieldName, recordId);
            return false;
        }
        return true;
    }
}
