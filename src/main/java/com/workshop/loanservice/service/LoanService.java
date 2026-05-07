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
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Service layer that reads from legacy tables and translates
 * cryptic legacy fields into clean DTOs.
 *
 * Includes data quality validation at ingestion time to detect
 * and handle anomalies documented in docs/DATA_ANOMALY_REPORT.md.
 */
@Service
public class LoanService {

    private static final Logger log = LoggerFactory.getLogger(LoanService.class);

    private static final Set<String> VALID_LOAN_STATUS_CODES = Set.of("ACT", "CLO", "DFT", "FRB");
    private static final Set<String> VALID_PAYMENT_TYPE_CODES = Set.of("REG", "EXT", "PRT", "PRE");
    private static final Set<String> VALID_PAYMENT_STATUS_CODES = Set.of("PST", "REV", "NSF", "PND");

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

        LegacyBorrower borrower = acct.getBorrowerId() != null
                ? borrowerRepository.findById(acct.getBorrowerId()).orElse(null)
                : null;

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
    // LEGACY TRANSLATION METHODS (with validation)
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product,
                                         LegacyBorrower borrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = acct.getLoanAccountNumber();

        // Required-field checks (not duplicated by per-field parsing below)
        if (acct.getBorrowerId() == null || acct.getBorrowerId().isBlank()) {
            warnings.add(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, id, "borrowerId",
                    "Required field is null/blank", acct.getBorrowerId()));
        }
        if (acct.getProductCode() == null || acct.getProductCode().isBlank()) {
            warnings.add(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, id, "productCode",
                    "Required field is null/blank", acct.getProductCode()));
        }

        // Cross-entity and referential checks
        validator.validateBorrowerExists(acct.getBorrowerId(), borrower != null, id, warnings);
        validator.validateProductExists(acct.getProductCode(), product != null, id, warnings);
        validator.validateDenormalizedBorrowerName(acct, borrower, warnings);

        if (borrower != null) {
            validator.validateSsnLast4AgainstPhone(
                    acct.getBorrowerSsnLast4(), borrower.getPhoneNumber(), id, warnings);
        }

        // Build DTO with per-field validated parsing (each field parsed exactly once)
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);
        dto.setBorrowerName(validator.buildBorrowerName(
                acct.getBorrowerFirstName(), acct.getBorrowerLastName(), id, warnings));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(validator.parseAmount(acct.getOriginalAmount(), id, "originalAmount", warnings));
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), id, "currentBalance", warnings));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), id, "interestRate", warnings));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), id, "monthlyPayment", warnings));
        dto.setStatus(expandStatusCode(
                validator.validateStatusCode(acct.getStatusCode(), VALID_LOAN_STATUS_CODES,
                        id, "statusCode", warnings)));
        dto.setOriginationDate(validator.validateAndFormatDate(
                acct.getOriginationDate(), id, "originationDate", warnings));
        dto.setPropertyAddress(validator.buildPropertyAddress(
                acct.getPropertyAddress(), acct.getPropertyCity(),
                acct.getPropertyState(), acct.getPropertyZip(), id, warnings));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        // Validate fields not used in DTO but still worth checking
        validator.parseAmount(acct.getEscrowBalance(), id, "escrowBalance", warnings);
        validator.parseDecimal(acct.getLtvPercent(), id, "ltvPercent", warnings);
        validator.parseAmount(acct.getAppraisedValue(), id, "appraisedValue", warnings);
        validator.parseInteger(acct.getTermMonths(), id, "termMonths", warnings);
        validator.parseInteger(acct.getDelinquencyDays(), id, "delinquencyDays", warnings);
        validator.validateAndFormatDate(acct.getMaturityDate(), id, "maturityDate", warnings);
        validator.validateAndFormatDate(acct.getFirstPaymentDate(), id, "firstPaymentDate", warnings);
        validator.validateAndFormatDate(acct.getNextPaymentDate(), id, "nextPaymentDate", warnings);
        if (acct.getPropertyType() != null) {
            validator.validateStatusCode(acct.getPropertyType(), Set.of("SFR", "CND", "MFR", "TWN"),
                    id, "propertyType", warnings);
        }

        logWarnings(warnings);
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = borrower.getBorrowerId();

        // Required-field checks
        if (borrower.getFirstName() == null || borrower.getFirstName().isBlank()) {
            warnings.add(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, id, "firstName",
                    "Required field is null/blank", borrower.getFirstName()));
        }
        if (borrower.getLastName() == null || borrower.getLastName().isBlank()) {
            warnings.add(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, id, "lastName",
                    "Required field is null/blank", borrower.getLastName()));
        }
        if (borrower.getSsnEncrypted() == null || borrower.getSsnEncrypted().isBlank()) {
            warnings.add(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, id, "ssnEncrypted",
                    "Required field is null/blank", borrower.getSsnEncrypted()));
        }

        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);
        String middle = borrower.getMiddleInitial() != null
                ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(validator.safeString(borrower.getFirstName(), "Unknown")
                + middle + " "
                + validator.safeString(borrower.getLastName(), "Unknown"));
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        Integer creditScore = validator.parseInteger(
                borrower.getCreditScore(), id, "creditScore", warnings);
        if (creditScore != null && (creditScore < 300 || creditScore > 850)) {
            warnings.add(new DataQualityWarning(
                    DataQualityWarning.Severity.MEDIUM, id, "creditScore",
                    "Credit score outside valid range (300-850)",
                    borrower.getCreditScore()));
        }
        dto.setCreditScore(creditScore);
        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        // Validate remaining fields not mapped to DTO
        validator.parseAmount(borrower.getAnnualIncome(), id, "annualIncome", warnings);
        validator.validateAndFormatDate(borrower.getDateOfBirth(), id, "dateOfBirth", warnings);
        validator.validateAndFormatDate(borrower.getCreatedDate(), id, "createdDate", warnings);
        validator.validateAndFormatDate(borrower.getUpdatedDate(), id, "updatedDate", warnings);
        validator.validateStatusCode(borrower.getStatusCode(),
                Set.of("ACT", "INA"), id, "statusCode", warnings);

        logWarnings(warnings);
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        List<DataQualityWarning> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        // Required-field check
        if (pmt.getLoanAccountNumber() == null || pmt.getLoanAccountNumber().isBlank()) {
            warnings.add(new DataQualityWarning(
                    DataQualityWarning.Severity.HIGH, id, "loanAccountNumber",
                    "Required field is null/blank", pmt.getLoanAccountNumber()));
        }

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(validator.validateAndFormatDate(
                pmt.getPaymentDate(), id, "paymentDate", warnings));

        // Parse each field exactly once, then use for both DTO and cross-validation
        BigDecimal total = validator.parseAmount(pmt.getTotalAmount(), id, "totalAmount", warnings);
        BigDecimal principal = validator.parseAmount(pmt.getPrincipalAmount(), id, "principalAmount", warnings);
        BigDecimal interest = validator.parseAmount(pmt.getInterestAmount(), id, "interestAmount", warnings);
        BigDecimal escrow = validator.parseAmount(pmt.getEscrowAmount(), id, "escrowAmount", warnings);
        BigDecimal lateFee = validator.parseAmount(pmt.getLateFee(), id, "lateFee", warnings);

        dto.setTotalAmount(total);
        dto.setPrincipalAmount(principal);
        dto.setInterestAmount(interest);
        dto.setEscrowAmount(escrow);
        dto.setLateFee(lateFee);

        // Cross-field validation using already-parsed values
        validator.validatePaymentComponents(id, total, principal, interest, escrow, lateFee, warnings);

        dto.setType(expandPaymentType(
                validator.validateStatusCode(pmt.getTypeCode(), VALID_PAYMENT_TYPE_CODES,
                        id, "typeCode", warnings)));
        dto.setStatus(expandPaymentStatus(
                validator.validateStatusCode(pmt.getStatusCode(), VALID_PAYMENT_STATUS_CODES,
                        id, "statusCode", warnings)));

        // Validate remaining date fields and late fee consistency
        validator.validateAndFormatDate(pmt.getReceivedDate(), id, "receivedDate", warnings);
        validator.validateAndFormatDate(pmt.getProcessedDate(), id, "processedDate", warnings);
        validator.validateLateFeeConsistency(pmt, warnings);

        logWarnings(warnings);
        return dto;
    }

    // =========================================================================
    // Code expansion helpers
    // =========================================================================

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

    private void logWarnings(List<DataQualityWarning> warnings) {
        for (DataQualityWarning w : warnings) {
            switch (w.getSeverity()) {
                case CRITICAL -> log.error("DATA QUALITY {}", w);
                case HIGH -> log.warn("DATA QUALITY {}", w);
                case MEDIUM -> log.info("DATA QUALITY {}", w);
                case LOW -> log.debug("DATA QUALITY {}", w);
            }
        }
    }
}
