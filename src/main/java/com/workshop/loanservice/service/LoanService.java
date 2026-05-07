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
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Service layer that reads from legacy CDW tables and translates
 * cryptic legacy fields into clean DTOs.
 * Validation is performed at ingestion time via LegacyDataValidator
 * to catch known data quality anomalies (see docs/DATA_ANOMALY_REPORT.md).
 */
@Service
public class LoanService {

    private static final Logger log = LoggerFactory.getLogger(LoanService.class);

    private final LegacyBorrowerRepository borrowerRepository;
    private final LegacyLoanAccountRepository loanAccountRepository;
    private final LegacyLoanProductRepository loanProductRepository;
    private final LegacyPaymentRepository paymentRepository;
    // Injected validator catches anomalies and logs warnings without aborting the response
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

        // Load borrowers for cross-referencing during loan validation (ANO-001 SSN check)
        Map<String, LegacyBorrower> borrowers = borrowerRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyBorrower::getBorrowerId, b -> b));

        return loanAccountRepository.findAll().stream()
                .map(acct -> {
                    LegacyBorrower borrower = borrowers.get(acct.getBorrowerId());
                    validator.validateLoanAccount(acct, borrower);
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        LegacyBorrower borrower = borrowerRepository.findById(acct.getBorrowerId()).orElse(null);
        validator.validateLoanAccount(acct, borrower);
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .map(b -> {
                    validator.validateBorrower(b);
                    return toBorrowerDto(b);
                })
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
        validator.validateBorrower(borrower);
        BorrowerDto dto = toBorrowerDto(borrower);

        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> {
                    validator.validateLoanAccount(acct, borrower);
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
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
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());
        // ANO-006 fix: null-safe concatenation prevents literal "null" in API output
        dto.setBorrowerName(
                validator.safeString(acct.getBorrowerFirstName(), "")
                + " "
                + validator.safeString(acct.getBorrowerLastName(), ""));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
        dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
        dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
        dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(acct.getOriginationDate());
        // ANO-006 fix: null-safe property address assembly
        dto.setPropertyAddress(
                validator.safeString(acct.getPropertyAddress(), "")
                + ", " + validator.safeString(acct.getPropertyCity(), "")
                + ", " + validator.safeString(acct.getPropertyState(), "")
                + " " + validator.safeString(acct.getPropertyZip(), ""));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        // ANO-006 fix: null-safe name concatenation
        dto.setFullName(
                validator.safeString(borrower.getFirstName(), "")
                + middle + " "
                + validator.safeString(borrower.getLastName(), ""));
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate());
        dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
        dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
        dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
        dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
        dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    // ANO-003 fix: delegate to validator's safe-parse methods that catch NumberFormatException
    // instead of the original raw BigDecimal/Integer.parseInt calls that threw on bad data

    private BigDecimal parseLegacyAmount(String amount) {
        BigDecimal result = validator.safeParseAmount(amount);
        return result != null ? result : BigDecimal.ZERO;
    }

    private BigDecimal parseLegacyDecimal(String value) {
        BigDecimal result = validator.safeParseDecimal(value);
        return result != null ? result : BigDecimal.ZERO;
    }

    private Integer parseLegacyInteger(String value) {
        return validator.safeParseInteger(value);
    }

    private String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            // ANO-010: log unknown codes instead of silently passing through
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
