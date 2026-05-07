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
import java.util.Set;
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
    // Injected validator for catching data quality anomalies during legacy data translation
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

        // Build lookup sets for referential integrity validation against orphaned records
        Set<String> validBorrowerIds = borrowerRepository.findAll().stream()
                .map(LegacyBorrower::getBorrowerId)
                .collect(Collectors.toSet());
        Set<String> validProductCodes = products.keySet();

        return loanAccountRepository.findAll().stream()
                .peek(acct -> {
                    validator.validateForeignKey(acct.getBorrowerId(), validBorrowerIds,
                            "BORR_ID", acct.getLoanAccountNumber());
                    validator.validateForeignKey(acct.getProductCode(), validProductCodes,
                            "PROD_CD", acct.getLoanAccountNumber());
                })
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
        dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        // Use validator to safely parse comma-formatted amount strings to BigDecimal
        dto.setOriginalAmount(validator.parseAmountWithDefault(
                acct.getOriginalAmount(), "originalAmount", id, BigDecimal.ZERO));
        dto.setCurrentBalance(validator.parseAmountWithDefault(
                acct.getCurrentBalance(), "currentBalance", id, BigDecimal.ZERO));
        dto.setInterestRate(validator.validateInterestRate(acct.getInterestRate(), id));
        dto.setMonthlyPayment(validator.parseAmountWithDefault(
                acct.getMonthlyPayment(), "monthlyPayment", id, BigDecimal.ZERO));
        validator.validateLoanStatus(acct.getStatusCode(), id);
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(acct.getOriginationDate());
        validator.parseDate(acct.getOriginationDate(), "originationDate", id);
        validator.validatePropertyType(acct.getPropertyType(), id);
        dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
                + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();
        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
        dto.setEmail(validator.validateRequired(borrower.getEmail(), "email", id));
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(validator.validateCreditScore(borrower.getCreditScore(), id));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        validator.validateBorrowerStatus(borrower.getStatusCode(), id);
        validator.parseDate(borrower.getDateOfBirth(), "dateOfBirth", id);
        validator.parseAmount(borrower.getAnnualIncome(), "annualIncome", id);
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String id = pmt.getPaymentSequenceNumber();
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate());
        validator.parseDate(pmt.getPaymentDate(), "paymentDate", id);

        // Parse all payment amount components for reconciliation check
        BigDecimal total = validator.parseAmountWithDefault(
                pmt.getTotalAmount(), "totalAmount", id, BigDecimal.ZERO);
        BigDecimal principal = validator.parseAmountWithDefault(
                pmt.getPrincipalAmount(), "principalAmount", id, BigDecimal.ZERO);
        BigDecimal interest = validator.parseAmountWithDefault(
                pmt.getInterestAmount(), "interestAmount", id, BigDecimal.ZERO);
        BigDecimal escrow = validator.parseAmountWithDefault(
                pmt.getEscrowAmount(), "escrowAmount", id, BigDecimal.ZERO);
        BigDecimal lateFee = validator.parseAmountWithDefault(
                pmt.getLateFee(), "lateFee", id, BigDecimal.ZERO);

        dto.setTotalAmount(total);
        dto.setPrincipalAmount(principal);
        dto.setInterestAmount(interest);
        dto.setEscrowAmount(escrow);
        dto.setLateFee(lateFee);

        // Verify payment component sum matches total (catches ANM-010 reconciliation mismatches)
        validator.validatePaymentReconciliation(id, total, principal, interest, escrow, lateFee);
        validator.validatePaymentType(pmt.getTypeCode(), id);
        validator.validatePaymentStatus(pmt.getStatusCode(), id);

        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    /**
     * Parse legacy amount strings like "285,000" or "1,487.02" into BigDecimal.
     */
    private BigDecimal parseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        return new BigDecimal(amount.replace(",", ""));
    }

    private BigDecimal parseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        return new BigDecimal(value.trim());
    }

    private Integer parseLegacyInteger(String value) {
        if (value == null || value.isBlank()) return null;
        return Integer.parseInt(value.trim());
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
