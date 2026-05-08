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
 * Data validation is delegated to LegacyDataValidator, which catches
 * anomalies at ingestion time (see docs/DATA_ANOMALY_REPORT.md).
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
    // These methods use LegacyDataValidator for safe type coercion with error
    // handling and anomaly detection. After migration, these should be simplified
    // or removed.
    // =========================================================================

    /**
     * Convert a legacy loan account to a DTO with validated/sanitized fields.
     * Uses validator for safe parsing (ANO-002), delinquency-aware status (ANO-003),
     * null-safe name building (ANO-004), and date parsing (ANO-007).
     */
    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String id = acct.getLoanAccountNumber();
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);
        // ANO-004: Null-safe borrower name from denormalized fields
        dto.setBorrowerName(validator.safeBuildBorrowerName(
                acct.getBorrowerFirstName(), acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        // ANO-002: Safe numeric parsing with fallback to ZERO on malformed data
        dto.setOriginalAmount(validator.safeParseLegacyAmount(acct.getOriginalAmount(), id, "LN_ORIG_AMT"));
        dto.setCurrentBalance(validator.safeParseLegacyAmount(acct.getCurrentBalance(), id, "LN_CURR_BAL"));
        dto.setInterestRate(validator.safeParseLegacyDecimal(acct.getInterestRate(), id, "LN_INT_RT"));
        dto.setMonthlyPayment(validator.safeParseLegacyAmount(acct.getMonthlyPayment(), id, "LN_PMT_AMT"));
        // ANO-003: Status expansion with delinquency cross-check
        dto.setStatus(validator.expandLoanStatusWithDelinquencyCheck(
                acct.getStatusCode(), acct.getDelinquencyDays(), id));
        // ANO-007: Parse legacy MM/DD/YYYY date to ISO-8601
        dto.setOriginationDate(validator.safeParseLegacyDate(acct.getOriginationDate(), id, "LN_ORIG_DT"));
        dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
                + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
        dto.setPropertyType(validator.expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    /**
     * Convert a legacy borrower to a DTO with validated/sanitized fields.
     * Uses validator for null-safe name building (ANO-004), safe integer parsing
     * for credit score (ANO-002/ANO-009).
     */
    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();
        // Run validation checks and log any anomalies found
        List<String> warnings = validator.validateBorrower(borrower);
        if (!warnings.isEmpty()) {
            log.warn("Borrower {} has {} data anomalies: {}", id, warnings.size(), warnings);
        }

        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);
        // ANO-004: Null-safe full name construction
        dto.setFullName(validator.safeBuildFullName(
                borrower.getFirstName(), borrower.getMiddleInitial(), borrower.getLastName()));
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        // ANO-002/ANO-009: Safe integer parsing for credit score
        dto.setCreditScore(validator.safeParseLegacyInteger(
                borrower.getCreditScore(), id, "BORR_CRDT_SCR"));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    /**
     * Convert a legacy payment to a DTO with validated/sanitized fields.
     * Uses validator for safe amount parsing (ANO-002), date parsing (ANO-007),
     * and logs payment component mismatches (ANO-001).
     */
    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String id = pmt.getPaymentSequenceNumber();
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        // ANO-007: Parse legacy MM/DD/YYYY date to ISO-8601
        dto.setPaymentDate(validator.safeParseLegacyDate(pmt.getPaymentDate(), id, "PMT_DT"));
        // ANO-002: Safe amount parsing with fallback to ZERO
        dto.setTotalAmount(validator.safeParseLegacyAmount(pmt.getTotalAmount(), id, "PMT_AMT"));
        dto.setPrincipalAmount(validator.safeParseLegacyAmount(pmt.getPrincipalAmount(), id, "PMT_PRIN_AMT"));
        dto.setInterestAmount(validator.safeParseLegacyAmount(pmt.getInterestAmount(), id, "PMT_INT_AMT"));
        dto.setEscrowAmount(validator.safeParseLegacyAmount(pmt.getEscrowAmount(), id, "PMT_ESCROW_AMT"));
        dto.setLateFee(validator.safeParseLegacyAmount(pmt.getLateFee(), id, "PMT_LATE_FEE"));
        dto.setType(validator.expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(validator.expandPaymentStatus(pmt.getStatusCode()));

        // ANO-001: Log warning if payment component sum does not match total
        BigDecimal computedSum = dto.getPrincipalAmount()
                .add(dto.getInterestAmount())
                .add(dto.getEscrowAmount())
                .add(dto.getLateFee());
        if (dto.getTotalAmount().compareTo(computedSum) != 0) {
            log.warn("ANO-001: Payment {} total ({}) != component sum ({}). Delta={}",
                    id, dto.getTotalAmount(), computedSum,
                    dto.getTotalAmount().subtract(computedSum));
        }

        return dto;
    }
}
