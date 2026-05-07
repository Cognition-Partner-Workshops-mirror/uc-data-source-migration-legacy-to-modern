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
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
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
    private static final int LATE_FEE_GRACE_PERIOD_DAYS = 15;

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

        Map<String, LegacyBorrower> borrowers = borrowerRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyBorrower::getBorrowerId, b -> b));

        return loanAccountRepository.findAll().stream()
                .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode()),
                        borrowers.get(acct.getBorrowerId())))
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        LegacyBorrower borrower = borrowerRepository.findById(acct.getBorrowerId())
                .orElse(null);
        return toLoanSummary(acct, product, borrower);
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

        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode()), borrower))
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

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product,
                                         LegacyBorrower masterBorrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);

        // ANO-005: Prefer master borrower name over denormalized copy
        if (masterBorrower != null) {
            validator.validateBorrowerNameConsistency(id,
                    acct.getBorrowerFirstName(), acct.getBorrowerLastName(),
                    masterBorrower.getFirstName(), masterBorrower.getLastName(),
                    warnings);
            dto.setBorrowerName(masterBorrower.getFirstName() + " " + masterBorrower.getLastName());
        } else {
            // ANO-003: Orphaned loan — borrower not found in master table
            warnings.add(new DataQualityWarning("ANO-003", "Critical", "BORR_ID",
                    acct.getBorrowerId(),
                    "Loan " + id + " references non-existent borrower; using denormalized name"));
            log.warn("Orphaned loan {}: BORR_ID={} not found in CDW_BORR_MSTR", id, acct.getBorrowerId());
            dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
        }

        // ANO-003: Check product FK
        if (product != null) {
            dto.setProductDescription(product.getDescription());
        } else {
            warnings.add(new DataQualityWarning("ANO-003", "Critical", "PROD_CD",
                    acct.getProductCode(),
                    "Loan " + id + " references non-existent product code"));
            log.warn("Orphaned product reference in loan {}: PROD_CD={}", id, acct.getProductCode());
            dto.setProductDescription(acct.getProductCode());
        }

        // ANO-002: Safe numeric parsing
        BigDecimal originalAmount = validator.parseAmount(acct.getOriginalAmount(), "LN_ORIG_AMT", id, warnings);
        BigDecimal currentBalance = validator.parseAmount(acct.getCurrentBalance(), "LN_CURR_BAL", id, warnings);
        BigDecimal interestRate = validator.parseDecimal(acct.getInterestRate(), "LN_INT_RT", id, warnings);
        BigDecimal monthlyPayment = validator.parseAmount(acct.getMonthlyPayment(), "LN_PMT_AMT", id, warnings);

        dto.setOriginalAmount(originalAmount);
        dto.setCurrentBalance(currentBalance);
        dto.setInterestRate(interestRate);
        dto.setMonthlyPayment(monthlyPayment);
        dto.setStatus(expandStatusCode(acct.getStatusCode()));

        // ANO-008: Parse and validate date, fall back to raw string if invalid
        dto.setOriginationDate(validateAndFormatDate(acct.getOriginationDate(), "LN_ORIG_DT", id, warnings));

        String propertyAddress = Optional.ofNullable(acct.getPropertyAddress()).orElse("")
                + ", " + Optional.ofNullable(acct.getPropertyCity()).orElse("")
                + ", " + Optional.ofNullable(acct.getPropertyState()).orElse("")
                + " " + Optional.ofNullable(acct.getPropertyZip()).orElse("");
        dto.setPropertyAddress(propertyAddress);
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        // ANO-004: Validate delinquency vs status
        validator.validateDelinquencyStatus(id, acct.getDelinquencyDays(), acct.getStatusCode(), warnings);

        // ANO-007: Validate LTV accuracy
        BigDecimal appraisedValue = validator.parseAmount(acct.getAppraisedValue(), "PROP_APRS_VAL", id, warnings);
        BigDecimal recordedLtv = validator.parseDecimal(acct.getLtvPercent(), "LN_LTV_PCT", id, warnings);
        validator.validateLtvAccuracy(id, currentBalance, appraisedValue, recordedLtv, warnings);

        dto.setDataQualityWarnings(warnings);
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);

        // ANO-009: Validate required fields
        String firstName = validator.validateRequiredField(borrower.getFirstName(), "BORR_FST_NM", id, "Unknown", warnings);
        String lastName = validator.validateRequiredField(borrower.getLastName(), "BORR_LST_NM", id, "Unknown", warnings);

        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(firstName + middle + " " + lastName);
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        // ANO-002: Safe integer parsing for credit score
        dto.setCreditScore(validator.parseInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", id, warnings));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        dto.setDataQualityWarnings(warnings);
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());

        // ANO-008: Parse and validate date
        dto.setPaymentDate(validateAndFormatDate(pmt.getPaymentDate(), "PMT_DT", id, warnings));

        // ANO-002: Safe numeric parsing
        BigDecimal totalAmount = validator.parseAmount(pmt.getTotalAmount(), "PMT_AMT", id, warnings);
        BigDecimal principalAmount = validator.parseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id, warnings);
        BigDecimal interestAmount = validator.parseAmount(pmt.getInterestAmount(), "PMT_INT_AMT", id, warnings);
        BigDecimal escrowAmount = validator.parseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id, warnings);
        BigDecimal lateFee = validator.parseAmount(pmt.getLateFee(), "PMT_LATE_FEE", id, warnings);

        dto.setTotalAmount(totalAmount);
        dto.setPrincipalAmount(principalAmount);
        dto.setInterestAmount(interestAmount);
        dto.setEscrowAmount(escrowAmount);
        dto.setLateFee(lateFee);

        // ANO-001: Validate payment component sum
        validator.validatePaymentComponentSum(id, totalAmount, principalAmount, interestAmount, escrowAmount, lateFee, warnings);

        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));

        // ANO-006: Validate late fee consistency
        validator.validateLateFeeConsistency(id, pmt.getPaymentDate(), pmt.getReceivedDate(),
                lateFee, LATE_FEE_GRACE_PERIOD_DAYS, warnings);

        dto.setDataQualityWarnings(warnings);
        return dto;
    }

    /**
     * Validate a legacy date string and return ISO-8601 format if valid,
     * or the raw string as fallback.
     */
    private String validateAndFormatDate(String dateStr, String fieldName, String recordId,
                                         List<DataQualityWarning> warnings) {
        if (dateStr == null || dateStr.isBlank()) {
            return null;
        }
        java.time.LocalDate parsed = validator.parseDate(dateStr, fieldName, recordId, warnings);
        if (parsed != null) {
            return parsed.toString();
        }
        return dateStr;
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
