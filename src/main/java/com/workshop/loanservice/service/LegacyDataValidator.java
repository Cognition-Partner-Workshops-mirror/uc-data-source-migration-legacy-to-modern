package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
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
import java.util.Map;
import java.util.Set;

/**
 * Validates legacy CDW data at ingestion time, catching known anomaly
 * patterns before they propagate to DTOs and API responses.
 */
@Component
public class LegacyDataValidator {

    private static final Logger log = LoggerFactory.getLogger(LegacyDataValidator.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");
    private static final Set<String> VALID_PROPERTY_TYPE_CODES = Set.of("SFR", "CND", "MFR", "TWN");
    private static final Set<String> VALID_BORROWER_STATUS_CODES = Set.of("ACT", "INA");
    private static final Set<String> VALID_PRODUCT_STATUS_CODES = Set.of("ACT", "INA");

    private static final int CREDIT_SCORE_MIN = 300;
    private static final int CREDIT_SCORE_MAX = 850;
    private static final BigDecimal INTEREST_RATE_MAX = new BigDecimal("100");
    private static final BigDecimal PAYMENT_TOLERANCE = new BigDecimal("0.02");

    // =========================================================================
    // PUBLIC VALIDATION METHODS
    // =========================================================================

    public List<String> validateBorrower(LegacyBorrower borrower) {
        List<String> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        validateRequiredField(warnings, id, "firstName", borrower.getFirstName());
        validateRequiredField(warnings, id, "lastName", borrower.getLastName());
        validateRequiredField(warnings, id, "ssnEncrypted", borrower.getSsnEncrypted());
        validateRequiredField(warnings, id, "statusCode", borrower.getStatusCode());

        validateDate(warnings, id, "dateOfBirth", borrower.getDateOfBirth());
        validateDate(warnings, id, "createdDate", borrower.getCreatedDate());
        validateDate(warnings, id, "updatedDate", borrower.getUpdatedDate());

        validateCreditScore(warnings, id, borrower.getCreditScore());
        validateAmount(warnings, id, "annualIncome", borrower.getAnnualIncome());

        if (borrower.getStatusCode() != null && !VALID_BORROWER_STATUS_CODES.contains(borrower.getStatusCode())) {
            warnings.add(String.format("[%s] Invalid borrower status code: '%s'", id, borrower.getStatusCode()));
        }

        return warnings;
    }

    public List<String> validateLoanAccount(LegacyLoanAccount account,
                                            Map<String, ?> borrowerIndex,
                                            Map<String, ?> productIndex) {
        List<String> warnings = new ArrayList<>();
        String id = account.getLoanAccountNumber();

        validateRequiredField(warnings, id, "borrowerId", account.getBorrowerId());
        validateRequiredField(warnings, id, "productCode", account.getProductCode());
        validateRequiredField(warnings, id, "originalAmount", account.getOriginalAmount());
        validateRequiredField(warnings, id, "currentBalance", account.getCurrentBalance());
        validateRequiredField(warnings, id, "statusCode", account.getStatusCode());

        // FK validation
        if (account.getBorrowerId() != null && !borrowerIndex.containsKey(account.getBorrowerId())) {
            warnings.add(String.format("[%s] Orphaned record: BORR_ID '%s' not found in CDW_BORR_MSTR",
                    id, account.getBorrowerId()));
        }
        if (account.getProductCode() != null && !productIndex.containsKey(account.getProductCode())) {
            warnings.add(String.format("[%s] Orphaned record: PROD_CD '%s' not found in CDW_LN_PROD",
                    id, account.getProductCode()));
        }

        validateAmount(warnings, id, "originalAmount", account.getOriginalAmount());
        validateAmount(warnings, id, "currentBalance", account.getCurrentBalance());
        validateAmount(warnings, id, "monthlyPayment", account.getMonthlyPayment());
        validateAmount(warnings, id, "escrowBalance", account.getEscrowBalance());
        validateAmount(warnings, id, "appraisedValue", account.getAppraisedValue());
        validateDecimal(warnings, id, "interestRate", account.getInterestRate());
        validateInteger(warnings, id, "termMonths", account.getTermMonths());
        validateInteger(warnings, id, "delinquencyDays", account.getDelinquencyDays());
        validateDecimal(warnings, id, "ltvPercent", account.getLtvPercent());

        validateDate(warnings, id, "originationDate", account.getOriginationDate());
        validateDate(warnings, id, "maturityDate", account.getMaturityDate());
        validateDate(warnings, id, "firstPaymentDate", account.getFirstPaymentDate());
        validateDate(warnings, id, "nextPaymentDate", account.getNextPaymentDate());

        if (account.getStatusCode() != null && !VALID_LOAN_STATUS_CODES.contains(account.getStatusCode())) {
            warnings.add(String.format("[%s] Invalid loan status code: '%s'", id, account.getStatusCode()));
        }

        if (account.getPropertyType() != null && !account.getPropertyType().isBlank()
                && !VALID_PROPERTY_TYPE_CODES.contains(account.getPropertyType())) {
            warnings.add(String.format("[%s] Invalid property type code: '%s'", id, account.getPropertyType()));
        }

        // Interest rate range
        BigDecimal rate = safeParseDecimal(account.getInterestRate());
        if (rate != null && (rate.compareTo(BigDecimal.ZERO) < 0 || rate.compareTo(INTEREST_RATE_MAX) > 0)) {
            warnings.add(String.format("[%s] Interest rate out of range: %s", id, account.getInterestRate()));
        }

        // Delinquency vs status cross-validation
        Integer dlqDays = safeParseInteger(account.getDelinquencyDays());
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(account.getStatusCode())) {
            warnings.add(String.format("[%s] Delinquent (%d days) but status is ACT — expected DFT or FRB",
                    id, dlqDays));
        }

        // Date logic: origination < maturity
        LocalDate origDate = safeParseDate(account.getOriginationDate());
        LocalDate matDate = safeParseDate(account.getMaturityDate());
        if (origDate != null && matDate != null && !origDate.isBefore(matDate)) {
            warnings.add(String.format("[%s] Origination date %s is not before maturity date %s",
                    id, account.getOriginationDate(), account.getMaturityDate()));
        }

        // Denormalized name cross-validation
        if (account.getBorrowerId() != null && borrowerIndex.containsKey(account.getBorrowerId())) {
            Object borrowerObj = borrowerIndex.get(account.getBorrowerId());
            if (borrowerObj instanceof LegacyBorrower borrower) {
                if (account.getBorrowerFirstName() != null
                        && !account.getBorrowerFirstName().equals(borrower.getFirstName())) {
                    warnings.add(String.format(
                            "[%s] Denormalized first name mismatch: loan has '%s', borrower master has '%s'",
                            id, account.getBorrowerFirstName(), borrower.getFirstName()));
                }
                if (account.getBorrowerLastName() != null
                        && !account.getBorrowerLastName().equals(borrower.getLastName())) {
                    warnings.add(String.format(
                            "[%s] Denormalized last name mismatch: loan has '%s', borrower master has '%s'",
                            id, account.getBorrowerLastName(), borrower.getLastName()));
                }
                // SSN last-4 vs phone number check
                if (account.getBorrowerSsnLast4() != null && borrower.getPhoneNumber() != null) {
                    String phoneLast4 = borrower.getPhoneNumber().replaceAll("[^0-9]", "");
                    if (phoneLast4.length() >= 4) {
                        phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
                        if (account.getBorrowerSsnLast4().equals(phoneLast4)) {
                            warnings.add(String.format(
                                    "[%s] BORR_SSN_LST4 '%s' matches phone last-4 — likely contains phone digits, not SSN",
                                    id, account.getBorrowerSsnLast4()));
                        }
                    }
                }
            }
        }

        return warnings;
    }

