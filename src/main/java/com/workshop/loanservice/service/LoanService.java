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
    // LEGACY TRANSLATION METHODS (with validation)
    // These methods handle the messy conversion from legacy string fields
    // to proper types with data quality validation at ingestion time.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String recordId = acct.getLoanAccountNumber();
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(recordId);

        String firstName = validator.requireNonBlank(
                acct.getBorrowerFirstName(), "BORR_FST_NM", recordId, "Unknown");
        String lastName = validator.requireNonBlank(
                acct.getBorrowerLastName(), "BORR_LST_NM", recordId, "Unknown");
        dto.setBorrowerName(firstName + " " + lastName);

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());

        validator.validateForeignKeyReference(acct.getBorrowerId(), "BORR_ID", recordId);
        validator.validateForeignKeyReference(acct.getProductCode(), "PROD_CD", recordId);

        dto.setOriginalAmount(validator.parseAmount(acct.getOriginalAmount(), "LN_ORIG_AMT", recordId));
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), "LN_CURR_BAL", recordId));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), "LN_INT_RT", recordId));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), "LN_PMT_AMT", recordId));

        String statusCode = validator.validateLoanStatus(acct.getStatusCode(), recordId);
        dto.setStatus(expandStatusCode(statusCode));

        String originationDate = validator.parseDate(acct.getOriginationDate(), "LN_ORIG_DT", recordId);
        dto.setOriginationDate(originationDate != null ? originationDate : acct.getOriginationDate());

        String propAddr = acct.getPropertyAddress() != null ? acct.getPropertyAddress() : "";
        String propCity = acct.getPropertyCity() != null ? acct.getPropertyCity() : "";
        String propState = acct.getPropertyState() != null ? acct.getPropertyState() : "";
        String propZip = acct.getPropertyZip() != null ? acct.getPropertyZip() : "";
        dto.setPropertyAddress(propAddr + ", " + propCity + ", " + propState + " " + propZip);

        String propertyTypeCode = validator.validatePropertyType(acct.getPropertyType(), recordId);
        dto.setPropertyType(expandPropertyType(propertyTypeCode));

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String recordId = borrower.getBorrowerId();
        BorrowerDto dto = new BorrowerDto();
        dto.setId(recordId);

        String firstName = validator.requireNonBlank(
                borrower.getFirstName(), "BORR_FST_NM", recordId, "Unknown");
        String lastName = validator.requireNonBlank(
                borrower.getLastName(), "BORR_LST_NM", recordId, "Unknown");
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(firstName + middle + " " + lastName);

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(validator.parseInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", recordId));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String recordId = pmt.getPaymentSequenceNumber();
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(recordId);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());

        validator.validateForeignKeyReference(pmt.getLoanAccountNumber(), "LN_ACCT_NBR", recordId);

        String paymentDate = validator.parseDate(pmt.getPaymentDate(), "PMT_DT", recordId);
        dto.setPaymentDate(paymentDate != null ? paymentDate : pmt.getPaymentDate());

        BigDecimal totalAmount = validator.parseAmount(pmt.getTotalAmount(), "PMT_AMT", recordId);
        BigDecimal principalAmount = validator.parseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", recordId);
        BigDecimal interestAmount = validator.parseAmount(pmt.getInterestAmount(), "PMT_INT_AMT", recordId);
        BigDecimal escrowAmount = validator.parseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", recordId);
        BigDecimal lateFee = validator.parseAmount(pmt.getLateFee(), "PMT_LATE_FEE", recordId);

        dto.setTotalAmount(totalAmount);
        dto.setPrincipalAmount(principalAmount);
        dto.setInterestAmount(interestAmount);
        dto.setEscrowAmount(escrowAmount);
        dto.setLateFee(lateFee);

        validator.validatePaymentConsistency(totalAmount, principalAmount, interestAmount,
                escrowAmount, lateFee, recordId);

        String typeCode = validator.validatePaymentType(pmt.getTypeCode(), recordId);
        dto.setType(expandPaymentType(typeCode));

        String statusCode = validator.validatePaymentStatus(pmt.getStatusCode(), recordId);
        dto.setStatus(expandPaymentStatus(statusCode));

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
