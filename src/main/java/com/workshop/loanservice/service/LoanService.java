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
import com.workshop.loanservice.validation.DataQualityException;
import com.workshop.loanservice.validation.DataQualityValidator;
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
 * Data quality validation is performed at ingestion time via DataQualityValidator.
 * Records that fail critical validation are excluded from results and logged.
 * Records with non-critical warnings are included but warnings are logged.
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
    private final DataQualityValidator validator;

    public LoanService(LegacyBorrowerRepository borrowerRepository,
                       LegacyLoanAccountRepository loanAccountRepository,
                       LegacyLoanProductRepository loanProductRepository,
                       LegacyPaymentRepository paymentRepository,
                       DataQualityValidator validator) {
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
                .filter(acct -> validateLoanAccountSafe(acct))
                .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        // Validate — throws DataQualityException on critical failures
        validator.validateLoanAccount(acct);
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .filter(borrower -> validateBorrowerSafe(borrower))
                .map(this::toBorrowerDto)
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
        // Validate — throws DataQualityException on critical failures
        validator.validateBorrower(borrower);
        BorrowerDto dto = toBorrowerDto(borrower);

        // Attach loans for this borrower
        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .filter(acct -> validateLoanAccountSafe(acct))
                .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .filter(pmt -> validatePaymentSafe(pmt))
                .map(this::toPaymentDto)
                .collect(Collectors.toList());
    }

    // =========================================================================
    // VALIDATION WRAPPERS
    // Catch DataQualityException from critical failures in list operations
    // and exclude the offending record rather than crashing the entire endpoint.
    // =========================================================================

    /**
     * Validate a borrower record, returning false to exclude it from results
     * if a critical data quality issue is found.
     */
    private boolean validateBorrowerSafe(LegacyBorrower borrower) {
        try {
            validator.validateBorrower(borrower);
            return true;
        } catch (DataQualityException e) {
            log.error("[DATA_QUALITY] Excluding borrower {}: {} (anomaly: {})",
                    e.getRecordId(), e.getMessage(), e.getAnomalyType());
            return false;
        }
    }

    /**
     * Validate a loan account record, returning false to exclude it from results
     * if a critical data quality issue is found.
     */
    private boolean validateLoanAccountSafe(LegacyLoanAccount account) {
        try {
            validator.validateLoanAccount(account);
            return true;
        } catch (DataQualityException e) {
            log.error("[DATA_QUALITY] Excluding loan {}: {} (anomaly: {})",
                    e.getRecordId(), e.getMessage(), e.getAnomalyType());
            return false;
        }
    }

    /**
     * Validate a payment record, returning false to exclude it from results
     * if a critical data quality issue is found.
     */
    private boolean validatePaymentSafe(LegacyPayment payment) {
        try {
            validator.validatePayment(payment);
            return true;
        } catch (DataQualityException e) {
            log.error("[DATA_QUALITY] Excluding payment {}: {} (anomaly: {})",
                    e.getRecordId(), e.getMessage(), e.getAnomalyType());
            return false;
        }
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    // Safe parsing via DataQualityValidator is used to handle malformed data.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());

        // Null-safe name concatenation to prevent "null null" in API responses (ANO-003)
        String firstName = acct.getBorrowerFirstName() != null ? acct.getBorrowerFirstName() : "";
        String lastName = acct.getBorrowerLastName() != null ? acct.getBorrowerLastName() : "";
        dto.setBorrowerName((firstName + " " + lastName).trim());

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());

        // Use safe parsing with fallback to BigDecimal.ZERO for amount fields (ANO-006)
        dto.setOriginalAmount(parseLegacyAmountSafe(acct.getOriginalAmount()));
        dto.setCurrentBalance(parseLegacyAmountSafe(acct.getCurrentBalance()));
        dto.setInterestRate(parseLegacyDecimalSafe(acct.getInterestRate()));
        dto.setMonthlyPayment(parseLegacyAmountSafe(acct.getMonthlyPayment()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(acct.getOriginationDate());

        // Null-safe property address concatenation (ANO-003)
        dto.setPropertyAddress(buildPropertyAddress(acct));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    /**
     * Build a full property address string, handling nulls gracefully
     * instead of producing "null, null, null null".
     */
    private String buildPropertyAddress(LegacyLoanAccount acct) {
        StringBuilder sb = new StringBuilder();
        if (acct.getPropertyAddress() != null) {
            sb.append(acct.getPropertyAddress());
        }
        if (acct.getPropertyCity() != null) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(acct.getPropertyCity());
        }
        if (acct.getPropertyState() != null) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(acct.getPropertyState());
        }
        if (acct.getPropertyZip() != null) {
            if (sb.length() > 0) sb.append(" ");
            sb.append(acct.getPropertyZip());
        }
        return sb.length() > 0 ? sb.toString() : "Unknown";
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());

        // Null-safe full name construction (ANO-003)
        String firstName = borrower.getFirstName() != null ? borrower.getFirstName() : "";
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        String lastName = borrower.getLastName() != null ? borrower.getLastName() : "";
        dto.setFullName((firstName + middle + " " + lastName).trim());

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        // Safe integer parsing for credit score (ANO-006)
        dto.setCreditScore(validator.safeParseInteger(borrower.getCreditScore()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate());

        // Safe amount parsing for all payment fields (ANO-006)
        dto.setTotalAmount(parseLegacyAmountSafe(pmt.getTotalAmount()));
        dto.setPrincipalAmount(parseLegacyAmountSafe(pmt.getPrincipalAmount()));
        dto.setInterestAmount(parseLegacyAmountSafe(pmt.getInterestAmount()));
        dto.setEscrowAmount(parseLegacyAmountSafe(pmt.getEscrowAmount()));
        dto.setLateFee(parseLegacyAmountSafe(pmt.getLateFee()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    /**
     * Parse legacy amount strings with error handling.
     * Returns BigDecimal.ZERO for null/blank or unparseable values
     * instead of throwing NumberFormatException.
     */
    private BigDecimal parseLegacyAmountSafe(String amount) {
        BigDecimal result = validator.safeParseAmount(amount);
        return result != null ? result : BigDecimal.ZERO;
    }

    /**
     * Parse legacy decimal strings with error handling.
     * Returns BigDecimal.ZERO for null/blank or unparseable values.
     */
    private BigDecimal parseLegacyDecimalSafe(String value) {
        BigDecimal result = validator.safeParseDecimal(value);
        return result != null ? result : BigDecimal.ZERO;
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
