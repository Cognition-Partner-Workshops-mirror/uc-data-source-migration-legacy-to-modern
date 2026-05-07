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

        // ANO-006: Validate required fields
        List<String> violations = validator.validateLoanAccountRequired(acct);
        if (!violations.isEmpty()) {
            log.warn("Loan {} has required field violations: {}", id, violations);
        }

        // ANO-003: Validate product reference
        if (product == null && acct.getProductCode() != null) {
            log.warn("Loan {} references unknown product code '{}'", id, acct.getProductCode());
        }

        // ANO-004: Validate status code
        validator.validateLoanStatus(acct.getStatusCode(), id);

        // ANO-009: Check delinquency-status consistency
        validator.validateDelinquencyStatusConsistency(acct);

        // ANO-010: Check LTV consistency
        validator.validateLtvConsistency(acct);

        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);
        String firstName = validator.safeString(acct.getBorrowerFirstName(), "Unknown");
        String lastName = validator.safeString(acct.getBorrowerLastName(), "Unknown");
        dto.setBorrowerName(firstName + " " + lastName);
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(validator.parseAmount(acct.getOriginalAmount(), id, "LN_ORIG_AMT"));
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), id, "LN_CURR_BAL"));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), id, "LN_INT_RT"));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), id, "LN_PMT_AMT"));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(validator.formatDateToIso(acct.getOriginationDate(), id, "LN_ORIG_DT"));
        String propAddr = validator.safeString(acct.getPropertyAddress(), "Unknown");
        String propCity = validator.safeString(acct.getPropertyCity(), "");
        String propState = validator.safeString(acct.getPropertyState(), "");
        String propZip = validator.safeString(acct.getPropertyZip(), "");
        dto.setPropertyAddress(propAddr + ", " + propCity + ", " + propState + " " + propZip);
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();

        // ANO-006: Validate required fields
        List<String> violations = validator.validateBorrowerRequired(borrower);
        if (!violations.isEmpty()) {
            log.warn("Borrower {} has required field violations: {}", id, violations);
        }

        // ANO-004: Validate borrower status
        validator.validateBorrowerStatus(borrower.getStatusCode(), id);

        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);
        String firstName = validator.safeString(borrower.getFirstName(), "Unknown");
        String lastName = validator.safeString(borrower.getLastName(), "Unknown");
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(firstName + middle + " " + lastName);
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

        // ANO-006: Validate required fields
        List<String> violations = validator.validatePaymentRequired(pmt);
        if (!violations.isEmpty()) {
            log.warn("Payment {} has required field violations: {}", id, violations);
        }

        // ANO-004: Validate status and type codes
        validator.validatePaymentStatus(pmt.getStatusCode(), id);
        validator.validatePaymentType(pmt.getTypeCode(), id);

        // ANO-008: Validate payment amount reconciliation
        validator.validatePaymentAmountReconciliation(pmt);

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(validator.formatDateToIso(pmt.getPaymentDate(), id, "PMT_DT"));
        dto.setTotalAmount(validator.parseAmount(pmt.getTotalAmount(), id, "PMT_AMT"));
        dto.setPrincipalAmount(validator.parseAmount(pmt.getPrincipalAmount(), id, "PMT_PRIN_AMT"));
        dto.setInterestAmount(validator.parseAmount(pmt.getInterestAmount(), id, "PMT_INT_AMT"));
        dto.setEscrowAmount(validator.parseAmount(pmt.getEscrowAmount(), id, "PMT_ESCROW_AMT"));
        dto.setLateFee(validator.parseAmount(pmt.getLateFee(), id, "PMT_LATE_FEE"));
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
