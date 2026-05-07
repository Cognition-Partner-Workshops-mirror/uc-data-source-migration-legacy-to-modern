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
import com.workshop.loanservice.validation.LegacyDataValidator;
import com.workshop.loanservice.validation.ValidationResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Service layer that reads from legacy tables and translates
 * cryptic legacy fields into clean DTOs.
 *
 * MIGRATION TASK: This service contains all the translation logic
 * between legacy string-typed fields and proper Java types.
 * When switching data sources, this layer needs to be updated
 * (or replaced) to read from the modern schema.
 */
@Service
public class LoanService {

    private static final Logger log = LoggerFactory.getLogger(LoanService.class);

    private final LegacyBorrowerRepository borrowerRepository;
    private final LegacyLoanAccountRepository loanAccountRepository;
    private final LegacyLoanProductRepository loanProductRepository;
    private final LegacyPaymentRepository paymentRepository;
    private final LegacyDataValidator validator;

    public LoanService(LegacyBorrowerRepository borrowerRepository,
                       LegacyLoanAccountRepository loanAccountRepository,
                       LegacyLoanProductRepository loanProductRepository,
                       LegacyPaymentRepository paymentRepository,
                       LegacyDataValidator validator) {
        this.borrowerRepository = borrowerRepository;
        this.loanAccountRepository = loanAccountRepository;
        this.loanProductRepository = loanProductRepository;
        this.paymentRepository = paymentRepository;
        this.validator = validator;
    }

