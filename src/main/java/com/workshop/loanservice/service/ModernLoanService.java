package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.entity.Borrower;
import com.workshop.loanservice.entity.LoanAccount;
import com.workshop.loanservice.entity.Payment;
import com.workshop.loanservice.repository.BorrowerRepository;
import com.workshop.loanservice.repository.LoanAccountRepository;
import com.workshop.loanservice.repository.PaymentRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

/**
 * Service layer that reads from the modern normalized tables.
 * No string parsing needed — modern entities already have proper Java types.
 * This replaces the legacy translation logic in LoanService.
 */
@Service
public class ModernLoanService {

    private final BorrowerRepository borrowerRepo;
    private final LoanAccountRepository accountRepo;
    private final PaymentRepository paymentRepo;

    public ModernLoanService(BorrowerRepository borrowerRepo,
                             LoanAccountRepository accountRepo,
                             PaymentRepository paymentRepo) {
        this.borrowerRepo = borrowerRepo;
        this.accountRepo = accountRepo;
        this.paymentRepo = paymentRepo;
    }

    @Transactional(readOnly = true)
    public List<LoanSummaryDto> getAllLoans() {
        return accountRepo.findAll().stream()
                .map(this::toLoanSummary)
                .collect(Collectors.toList());
    }

    @Transactional(readOnly = true)
    public LoanSummaryDto getLoanById(String accountNumber) {
        LoanAccount acct = accountRepo.findByAccountNumber(accountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + accountNumber));
        return toLoanSummary(acct);
    }

    @Transactional(readOnly = true)
    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepo.findAll().stream()
                .map(this::toBorrowerDto)
                .collect(Collectors.toList());
    }

    @Transactional(readOnly = true)
    public BorrowerDto getBorrowerById(String externalId) {
        Borrower borrower = borrowerRepo.findByExternalId(externalId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + externalId));
        BorrowerDto dto = toBorrowerDto(borrower);

        // Attach loans for this borrower using FK relationship
        List<LoanSummaryDto> loans = accountRepo.findByBorrowerExternalId(externalId)
                .stream()
                .map(this::toLoanSummary)
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    @Transactional(readOnly = true)
    public List<PaymentDto> getPaymentsByLoan(String accountNumber) {
        return paymentRepo.findByLoanAccountAccountNumberOrderByPaymentDateDesc(accountNumber)
                .stream()
                .map(this::toPaymentDto)
                .collect(Collectors.toList());
    }

    // =========================================================================
    // MODERN MAPPING METHODS
    // No string parsing needed — values are already properly typed.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LoanAccount acct) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getAccountNumber());
        // Borrower name from FK relationship (no more denormalized fields)
        Borrower borrower = acct.getBorrower();
        dto.setBorrowerName(borrower.getFirstName() + " " + borrower.getLastName());
        dto.setProductDescription(acct.getProduct().getName());
        // Amounts are already BigDecimal — no parsing needed
        dto.setOriginalAmount(acct.getOriginalAmount());
        dto.setCurrentBalance(acct.getCurrentBalance());
        dto.setInterestRate(acct.getInterestRate());
        dto.setMonthlyPayment(acct.getMonthlyPayment());
        // Status is already expanded (ACTIVE, not ACT)
        dto.setStatus(expandModernStatus(acct.getStatus()));
        dto.setOriginationDate(acct.getOriginationDate().toString());
        dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
                + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
        dto.setPropertyType(expandModernPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(Borrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getExternalId());
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhone());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getState());
        // Credit score is already Integer — no parsing
        dto.setCreditScore(borrower.getCreditScore());
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(Payment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(String.valueOf(pmt.getId()));
        dto.setLoanAccountNumber(pmt.getLoanAccount().getAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate().toString());
        // Amounts are already BigDecimal — no parsing
        dto.setTotalAmount(pmt.getTotalAmount());
        dto.setPrincipalAmount(pmt.getPrincipalAmount());
        dto.setInterestAmount(pmt.getInterestAmount());
        dto.setEscrowAmount(pmt.getEscrowAmount());
        dto.setLateFee(pmt.getLateFee());
        // Type and status are already expanded
        dto.setType(expandModernPaymentType(pmt.getType()));
        dto.setStatus(expandModernPaymentStatus(pmt.getStatus()));
        return dto;
    }

    /**
     * Map modern status values to the same display strings as legacy service.
     * Modern stores ACTIVE; legacy service displayed "Active".
     */
    private String expandModernStatus(String status) {
        if (status == null) return "Unknown";
        return switch (status) {
            case "ACTIVE" -> "Active";
            case "CLOSED" -> "Closed";
            case "DEFAULT" -> "Default";
            case "FORBEARANCE" -> "Forbearance";
            default -> status;
        };
    }

    /**
     * Map modern property type values to the same display strings as legacy service.
     * Modern stores "Single Family"; legacy service displayed "Single Family Residence".
     */
    private String expandModernPropertyType(String type) {
        if (type == null) return "Unknown";
        return switch (type) {
            case "Single Family" -> "Single Family Residence";
            case "Condominium" -> "Condominium";
            case "Multi-Family" -> "Multi-Family Residence";
            case "Townhouse" -> "Townhouse";
            default -> type;
        };
    }

    /** Map modern payment type to the same display strings as legacy service. */
    private String expandModernPaymentType(String type) {
        if (type == null) return "Unknown";
        return switch (type) {
            case "REGULAR" -> "Regular";
            case "EXTRA" -> "Extra";
            case "PARTIAL" -> "Partial";
            case "PREPAYMENT" -> "Prepayment";
            default -> type;
        };
    }

    /** Map modern payment status to the same display strings as legacy service. */
    private String expandModernPaymentStatus(String status) {
        if (status == null) return "Unknown";
        return switch (status) {
            case "POSTED" -> "Posted";
            case "REVERSED" -> "Reversed";
            case "NSF" -> "Non-Sufficient Funds";
            case "PENDING" -> "Pending";
            default -> status;
        };
    }
}
