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
import com.workshop.loanservice.validation.DataQualityWarning;
import com.workshop.loanservice.validation.LegacyDataValidator;
import org.springframework.stereotype.Service;

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
        List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);
        String id = acct.getLoanAccountNumber();

        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);
        dto.setBorrowerName(validator.buildFullName(acct.getBorrowerFirstName(), acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(validator.parseAmount(acct.getOriginalAmount(), id, "LN_ORIG_AMT", warnings));
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), id, "LN_CURR_BAL", warnings));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), id, "LN_INT_RT", warnings));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), id, "LN_PMT_AMT", warnings));
        dto.setStatus(validator.resolveEffectiveLoanStatus(acct.getStatusCode(), acct.getDelinquencyDays()));
        dto.setOriginationDate(validator.formatDateToIso(acct.getOriginationDate(), id, "LN_ORIG_DT", warnings));
        dto.setPropertyAddress(validator.buildAddress(
                acct.getPropertyAddress(), acct.getPropertyCity(),
                acct.getPropertyState(), acct.getPropertyZip()));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        dto.setDataQualityWarnings(toWarningStrings(warnings));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
        String id = borrower.getBorrowerId();

        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(validator.safeString(borrower.getFirstName(), "") + middle + " "
                + validator.safeString(borrower.getLastName(), ""));
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(validator.parseInteger(borrower.getCreditScore(), id, "BORR_CRDT_SCR", warnings));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        dto.setDataQualityWarnings(toWarningStrings(warnings));
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        List<DataQualityWarning> warnings = validator.validatePayment(pmt);
        String id = pmt.getPaymentSequenceNumber();

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(validator.formatDateToIso(pmt.getPaymentDate(), id, "PMT_DT", warnings));
        dto.setTotalAmount(validator.parseAmount(pmt.getTotalAmount(), id, "PMT_AMT", warnings));
        dto.setPrincipalAmount(validator.parseAmount(pmt.getPrincipalAmount(), id, "PMT_PRIN_AMT", warnings));
        dto.setInterestAmount(validator.parseAmount(pmt.getInterestAmount(), id, "PMT_INT_AMT", warnings));
        dto.setEscrowAmount(validator.parseAmount(pmt.getEscrowAmount(), id, "PMT_ESCROW_AMT", warnings));
        dto.setLateFee(validator.parseAmount(pmt.getLateFee(), id, "PMT_LATE_FEE", warnings));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        dto.setDataQualityWarnings(toWarningStrings(warnings));
        return dto;
    }

    private List<String> toWarningStrings(List<DataQualityWarning> warnings) {
        if (warnings == null || warnings.isEmpty()) {
            return null;
        }
        return warnings.stream()
                .map(DataQualityWarning::toString)
                .collect(Collectors.toList());
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