    public List<LoanSummaryDto> getAllLoans() {
        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));

        Map<String, LegacyBorrower> borrowers = borrowerRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyBorrower::getBorrowerId, b -> b));

        List<LoanSummaryDto> results = new ArrayList<>();
        for (LegacyLoanAccount acct : loanAccountRepository.findAll()) {
            LegacyBorrower borrower = borrowers.get(acct.getBorrowerId());
            ValidationResult validation = validator.validateLoanAccount(acct, borrower);
            LoanSummaryDto dto = toLoanSummary(acct, products.get(acct.getProductCode()), validation);
            results.add(dto);
        }
        return results;
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        LegacyBorrower borrower = acct.getBorrowerId() != null
                ? borrowerRepository.findById(acct.getBorrowerId()).orElse(null)
                : null;
        ValidationResult validation = validator.validateLoanAccount(acct, borrower);
        return toLoanSummary(acct, product, validation);
    }

    public List<BorrowerDto> getAllBorrowers() {
        List<BorrowerDto> results = new ArrayList<>();
        for (LegacyBorrower borrower : borrowerRepository.findAll()) {
            ValidationResult validation = validator.validateBorrower(borrower);
            results.add(toBorrowerDto(borrower, validation));
        }
        return results;
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
        ValidationResult validation = validator.validateBorrower(borrower);
        BorrowerDto dto = toBorrowerDto(borrower, validation);

        // Attach loans for this borrower
        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> {
                    ValidationResult loanValidation = validator.validateLoanAccount(acct, borrower);
                    return toLoanSummary(acct, products.get(acct.getProductCode()), loanValidation);
                })
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        List<PaymentDto> results = new ArrayList<>();
        for (LegacyPayment pmt : paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)) {
            ValidationResult validation = validator.validatePayment(pmt);
            results.add(toPaymentDto(pmt, validation));
        }
        return results;
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types with validation-aware error handling.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product,
                                         ValidationResult validation) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());
        dto.setBorrowerName(safeConcatName(acct.getBorrowerFirstName(), acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : safeDefault(acct.getProductCode(), "Unknown Product"));
        dto.setOriginalAmount(safeParseAmount(acct.getOriginalAmount(), "LN_ORIG_AMT", acct.getLoanAccountNumber()));
        dto.setCurrentBalance(safeParseAmount(acct.getCurrentBalance(), "LN_CURR_BAL", acct.getLoanAccountNumber()));
        dto.setInterestRate(safeParseDecimal(acct.getInterestRate(), "LN_INT_RT", acct.getLoanAccountNumber()));
        dto.setMonthlyPayment(safeParseAmount(acct.getMonthlyPayment(), "LN_PMT_AMT", acct.getLoanAccountNumber()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(acct.getOriginationDate());
        dto.setPropertyAddress(buildPropertyAddress(acct));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        dto.setValidationWarnings(formatWarnings(validation));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower, ValidationResult validation) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(safeDefault(borrower.getFirstName(), "") + middle + " " + safeDefault(borrower.getLastName(), ""));
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(safeParseIntegerField(borrower.getCreditScore(), "BORR_CRDT_SCR", borrower.getBorrowerId()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        dto.setValidationWarnings(formatWarnings(validation));
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt, ValidationResult validation) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate());
        dto.setTotalAmount(safeParseAmount(pmt.getTotalAmount(), "PMT_AMT", pmt.getPaymentSequenceNumber()));
        dto.setPrincipalAmount(safeParseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", pmt.getPaymentSequenceNumber()));
        dto.setInterestAmount(safeParseAmount(pmt.getInterestAmount(), "PMT_INT_AMT", pmt.getPaymentSequenceNumber()));
        dto.setEscrowAmount(safeParseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", pmt.getPaymentSequenceNumber()));
        dto.setLateFee(safeParseAmount(pmt.getLateFee(), "PMT_LATE_FEE", pmt.getPaymentSequenceNumber()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        dto.setValidationWarnings(formatWarnings(validation));
        return dto;
    }

    // =========================================================================
    // SAFE PARSING METHODS — handle malformed data gracefully
    // =========================================================================

    private BigDecimal safeParseAmount(String amount, String fieldName, String recordId) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        BigDecimal result = validator.safeParseAmount(amount);
        if (result == null) {
            log.error("Failed to parse amount field {} for record {}: '{}'", fieldName, recordId, amount);
            return BigDecimal.ZERO;
        }
        return result;
    }

    private BigDecimal safeParseDecimal(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return BigDecimal.ZERO;
        }
        BigDecimal result = validator.safeParseDecimal(value);
        if (result == null) {
            log.error("Failed to parse decimal field {} for record {}: '{}'", fieldName, recordId, value);
            return BigDecimal.ZERO;
        }
        return result;
    }

    private Integer safeParseIntegerField(String value, String fieldName, String recordId) {
        if (value == null || value.isBlank()) {
            return null;
        }
        Integer result = validator.safeParseInteger(value);
        if (result == null) {
            log.error("Failed to parse integer field {} for record {}: '{}'", fieldName, recordId, value);
            return null;
        }
        return result;
    }

    // =========================================================================
    // STRING HELPERS
    // =========================================================================

    private String safeConcatName(String firstName, String lastName) {
        String first = safeDefault(firstName, "Unknown");
        String last = safeDefault(lastName, "Unknown");
        return first + " " + last;
    }

    private String buildPropertyAddress(LegacyLoanAccount acct) {
        String addr = safeDefault(acct.getPropertyAddress(), "");
        String city = safeDefault(acct.getPropertyCity(), "");
        String state = safeDefault(acct.getPropertyState(), "");
        String zip = safeDefault(acct.getPropertyZip(), "");
        return addr + ", " + city + ", " + state + " " + zip;
    }

    private String safeDefault(String value, String defaultValue) {
        return (value != null && !value.isBlank()) ? value : defaultValue;
    }

    private List<String> formatWarnings(ValidationResult validation) {
        if (validation == null || !validation.hasWarnings()) {
            return null;
        }
        return validation.getWarnings().stream()
                .map(w -> "[" + w.severity() + "] " + w.field() + ": " + w.message())
                .toList();
    }

    // =========================================================================
    // CODE EXPANSION METHODS
    // =========================================================================

    private String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> {
                log.warn("Unknown loan status code: '{}'", code);
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
                log.warn("Unknown property type code: '{}'", code);
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
                log.warn("Unknown payment type code: '{}'", code);
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
                log.warn("Unknown payment status code: '{}'", code);
                yield code;
            }
        };
    }
}
