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
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String id = acct.getLoanAccountNumber();
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);

        String firstName = validator.validateRequiredField(
                acct.getBorrowerFirstName(), "borrowerFirstName", id, "Unknown");
        String lastName = validator.validateRequiredField(
                acct.getBorrowerLastName(), "borrowerLastName", id, "Unknown");
        dto.setBorrowerName(firstName + " " + lastName);

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(validator.parseAmount(acct.getOriginalAmount(), "originalAmount", id));
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), "currentBalance", id));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), "interestRate", id));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), "monthlyPayment", id));

        validator.validateLoanStatusCode(acct.getStatusCode(), id);
        dto.setStatus(expandStatusCode(acct.getStatusCode()));

        dto.setOriginationDate(validator.parseLegacyDate(acct.getOriginationDate(), "originationDate", id));

        String propAddr = validator.validateRequiredField(acct.getPropertyAddress(), "propertyAddress", id, "N/A");
        String propCity = validator.validateRequiredField(acct.getPropertyCity(), "propertyCity", id, "N/A");
        String propState = validator.validateRequiredField(acct.getPropertyState(), "propertyState", id, "N/A");
        String propZip = validator.validateRequiredField(acct.getPropertyZip(), "propertyZip", id, "N/A");
        dto.setPropertyAddress(propAddr + ", " + propCity + ", " + propState + " " + propZip);

        validator.validatePropertyTypeCode(acct.getPropertyType(), id);
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        validator.validateDelinquencyConsistency(acct.getDelinquencyDays(), acct.getStatusCode(), id);
        validator.validateLtvConsistency(acct.getLtvPercent(), acct.getCurrentBalance(),
                acct.getAppraisedValue(), id);

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();
        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);

        String firstName = validator.validateRequiredField(borrower.getFirstName(), "firstName", id, "Unknown");
        String lastName = validator.validateRequiredField(borrower.getLastName(), "lastName", id, "Unknown");
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(firstName + middle + " " + lastName);

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(validator.parseCreditScore(borrower.getCreditScore(), id));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String id = pmt.getPaymentSequenceNumber();
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(validator.parseLegacyDate(pmt.getPaymentDate(), "paymentDate", id));

        BigDecimal total = validator.parseAmount(pmt.getTotalAmount(), "totalAmount", id);
        BigDecimal principal = validator.parseAmount(pmt.getPrincipalAmount(), "principalAmount", id);
        BigDecimal interest = validator.parseAmount(pmt.getInterestAmount(), "interestAmount", id);
        BigDecimal escrow = validator.parseAmount(pmt.getEscrowAmount(), "escrowAmount", id);
        BigDecimal lateFee = validator.parseAmount(pmt.getLateFee(), "lateFee", id);

        dto.setTotalAmount(total);
        dto.setPrincipalAmount(principal);
        dto.setInterestAmount(interest);
        dto.setEscrowAmount(escrow);
        dto.setLateFee(lateFee);

        validator.validatePaymentReconciliation(total, principal, interest, escrow, lateFee, id);

        validator.validatePaymentTypeCode(pmt.getTypeCode(), id);
        dto.setType(expandPaymentType(pmt.getTypeCode()));

        validator.validatePaymentStatusCode(pmt.getStatusCode(), id);
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
