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
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Service layer that reads from legacy tables and translates
 * cryptic legacy fields into clean DTOs.
 *
 * Uses LegacyDataValidator to safely handle all known data quality
 * anomalies in the CDW tables (see docs/DATA_ANOMALY_REPORT.md).
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
                .sorted(Comparator.comparing(
                        PaymentDto::getPaymentDate,
                        Comparator.nullsLast(Comparator.reverseOrder())))
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS — with validation
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String id = acct.getLoanAccountNumber();
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);
        dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());

        if (product != null) {
            dto.setProductDescription(product.getDescription());
        } else {
            log.warn("Loan {} references unknown product code '{}'", id, acct.getProductCode());
            dto.setProductDescription(acct.getProductCode());
        }

        BigDecimal originalAmount = validator.parseAmount(acct.getOriginalAmount(), "originalAmount", id);
        BigDecimal appraisedValue = validator.parseAmount(acct.getAppraisedValue(), "appraisedValue", id);
        BigDecimal ltvPct = validator.parseDecimal(acct.getLtvPercent(), "ltvPercent", id);

        dto.setOriginalAmount(originalAmount);
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), "currentBalance", id));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), "interestRate", id));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), "monthlyPayment", id));

        validator.validateLoanStatus(acct.getStatusCode(), id);
        dto.setStatus(expandStatusCode(acct.getStatusCode()));

        dto.setOriginationDate(validator.parseAndFormatDate(acct.getOriginationDate(), "originationDate", id));

        validator.validatePropertyType(acct.getPropertyType(), id);
        dto.setPropertyAddress(validator.buildAddress(
                acct.getPropertyAddress(), acct.getPropertyCity(),
                acct.getPropertyState(), acct.getPropertyZip()));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        Integer dlqDays = validator.parseInteger(acct.getDelinquencyDays(), "delinquencyDays", id);
        validator.validateDelinquencyConsistency(id, acct.getStatusCode(), dlqDays);
        validator.validateLtv(id, ltvPct, originalAmount, appraisedValue);

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();
        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
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
        dto.setPaymentDate(validator.parseAndFormatDate(pmt.getPaymentDate(), "paymentDate", id));

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

        validator.validatePaymentBalance(id, total, principal, interest, escrow, lateFee);

        validator.validatePaymentType(pmt.getTypeCode(), id);
        validator.validatePaymentStatus(pmt.getStatusCode(), id);
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
