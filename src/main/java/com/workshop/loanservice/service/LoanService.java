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
import java.util.Objects;
import java.util.stream.Collectors;

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
                .map(acct -> safeToLoanSummary(acct, products.get(acct.getProductCode())))
                .filter(Objects::nonNull)
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
                .map(this::safeToBorrowerDto)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
        BorrowerDto dto = toBorrowerDto(borrower);

        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> safeToLoanSummary(acct, products.get(acct.getProductCode())))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(this::safeToPaymentDto)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    // =========================================================================
    // SAFE WRAPPERS — isolate per-record failures so one bad record
    // does not crash the entire list endpoint.
    // =========================================================================

    private LoanSummaryDto safeToLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        try {
            return toLoanSummary(acct, product);
        } catch (Exception e) {
            log.error("Failed to map loan account {}: {}", acct.getLoanAccountNumber(), e.getMessage());
            return null;
        }
    }

    private BorrowerDto safeToBorrowerDto(LegacyBorrower borrower) {
        try {
            return toBorrowerDto(borrower);
        } catch (Exception e) {
            log.error("Failed to map borrower {}: {}", borrower.getBorrowerId(), e.getMessage());
            return null;
        }
    }

    private PaymentDto safeToPaymentDto(LegacyPayment pmt) {
        try {
            return toPaymentDto(pmt);
        } catch (Exception e) {
            log.error("Failed to map payment {}: {}", pmt.getPaymentSequenceNumber(), e.getMessage());
            return null;
        }
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String id = acct.getLoanAccountNumber();

        validator.validateLoanStatus(acct.getStatusCode(), acct.getDelinquencyDays(), id);
        validator.validatePropertyType(acct.getPropertyType(), id);

        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);
        dto.setBorrowerName(validator.buildSafeName(acct.getBorrowerFirstName(), acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(validator.parseAmount(acct.getOriginalAmount(), "LN_ORIG_AMT", id));
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), "LN_CURR_BAL", id));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), "LN_INT_RT", id));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), "LN_PMT_AMT", id));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(validator.formatLegacyDate(acct.getOriginationDate(), "LN_ORIG_DT", id));
        dto.setPropertyAddress(validator.buildSafeAddress(
                acct.getPropertyAddress(), acct.getPropertyCity(),
                acct.getPropertyState(), acct.getPropertyZip()));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();

        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);
        dto.setFullName(validator.buildSafeFullName(
                borrower.getFirstName(), borrower.getMiddleInitial(), borrower.getLastName()));
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(validator.parseInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", id));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String id = pmt.getPaymentSequenceNumber();

        validator.validatePaymentType(pmt.getTypeCode(), id);
        validator.validatePaymentStatus(pmt.getStatusCode(), id);

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(validator.formatLegacyDate(pmt.getPaymentDate(), "PMT_DT", id));
        BigDecimal total = validator.parseAmount(pmt.getTotalAmount(), "PMT_AMT", id);
        BigDecimal principal = validator.parseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id);
        BigDecimal interest = validator.parseAmount(pmt.getInterestAmount(), "PMT_INT_AMT", id);
        BigDecimal escrow = validator.parseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id);
        BigDecimal lateFee = validator.parseAmount(pmt.getLateFee(), "PMT_LATE_FEE", id);

        validator.validatePaymentComponents(id, total, principal, interest, escrow, lateFee);

        dto.setTotalAmount(total);
        dto.setPrincipalAmount(principal);
        dto.setInterestAmount(interest);
        dto.setEscrowAmount(escrow);
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
