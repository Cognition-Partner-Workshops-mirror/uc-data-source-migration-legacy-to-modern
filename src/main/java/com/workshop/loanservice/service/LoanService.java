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
 *
 * Data validation is delegated to LegacyDataValidator which catches
 * anomalies (malformed numbers, invalid dates, cross-field inconsistencies)
 * at ingestion time rather than letting them propagate as runtime exceptions.
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

        // Use null-safe name building instead of raw concatenation (ANM-009)
        dto.setBorrowerName(validator.buildFullName(
                acct.getBorrowerFirstName(), null, acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());

        // Use validated parsing with error handling instead of raw BigDecimal construction (ANM-003)
        BigDecimal originalAmount = validator.safeParseAmount(acct.getOriginalAmount(), "LN_ORIG_AMT", id);
        dto.setOriginalAmount(validator.validateNonNegativeAmount(originalAmount, "LN_ORIG_AMT", id));

        BigDecimal currentBalance = validator.safeParseAmount(acct.getCurrentBalance(), "LN_CURR_BAL", id);
        dto.setCurrentBalance(validator.validateNonNegativeAmount(currentBalance, "LN_CURR_BAL", id));

        BigDecimal interestRate = validator.safeParseDecimal(acct.getInterestRate(), "LN_INT_RT", id);
        dto.setInterestRate(validator.validateInterestRate(interestRate, id));

        BigDecimal monthlyPayment = validator.safeParseAmount(acct.getMonthlyPayment(), "LN_PMT_AMT", id);
        dto.setMonthlyPayment(validator.validateNonNegativeAmount(monthlyPayment, "LN_PMT_AMT", id));

        // Validate status code against known set before expanding (ANM-005)
        validator.validateLoanStatusCode(acct.getStatusCode(), id);
        dto.setStatus(expandStatusCode(acct.getStatusCode()));

        // Validate date format at ingestion time (ANM-004)
        validator.safeParseLegacyDate(acct.getOriginationDate(), "LN_ORIG_DT", id);
        dto.setOriginationDate(acct.getOriginationDate());

        // Use null-safe address building instead of raw concatenation (ANM-009)
        dto.setPropertyAddress(validator.buildFullAddress(
                acct.getPropertyAddress(), acct.getPropertyCity(),
                acct.getPropertyState(), acct.getPropertyZip()));

        // Validate property type code before expanding
        validator.validatePropertyTypeCode(acct.getPropertyType(), id);
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        // Cross-field validation: delinquency days vs. status (ANM-005)
        validator.validateDelinquencyStatusConsistency(
                acct.getStatusCode(), acct.getDelinquencyDays(), id);

        // Cross-field validation: LTV percentage vs. computed value (ANM-008)
        validator.validateLtvPercentage(
                acct.getLtvPercent(), acct.getOriginalAmount(),
                acct.getAppraisedValue(), id);

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();
        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);

        // Use validator for null-safe name building (ANM-009)
        dto.setFullName(validator.buildFullName(
                borrower.getFirstName(), borrower.getMiddleInitial(), borrower.getLastName()));
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        // Use validated integer parsing with range check (ANM-003)
        Integer creditScore = validator.safeParseInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", id);
        dto.setCreditScore(validator.validateCreditScore(creditScore, id));

        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        // Validate borrower status code
        validator.validateBorrowerStatusCode(borrower.getStatusCode(), id);

        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String id = pmt.getPaymentSequenceNumber();
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());

        // Validate date format at ingestion time (ANM-004)
        validator.safeParseLegacyDate(pmt.getPaymentDate(), "PMT_DT", id);
        dto.setPaymentDate(pmt.getPaymentDate());

        // Use validated amount parsing with error handling (ANM-003)
        BigDecimal totalAmount = validator.safeParseAmount(pmt.getTotalAmount(), "PMT_AMT", id);
        dto.setTotalAmount(validator.validateNonNegativeAmount(totalAmount, "PMT_AMT", id));

        BigDecimal principalAmount = validator.safeParseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id);
        dto.setPrincipalAmount(validator.validateNonNegativeAmount(principalAmount, "PMT_PRIN_AMT", id));

        BigDecimal interestAmount = validator.safeParseAmount(pmt.getInterestAmount(), "PMT_INT_AMT", id);
        dto.setInterestAmount(validator.validateNonNegativeAmount(interestAmount, "PMT_INT_AMT", id));

        BigDecimal escrowAmount = validator.safeParseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id);
        dto.setEscrowAmount(validator.validateNonNegativeAmount(escrowAmount, "PMT_ESCROW_AMT", id));

        BigDecimal lateFee = validator.safeParseAmount(pmt.getLateFee(), "PMT_LATE_FEE", id);
        dto.setLateFee(validator.validateNonNegativeAmount(lateFee, "PMT_LATE_FEE", id));

        // Cross-field validation: payment components must sum to total (ANM-001)
        validator.validatePaymentComponentSum(
                dto.getTotalAmount(), dto.getPrincipalAmount(),
                dto.getInterestAmount(), dto.getEscrowAmount(),
                dto.getLateFee(), id);

        // Validate type and status codes before expanding
        validator.validatePaymentTypeCode(pmt.getTypeCode(), id);
        dto.setType(expandPaymentType(pmt.getTypeCode()));

        validator.validatePaymentStatusCode(pmt.getStatusCode(), id);
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));

        return dto;
    }

    /**
     * Parse legacy amount strings like "285,000" or "1,487.02" into BigDecimal.
     * @deprecated Use {@link LegacyDataValidator#safeParseAmount} instead for safe parsing with error handling.
     */
    @Deprecated
    private BigDecimal parseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        return new BigDecimal(amount.replace(",", ""));
    }

    /**
     * @deprecated Use {@link LegacyDataValidator#safeParseDecimal} instead for safe parsing with error handling.
     */
    @Deprecated
    private BigDecimal parseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        return new BigDecimal(value.trim());
    }

    /**
     * @deprecated Use {@link LegacyDataValidator#safeParseInteger} instead for safe parsing with error handling.
     */
    @Deprecated
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