    public List<String> validatePayment(LegacyPayment payment, Map<String, ?> loanAccountIndex) {
        List<String> warnings = new ArrayList<>();
        String id = payment.getPaymentSequenceNumber();

        validateRequiredField(warnings, id, "loanAccountNumber", payment.getLoanAccountNumber());
        validateRequiredField(warnings, id, "paymentDate", payment.getPaymentDate());
        validateRequiredField(warnings, id, "totalAmount", payment.getTotalAmount());
        validateRequiredField(warnings, id, "statusCode", payment.getStatusCode());
        validateRequiredField(warnings, id, "typeCode", payment.getTypeCode());

        // FK validation
        if (payment.getLoanAccountNumber() != null
                && !loanAccountIndex.containsKey(payment.getLoanAccountNumber())) {
            warnings.add(String.format("[%s] Orphaned record: LN_ACCT_NBR '%s' not found in CDW_LN_ACCT",
                    id, payment.getLoanAccountNumber()));
        }

        validateAmount(warnings, id, "totalAmount", payment.getTotalAmount());
        validateAmount(warnings, id, "principalAmount", payment.getPrincipalAmount());
        validateAmount(warnings, id, "interestAmount", payment.getInterestAmount());
        validateAmount(warnings, id, "escrowAmount", payment.getEscrowAmount());
        validateAmount(warnings, id, "lateFee", payment.getLateFee());

        validateDate(warnings, id, "paymentDate", payment.getPaymentDate());
        validateDate(warnings, id, "receivedDate", payment.getReceivedDate());
        validateDate(warnings, id, "processedDate", payment.getProcessedDate());

        if (payment.getTypeCode() != null && !VALID_PAYMENT_TYPE_CODES.contains(payment.getTypeCode())) {
            warnings.add(String.format("[%s] Invalid payment type code: '%s'", id, payment.getTypeCode()));
        }
        if (payment.getStatusCode() != null && !VALID_PAYMENT_STATUS_CODES.contains(payment.getStatusCode())) {
            warnings.add(String.format("[%s] Invalid payment status code: '%s'", id, payment.getStatusCode()));
        }

        // Component sum validation
        validatePaymentComponents(warnings, id, payment);

        return warnings;
    }

