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
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String id = acct.getLoanAccountNumber();
        List<String> warnings = validator.validateLoanAccount(acct);
        if (!warnings.isEmpty()) {
            log.warn("[{}] Loan validation warnings: {}", id, warnings);
        }

        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);
        String firstName = acct.getBorrowerFirstName() != null ? acct.getBorrowerFirstName() : "";
        String lastName = acct.getBorrowerLastName() != null ? acct.getBorrowerLastName() : "";
        dto.setBorrowerName((firstName + " " + lastName).trim());
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(validator.parseAndValidateAmount(acct.getOriginalAmount(), "originalAmount", id));
        dto.setCurrentBalance(validator.parseAndValidateAmount(acct.getCurrentBalance(), "currentBalance", id));
        dto.setInterestRate(validator.parseAndValidateDecimal(acct.getInterestRate(), "interestRate", id));
        dto.setMonthlyPayment(validator.parseAndValidateAmount(acct.getMonthlyPayment(), "monthlyPayment", id));
        dto.setStatus(expandStatusCode(
                validator.validateStatusCode(acct.getStatusCode(), validator.getValidLoanStatuses(), "loanStatus", id)));
        String validatedDate = validator.parseAndValidateDate(acct.getOriginationDate(), "originationDate", id);
        dto.setOriginationDate(validatedDate != null ? validatedDate : acct.getOriginationDate());
        String addr = safeJoin(acct.getPropertyAddress(), acct.getPropertyCity(),
                acct.getPropertyState(), acct.getPropertyZip());
        dto.setPropertyAddress(addr);
        dto.setPropertyType(expandPropertyType(
                validator.validateStatusCode(acct.getPropertyType(), validator.getValidPropertyTypes(), "propertyType", id)));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();
        List<String> warnings = validator.validateBorrower(borrower);
        if (!warnings.isEmpty()) {
            log.warn("[{}] Borrower validation warnings: {}", id, warnings);
        }

        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);
        String first = borrower.getFirstName() != null ? borrower.getFirstName() : "";
        String last = borrower.getLastName() != null ? borrower.getLastName() : "";
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName((first + middle + " " + last).trim());
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(validator.validateCreditScore(borrower.getCreditScore(), id));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String id = pmt.getPaymentSequenceNumber();
        List<String> warnings = validator.validatePayment(pmt);
        if (!warnings.isEmpty()) {
            log.warn("[{}] Payment validation warnings: {}", id, warnings);
        }

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        String validatedDate = validator.parseAndValidateDate(pmt.getPaymentDate(), "paymentDate", id);
        dto.setPaymentDate(validatedDate != null ? validatedDate : pmt.getPaymentDate());
        dto.setTotalAmount(validator.parseAndValidateAmount(pmt.getTotalAmount(), "totalAmount", id));
        dto.setPrincipalAmount(validator.parseAndValidateAmount(pmt.getPrincipalAmount(), "principalAmount", id));
        dto.setInterestAmount(validator.parseAndValidateAmount(pmt.getInterestAmount(), "interestAmount", id));
        dto.setEscrowAmount(validator.parseAndValidateAmount(pmt.getEscrowAmount(), "escrowAmount", id));
        dto.setLateFee(validator.parseAndValidateAmount(pmt.getLateFee(), "lateFee", id));
        dto.setType(expandPaymentType(
                validator.validateStatusCode(pmt.getTypeCode(), validator.getValidPaymentTypes(), "paymentType", id)));
        dto.setStatus(expandPaymentStatus(
                validator.validateStatusCode(pmt.getStatusCode(), validator.getValidPaymentStatuses(), "paymentStatus", id)));
        return dto;
    }

    private String safeJoin(String address, String city, String state, String zip) {
        StringBuilder sb = new StringBuilder();
        sb.append(address != null ? address : "Unknown");
        sb.append(", ");
        sb.append(city != null ? city : "Unknown");
        sb.append(", ");
        sb.append(state != null ? state : "??");
        sb.append(" ");
        sb.append(zip != null ? zip : "00000");
        return sb.toString();
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
