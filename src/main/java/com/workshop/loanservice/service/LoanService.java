package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.entity.modern.Borrower;
import com.workshop.loanservice.entity.modern.LoanAccount;
import com.workshop.loanservice.entity.modern.Payment;
import com.workshop.loanservice.repository.modern.BorrowerRepository;
import com.workshop.loanservice.repository.modern.LoanAccountRepository;
import com.workshop.loanservice.repository.modern.PaymentRepository;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.Collectors;

/**
 * Service layer that reads from the modern normalized schema.
 * Replaces the legacy implementation that performed string-to-type
 * conversions at read time. Now entities already have proper types
 * (LocalDate, BigDecimal, Integer, enums) so no translation is needed.
 */
@Service
public class LoanService {

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

    /** Returns all loan summaries from the modern schema */
    public List<LoanSummaryDto> getAllLoans() {
        return loanAccountRepository.findAll().stream()
                .map(this::toLoanSummary)
                .collect(Collectors.toList());
    }

    /** Returns a single loan by account number */
    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LoanAccount acct = loanAccountRepository.findByAccountNumber(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        return toLoanSummary(acct);
    }

    /** Returns all borrowers from the modern schema */
    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .map(this::toBorrowerDto)
                .collect(Collectors.toList());
    }

    /** Returns a single borrower with attached loans by external ID */
    public BorrowerDto getBorrowerById(String borrowerId) {
        Borrower borrower = borrowerRepository.findByExternalId(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
        BorrowerDto dto = toBorrowerDto(borrower);

        // Attach loans for this borrower via FK relationship
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerExternalId(borrowerId)
                .stream()
                .map(this::toLoanSummary)
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    /** Returns payments for a loan account, ordered by date descending */
    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        return paymentRepository
                .findByLoanAccountAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(this::toPaymentDto)
                .collect(Collectors.toList());
    }

    // =========================================================================
    // DTO MAPPING METHODS
    // No more legacy string parsing needed — entities already have proper types.
    // =========================================================================

    /** Maps a modern LoanAccount entity to LoanSummaryDto */
    private LoanSummaryDto toLoanSummary(LoanAccount acct) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getAccountNumber());

        // Borrower name from normalized FK relationship
        Borrower borrower = acct.getBorrower();
        dto.setBorrowerName(borrower.getFirstName() + " " + borrower.getLastName());

        // Product description from FK relationship
        dto.setProductDescription(acct.getProduct().getName());

        // Numeric fields are already typed — no parsing needed
        dto.setOriginalAmount(acct.getOriginalAmount());
        dto.setCurrentBalance(acct.getCurrentBalance());
        dto.setInterestRate(acct.getInterestRate());
        dto.setMonthlyPayment(acct.getMonthlyPayment());

        // Status enum → display string
        dto.setStatus(formatStatus(acct.getStatus()));

        // Date already typed — format for API output
        dto.setOriginationDate(acct.getOriginationDate() != null
                ? acct.getOriginationDate().toString() : null);

        // Compose full property address
        dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
                + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());

        dto.setPropertyType(acct.getPropertyType());
        return dto;
    }

    /** Maps a modern Borrower entity to BorrowerDto */
    private BorrowerDto toBorrowerDto(Borrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getExternalId());

        // Build full name with optional middle initial
        String middle = borrower.getMiddleInitial() != null
                ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhone());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getState());
        dto.setCreditScore(borrower.getCreditScore());
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    /** Maps a modern Payment entity to PaymentDto */
    private PaymentDto toPaymentDto(Payment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(String.valueOf(pmt.getId()));
        dto.setLoanAccountNumber(pmt.getLoanAccount().getAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate() != null
                ? pmt.getPaymentDate().toString() : null);
        dto.setTotalAmount(pmt.getTotalAmount());
        dto.setPrincipalAmount(pmt.getPrincipalAmount());
        dto.setInterestAmount(pmt.getInterestAmount());
        dto.setEscrowAmount(pmt.getEscrowAmount());
        dto.setLateFee(pmt.getLateFee());
        dto.setType(formatPaymentType(pmt.getType()));
        dto.setStatus(formatPaymentStatus(pmt.getStatus()));
        return dto;
    }

    /** Formats loan account status enum to display string */
    private String formatStatus(LoanAccount.Status status) {
        if (status == null) return "Unknown";
        return switch (status) {
            case ACTIVE -> "Active";
            case CLOSED -> "Closed";
            case DEFAULT -> "Default";
            case FORBEARANCE -> "Forbearance";
        };
    }

    /** Formats payment type enum to display string */
    private String formatPaymentType(Payment.PaymentType type) {
        if (type == null) return "Unknown";
        return switch (type) {
            case REGULAR -> "Regular";
            case EXTRA -> "Extra";
            case PARTIAL -> "Partial";
            case PREPAYMENT -> "Prepayment";
        };
    }

    /** Formats payment status enum to display string */
    private String formatPaymentStatus(Payment.PaymentStatus status) {
        if (status == null) return "Unknown";
        return switch (status) {
            case POSTED -> "Posted";
            case REVERSED -> "Reversed";
            case NSF -> "Non-Sufficient Funds";
            case PENDING -> "Pending";
        };
    }
}
