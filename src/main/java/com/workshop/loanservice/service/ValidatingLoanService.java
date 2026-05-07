package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import com.workshop.loanservice.validation.DataQualityValidator;
import com.workshop.loanservice.validation.ValidationIssue;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Enhanced loan service with data quality validation.
 * Wraps legacy data access with validation, safe parsing, and error handling.
 * Replaces the original LoanService as the primary bean.
 */
@Service
@Primary
public class ValidatingLoanService {

    private static final Logger log = LoggerFactory.getLogger(ValidatingLoanService.class);

    private static final DateTimeFormatter LEGACY_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/uuuu").withResolverStyle(ResolverStyle.STRICT);

    private final LegacyBorrowerRepository borrowerRepository;
    private final LegacyLoanAccountRepository loanAccountRepository;
    private final LegacyLoanProductRepository loanProductRepository;
    private final LegacyPaymentRepository paymentRepository;
    private final DataQualityValidator validator;

    public ValidatingLoanService(LegacyBorrowerRepository borrowerRepository,
                                 LegacyLoanAccountRepository loanAccountRepository,
                                 LegacyLoanProductRepository loanProductRepository,
                                 LegacyPaymentRepository paymentRepository,
                                 DataQualityValidator validator) {
        this.borrowerRepository = borrowerRepository;
        this.loanAccountRepository = loanAccountRepository;
        this.loanProductRepository = loanProductRepository;
        this.paymentRepository = paymentRepository;
        this.validator = validator;
    }

