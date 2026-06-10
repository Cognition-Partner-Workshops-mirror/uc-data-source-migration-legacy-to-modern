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

import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.stream.Collectors;

/**
 * Service layer that reads from the modern normalized schema.
 * Translates modern typed entities into the same DTO contract
 * previously served by the legacy data source, preserving the
 * REST API response format.
 *
 * REFACTORED: Now uses modern JPA entities (Borrower, LoanAccount, Payment)
 * with proper types. No more string parsing — the database stores proper
 * DATE, DECIMAL, and INTEGER types. Status codes and property types are
 * already expanded in the modern schema.
 */
@Service
public class LoanService {

    // Date format used in API responses to maintain backward compatibility
    private static final DateTimeFormatter API_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private final BorrowerRepository borrowerRepository;
    private final LoanAccountRepository loanAccountRepository;
    private final PaymentRepository paymentRepository;

    public LoanService(BorrowerRepository borrowerRepository,
                       LoanAccountRepository loanAccountRepository,
                       PaymentRepository paymentRepository) {
        this.borrowerRepository = borrowerRepository;
        this.loanAccountRepository = loanAccountRepository;
        this.paymentRepository = paymentRepository;
    }

    public List<LoanSummaryDto> getAllLoans() {
        return loanAccountRepository.findAll().stream()
                .map(this::toLoanSummary)
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LoanAccount acct = loanAccountRepository.findByAccountNumber(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        return toLoanSummary(acct);
    }

    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .map(this::toBorrowerDto)
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        Borrower borrower = borrowerRepository.findByExternalId(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
        BorrowerDto dto = toBorrowerDto(borrower);

        // Attach loans for this borrower
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrower.getId())
                .stream()
                .map(this::toLoanSummary)
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        return paymentRepository.findByLoanAccountAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(this::toPaymentDto)
                .collect(Collectors.toList());
    }

    // =========================================================================
    // DTO MAPPING METHODS
    // With modern entities, no string parsing is needed — types are already
    // correct in the database. We only format dates for API compatibility.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LoanAccount acct) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getAccountNumber());

        // Borrower name from the FK relationship (replaces denormalized fields)
        Borrower borrower = acct.getBorrower();
        dto.setBorrowerName(borrower.getFirstName() + " " + borrower.getLastName());

        // Product description from FK relationship
        dto.setProductDescription(acct.getProduct().getName());

        // Amounts are already proper BigDecimal — no parsing needed
        dto.setOriginalAmount(acct.getOriginalAmount());
        dto.setCurrentBalance(acct.getCurrentBalance());
        dto.setInterestRate(acct.getInterestRate());
        dto.setMonthlyPayment(acct.getMonthlyPayment());

        // Status is already expanded in modern schema
        dto.setStatus(acct.getStatus());

        // Format date for API response (preserves existing MM/dd/yyyy contract)
        dto.setOriginationDate(acct.getOriginationDate() != null
                ? acct.getOriginationDate().format(API_DATE_FORMAT)
                : null);

        // Assemble property address (same format as legacy: "addr, city, state zip")
        dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
                + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());

        // Property type already expanded in modern schema
        dto.setPropertyType(acct.getPropertyType());

        return dto;
    }

    private BorrowerDto toBorrowerDto(Borrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getExternalId());

        // Build full name with middle initial (same format as legacy)
        String middle = borrower.getMiddleInitial() != null
                ? " " + borrower.getMiddleInitial() + "."
                : "";
        dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhone());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getState());

        // Credit score is already Integer — no parsing needed
        dto.setCreditScore(borrower.getCreditScore());
        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        return dto;
    }

    private PaymentDto toPaymentDto(Payment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(String.valueOf(pmt.getId()));
        dto.setLoanAccountNumber(pmt.getLoanAccount().getAccountNumber());

        // Format date for API response (preserves existing contract)
        dto.setPaymentDate(pmt.getPaymentDate() != null
                ? pmt.getPaymentDate().format(API_DATE_FORMAT)
                : null);

        // Amounts are already BigDecimal — no parsing needed
        dto.setTotalAmount(pmt.getTotalAmount());
        dto.setPrincipalAmount(pmt.getPrincipalAmount());
        dto.setInterestAmount(pmt.getInterestAmount());
        dto.setEscrowAmount(pmt.getEscrowAmount());
        dto.setLateFee(pmt.getLateFee());

        // Type and status already expanded in modern schema
        dto.setType(pmt.getType());
        dto.setStatus(pmt.getStatus());

        return dto;
    }
}