    public List<String> validateLoanProduct(LegacyLoanProduct product) {
        List<String> warnings = new ArrayList<>();
        String id = product.getProductCode();

        validateRequiredField(warnings, id, "description", product.getDescription());
        validateRequiredField(warnings, id, "typeCode", product.getTypeCode());
        validateRequiredField(warnings, id, "statusCode", product.getStatusCode());

        validateAmount(warnings, id, "minAmount", product.getMinAmount());
        validateAmount(warnings, id, "maxAmount", product.getMaxAmount());
        validateInteger(warnings, id, "termMonths", product.getTermMonths());
        validateDate(warnings, id, "effectiveDate", product.getEffectiveDate());
        validateDate(warnings, id, "expirationDate", product.getExpirationDate());

        if (product.getStatusCode() != null && !VALID_PRODUCT_STATUS_CODES.contains(product.getStatusCode())) {
            warnings.add(String.format("[%s] Invalid product status code: '%s'", id, product.getStatusCode()));
        }

        // Min < Max amount
        BigDecimal min = safeParseAmount(product.getMinAmount());
        BigDecimal max = safeParseAmount(product.getMaxAmount());
        if (min != null && max != null && min.compareTo(max) > 0) {
            warnings.add(String.format("[%s] Min amount %s exceeds max amount %s", id,
                    product.getMinAmount(), product.getMaxAmount()));
        }

        return warnings;
    }

    // =========================================================================
    // SAFE PARSING METHODS (with error handling and fallbacks)
    // =========================================================================

    public BigDecimal safeParseAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
            return null;
        }
    }

    public BigDecimal safeParseDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}': {}", value, e.getMessage());
            return null;
        }
    }

    public Integer safeParseInteger(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    public LocalDate safeParseDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        try {
            return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}': {}", dateStr, e.getMessage());
            return null;
        }
    }

    // =========================================================================
    // PRIVATE VALIDATION HELPERS
    // =========================================================================

    private void validateRequiredField(List<String> warnings, String recordId, String fieldName, String value) {
        if (value == null || value.isBlank()) {
            warnings.add(String.format("[%s] Required field '%s' is null or blank", recordId, fieldName));
        }
    }

    private void validateAmount(List<String> warnings, String recordId, String fieldName, String value) {
        if (value == null || value.isBlank()) return;
        BigDecimal parsed = safeParseAmount(value);
        if (parsed == null) {
            warnings.add(String.format("[%s] Field '%s' has unparseable amount: '%s'", recordId, fieldName, value));
        } else if (parsed.compareTo(BigDecimal.ZERO) < 0) {
            warnings.add(String.format("[%s] Field '%s' has negative amount: %s", recordId, fieldName, value));
        }
    }

    private void validateDecimal(List<String> warnings, String recordId, String fieldName, String value) {
        if (value == null || value.isBlank()) return;
        BigDecimal parsed = safeParseDecimal(value);
        if (parsed == null) {
            warnings.add(String.format("[%s] Field '%s' has unparseable decimal: '%s'", recordId, fieldName, value));
        }
    }

    private void validateInteger(List<String> warnings, String recordId, String fieldName, String value) {
        if (value == null || value.isBlank()) return;
        Integer parsed = safeParseInteger(value);
        if (parsed == null) {
            warnings.add(String.format("[%s] Field '%s' has unparseable integer: '%s'", recordId, fieldName, value));
        }
    }

    private void validateDate(List<String> warnings, String recordId, String fieldName, String value) {
        if (value == null || value.isBlank()) return;
        LocalDate parsed = safeParseDate(value);
        if (parsed == null) {
            warnings.add(String.format("[%s] Field '%s' has unparseable date: '%s' (expected MM/DD/YYYY)",
                    recordId, fieldName, value));
        }
    }

    private void validateCreditScore(List<String> warnings, String recordId, String value) {
        if (value == null || value.isBlank()) return;
        Integer score = safeParseInteger(value);
        if (score == null) {
            warnings.add(String.format("[%s] Credit score has unparseable value: '%s'", recordId, value));
        } else if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            warnings.add(String.format("[%s] Credit score %d out of range [%d–%d]",
                    recordId, score, CREDIT_SCORE_MIN, CREDIT_SCORE_MAX));
        }
    }

    private void validatePaymentComponents(List<String> warnings, String recordId, LegacyPayment payment) {
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (total == null || principal == null || interest == null || escrow == null || lateFee == null) {
            return; // unparseable values already flagged
        }

        BigDecimal componentSum = principal.add(interest).add(escrow).add(lateFee);
        BigDecimal diff = total.subtract(componentSum).abs();

        if (diff.compareTo(PAYMENT_TOLERANCE) > 0) {
            warnings.add(String.format(
                    "[%s] Payment total %s ≠ components sum %s (principal=%s + interest=%s + escrow=%s + lateFee=%s), diff=%s",
                    recordId, total, componentSum, principal, interest, escrow, lateFee,
                    diff.setScale(2, RoundingMode.HALF_UP)));
        }
    }
}