    public List<LoanSummaryDto> getAllLoansValidated() {
        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));

        Set<String> validBorrowerIds = borrowerRepository.findAll().stream()
                .map(LegacyBorrower::getBorrowerId)
                .collect(Collectors.toSet());

        Set<String> validProductCodes = products.keySet();

        return loanAccountRepository.findAll().stream()
                .filter(acct -> {
                    List<ValidationIssue> issues = validator.validateLoanAccount(
                            acct, validBorrowerIds, validProductCodes);
                    logIssues(issues);
                    return issues.stream().noneMatch(i ->
                            i.getSeverity() == ValidationIssue.Severity.CRITICAL);
                })
                .map(acct -> toLoanSummarySafe(acct, products.get(acct.getProductCode())))
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanByIdValidated(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));

        Set<String> validBorrowerIds = borrowerRepository.findAll().stream()
                .map(LegacyBorrower::getBorrowerId)
                .collect(Collectors.toSet());
        Set<String> validProductCodes = loanProductRepository.findAll().stream()
                .map(LegacyLoanProduct::getProductCode)
                .collect(Collectors.toSet());

        List<ValidationIssue> issues = validator.validateLoanAccount(
                acct, validBorrowerIds, validProductCodes);
        logIssues(issues);

        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        return toLoanSummarySafe(acct, product);
    }

    public List<BorrowerDto> getAllBorrowersValidated() {
        return borrowerRepository.findAll().stream()
                .filter(borrower -> {
                    List<ValidationIssue> issues = validator.validateBorrower(borrower);
                    logIssues(issues);
                    return issues.stream().noneMatch(i ->
                            i.getSeverity() == ValidationIssue.Severity.CRITICAL);
                })
                .map(this::toBorrowerDtoSafe)
                .collect(Collectors.toList());
    }

    public List<PaymentDto> getPaymentsByLoanValidated(String loanAccountNumber) {
        Set<String> validLoanAccounts = loanAccountRepository.findAll().stream()
                .map(LegacyLoanAccount::getLoanAccountNumber)
                .collect(Collectors.toSet());

        return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .filter(pmt -> {
                    List<ValidationIssue> issues = validator.validatePayment(pmt, validLoanAccounts);
                    logIssues(issues);
                    return issues.stream().noneMatch(i ->
                            i.getSeverity() == ValidationIssue.Severity.CRITICAL);
                })
                .map(this::toPaymentDtoSafe)
                .collect(Collectors.toList());
    }

    private LoanSummaryDto toLoanSummarySafe(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());
        dto.setBorrowerName(safeConcatName(acct.getBorrowerFirstName(), acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : safeString(acct.getProductCode()));
        dto.setOriginalAmount(safeParseAmount(acct.getOriginalAmount(), "LN_ORIG_AMT", acct.getLoanAccountNumber()));
        dto.setCurrentBalance(safeParseAmount(acct.getCurrentBalance(), "LN_CURR_BAL", acct.getLoanAccountNumber()));
        dto.setInterestRate(safeParseDecimal(acct.getInterestRate(), "LN_INT_RT", acct.getLoanAccountNumber()));
        dto.setMonthlyPayment(safeParseAmount(acct.getMonthlyPayment(), "LN_PMT_AMT", acct.getLoanAccountNumber()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(safeParseDateToString(acct.getOriginationDate()));
        dto.setPropertyAddress(buildPropertyAddress(acct));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDtoSafe(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(safeString(borrower.getFirstName()) + middle + " " + safeString(borrower.getLastName()));
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(safeParseInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", borrower.getBorrowerId()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDtoSafe(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        String id = pmt.getPaymentSequenceNumber();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(safeParseDateToString(pmt.getPaymentDate()));
        dto.setTotalAmount(safeParseAmount(pmt.getTotalAmount(), "PMT_AMT", id));
        dto.setPrincipalAmount(safeParseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id));
        dto.setInterestAmount(safeParseAmount(pmt.getInterestAmount(), "PMT_INT_AMT", id));
        dto.setEscrowAmount(safeParseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id));
        dto.setLateFee(safeParseAmount(pmt.getLateFee(), "PMT_LATE_FEE", id));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    // =========================================================================
    // SAFE PARSING METHODS — catch and log errors instead of crashing
    // =========================================================================

    BigDecimal safeParseAmount(String amount, String column, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        String cleaned = amount.trim().replace(",", "");
        try {
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.warn("DATA_QUALITY: Failed to parse amount in column={}, record={}, value='{}': {}",
                    column, recordId, amount, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    BigDecimal safeParseDecimal(String value, String column, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("DATA_QUALITY: Failed to parse decimal in column={}, record={}, value='{}': {}",
                    column, recordId, value, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    Integer safeParseInteger(String value, String column, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("DATA_QUALITY: Failed to parse integer in column={}, record={}, value='{}': {}",
                    column, recordId, value, e.getMessage());
            return null;
        }
    }

    private String safeParseDateToString(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        try {
            LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
            return dateStr.trim();
        } catch (DateTimeParseException e) {
            log.warn("DATA_QUALITY: Invalid date format '{}', expected MM/DD/YYYY", dateStr);
            return dateStr.trim();
        }
    }

    private String safeConcatName(String firstName, String lastName) {
        String first = safeString(firstName);
        String last = safeString(lastName);
        if (first.isEmpty() && last.isEmpty()) {
            return "Unknown";
        }
        return (first + " " + last).trim();
    }

    private String safeString(String value) {
        return value != null ? value : "";
    }

    private String buildPropertyAddress(LegacyLoanAccount acct) {
        StringBuilder sb = new StringBuilder();
        if (acct.getPropertyAddress() != null) sb.append(acct.getPropertyAddress());
        if (acct.getPropertyCity() != null) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(acct.getPropertyCity());
        }
        if (acct.getPropertyState() != null) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(acct.getPropertyState());
        }
        if (acct.getPropertyZip() != null) {
            if (sb.length() > 0) sb.append(" ");
            sb.append(acct.getPropertyZip());
        }
        return sb.toString();
    }

    private String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> {
                log.warn("DATA_QUALITY: Unknown loan status code: '{}'", code);
                yield code;
            }
        };
    }

    private String expandPropertyType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "SFR" -> "Single Family Residence";
            case "CND" -> "Condominium";
            case "MFR" -> "Multi-Family Residence";
            case "TWN" -> "Townhouse";
            default -> {
                log.warn("DATA_QUALITY: Unknown property type code: '{}'", code);
                yield code;
            }
        };
    }

    private String expandPaymentType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "REG" -> "Regular";
            case "EXT" -> "Extra";
            case "PRT" -> "Partial";
            case "PRE" -> "Prepayment";
            default -> {
                log.warn("DATA_QUALITY: Unknown payment type code: '{}'", code);
                yield code;
            }
        };
    }

    private String expandPaymentStatus(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "PST" -> "Posted";
            case "REV" -> "Reversed";
            case "NSF" -> "Non-Sufficient Funds";
            case "PND" -> "Pending";
            default -> {
                log.warn("DATA_QUALITY: Unknown payment status code: '{}'", code);
                yield code;
            }
        };
    }

    private void logIssues(List<ValidationIssue> issues) {
        for (ValidationIssue issue : issues) {
            switch (issue.getSeverity()) {
                case CRITICAL -> log.error("DATA_QUALITY: {}", issue);
                case HIGH -> log.warn("DATA_QUALITY: {}", issue);
                case MEDIUM -> log.info("DATA_QUALITY: {}", issue);
                case LOW -> log.debug("DATA_QUALITY: {}", issue);
            }
        }
    }
}
