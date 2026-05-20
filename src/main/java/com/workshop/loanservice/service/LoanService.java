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
 * Service layer that reads from legacy tables and translates
 * cryptic legacy fields into clean DTOs.
 *
 * MIGRATION TASK: This service contains all the translation logic
 * between legacy string-typed fields and proper Java types.
 * When switching data sources, this layer needs to be updated
 * (or replaced) to read from the modern schema.
 *
 * Data validation is performed at ingestion time via LegacyDataValidator
 * to catch known CDW quality issues (malformed amounts, invalid dates,
 * unrecognized status codes, payment component mismatches).
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

        return loanAccountRepository.findAll().stream()
                .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .map(this::toBorrowerDto)
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
        BorrowerDto dto = toBorrowerDto(borrower);

        // Attach loans for this borrower
        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(this::toPaymentDto)
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    // All parsing now uses LegacyDataValidator for safe error handling.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String loanId = acct.getLoanAccountNumber();

        // Validate FK reference to product
        if (product == null && acct.getProductCode() != null) {
            log.warn("Loan [{}] references non-existent product code '{}'",
                    loanId, acct.getProductCode());
        }

        // Validate loan status code
        validator.isValidLoanStatus(acct.getStatusCode(), loanId);

        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(loanId);
        dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(validator.parseAmount(acct.getOriginalAmount(), "originalAmount:" + loanId));
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), "currentBalance:" + loanId));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), "interestRate:" + loanId));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), "monthlyPayment:" + loanId));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));

        // Parse origination date to ISO-8601 format
        dto.setOriginationDate(validator.parseDateToIso(acct.getOriginationDate(), "originationDate:" + loanId));

        // Safe address concatenation (avoids literal "null" in output)
        dto.setPropertyAddress(validator.formatAddress(
                acct.getPropertyAddress(), acct.getPropertyCity(),
                acct.getPropertyState(), acct.getPropertyZip()));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String borrowerId = borrower.getBorrowerId();

        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrowerId);
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        // Safe credit score parsing with FICO range validation
        dto.setCreditScore(validator.parseCreditScore(borrower.getCreditScore(), borrowerId));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String pmtId = pmt.getPaymentSequenceNumber();

        // Validate payment status and type codes
        validator.isValidPaymentStatus(pmt.getStatusCode(), pmtId);
        validator.isValidPaymentType(pmt.getTypeCode(), pmtId);

        // Validate FK reference to loan account
        validator.isValidReference(pmt.getLoanAccountNumber(), "loanAccountNumber:" + pmtId);

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmtId);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());

        // Parse payment date to ISO-8601 format
        dto.setPaymentDate(validator.parseDateToIso(pmt.getPaymentDate(), "paymentDate:" + pmtId));

        // Parse all monetary amounts with safe error handling
        BigDecimal totalAmount = validator.parseAmount(pmt.getTotalAmount(), "totalAmount:" + pmtId);
        BigDecimal principalAmount = validator.parseAmount(pmt.getPrincipalAmount(), "principalAmount:" + pmtId);
        BigDecimal interestAmount = validator.parseAmount(pmt.getInterestAmount(), "interestAmount:" + pmtId);
        BigDecimal escrowAmount = validator.parseAmount(pmt.getEscrowAmount(), "escrowAmount:" + pmtId);
        BigDecimal lateFee = validator.parseAmount(pmt.getLateFee(), "lateFee:" + pmtId);

        // Cross-field validation: check that payment components sum correctly
        validator.validatePaymentComponents(pmtId, totalAmount, principalAmount,
                interestAmount, escrowAmount, lateFee);

        dto.setTotalAmount(totalAmount);
        dto.setPrincipalAmount(principalAmount);
        dto.setInterestAmount(interestAmount);
        dto.setEscrowAmount(escrowAmount);
        dto.setLateFee(lateFee);
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

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
}
