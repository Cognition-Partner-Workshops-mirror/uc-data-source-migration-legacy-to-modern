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
import com.workshop.loanservice.validation.DataQualityIssue;
import com.workshop.loanservice.validation.LegacyDataValidator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
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
 *
 * Data validation added to catch anomalies at ingestion time —
 * see docs/DATA_ANOMALY_REPORT.md for the full list of known issues.
 */
@Service
public class LoanService {

    private static final Logger log = LoggerFactory.getLogger(LoanService.class);

    // Fallback marker for missing required string fields (ANO-005)
    private static final String UNKNOWN_MARKER = "[Unknown]";

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

        // Validate each loan account at ingestion time (ANO-003, ANO-004, ANO-005)
        return loanAccountRepository.findAll().stream()
                .map(acct -> {
                    validator.validateLoanAccount(acct);
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        // Validate the loan account before translation
        validator.validateLoanAccount(acct);
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        // Validate each borrower at ingestion time (ANO-003, ANO-005, ANO-010)
        return borrowerRepository.findAll().stream()
                .map(borrower -> {
                    validator.validateBorrower(borrower);
                    return toBorrowerDto(borrower);
                })
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
        // Validate borrower before translation
        validator.validateBorrower(borrower);
        BorrowerDto dto = toBorrowerDto(borrower);

        // Attach loans for this borrower, with denormalized-name divergence check (ANO-007)
        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> {
                    validator.validateLoanAccount(acct);
                    validator.validateDenormalizedBorrowerName(acct, borrower);
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        // Validate each payment at ingestion time (ANO-001, ANO-003, ANO-009)
        return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(pmt -> {
                    validator.validatePayment(pmt);
                    return toPaymentDto(pmt);
                })
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    // Now uses safe parsing from LegacyDataValidator to prevent
    // NumberFormatException crashes (ANO-003 fix).
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());
        // ANO-005 fix: guard against null borrower names producing "null null"
        dto.setBorrowerName(safeConcat(acct.getBorrowerFirstName(), acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        // ANO-003 fix: use safe parsing with fallback to BigDecimal.ZERO
        dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
        dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
        dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
        dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(acct.getOriginationDate());
        // ANO-005 fix: guard against null property address components
        dto.setPropertyAddress(safePropertyAddress(acct));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());
        // ANO-005 fix: null-safe full name construction
        String first = borrower.getFirstName() != null ? borrower.getFirstName() : UNKNOWN_MARKER;
        String last = borrower.getLastName() != null ? borrower.getLastName() : UNKNOWN_MARKER;
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(first + middle + " " + last);
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        // ANO-003 fix: safe integer parsing for credit score
        dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate());
        // ANO-003 fix: safe amount parsing for all payment fields
        dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
        dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
        dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
        dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
        dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    // =========================================================================
    // SAFE PARSING METHODS
    // Wrap all legacy string→type conversions in try-catch to prevent
    // NumberFormatException from crashing the entire API request (ANO-003).
    // =========================================================================

    /**
     * Parse legacy amount strings like "285,000" or "1,487.02" into BigDecimal.
     * Returns BigDecimal.ZERO for null, blank, or unparseable values (ANO-003 fix).
     */
    private BigDecimal parseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            // Log and return safe default instead of crashing
            log.warn("Unparseable amount '{}', defaulting to ZERO", amount);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse decimal strings like "5.250" into BigDecimal.
     * Returns BigDecimal.ZERO for unparseable values (ANO-003 fix).
     */
    private BigDecimal parseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable decimal '{}', defaulting to ZERO", value);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse integer strings like "360" into Integer.
     * Returns null for unparseable values (ANO-003 fix).
     */
    private Integer parseLegacyInteger(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Unparseable integer '{}', defaulting to null", value);
            return null;
        }
    }

    // =========================================================================
    // STATUS CODE EXPANSION
    // =========================================================================

    private String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> code;
        };
    }

    private String expandPropertyType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "SFR" -> "Single Family Residence";
            case "CND" -> "Condominium";
            case "MFR" -> "Multi-Family Residence";
            case "TWN" -> "Townhouse";
            default -> code;
        };
    }

    private String expandPaymentType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "REG" -> "Regular";
            case "EXT" -> "Extra";
            case "PRT" -> "Partial";
            case "PRE" -> "Prepayment";
            default -> code;
        };
    }

    private String expandPaymentStatus(String code) {
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
    // STRING SAFETY HELPERS
    // Guard against null fields in string concatenation (ANO-005 fix).
    // =========================================================================

    /**
     * Safely concatenates first and last name, using "[Unknown]" marker for nulls.
     */
    private String safeConcat(String firstName, String lastName) {
        String first = firstName != null ? firstName : UNKNOWN_MARKER;
        String last = lastName != null ? lastName : UNKNOWN_MARKER;
        return first + " " + last;
    }

    /**
     * Safely builds property address string, handling null components.
     */
    private String safePropertyAddress(LegacyLoanAccount acct) {
        String addr = acct.getPropertyAddress() != null ? acct.getPropertyAddress() : UNKNOWN_MARKER;
        String city = acct.getPropertyCity() != null ? acct.getPropertyCity() : "";
        String state = acct.getPropertyState() != null ? acct.getPropertyState() : "";
        String zip = acct.getPropertyZip() != null ? acct.getPropertyZip() : "";
        return addr + ", " + city + ", " + state + " " + zip;
    }
}
