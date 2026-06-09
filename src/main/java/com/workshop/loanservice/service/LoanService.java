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
import com.workshop.loanservice.validation.DataQualityResult;
import com.workshop.loanservice.validation.LegacyDataValidator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Service layer that reads from legacy tables and translates
 * cryptic legacy fields into clean DTOs.
 *
 * Includes data quality validation at ingestion time to catch known CDW
 * anomalies (see docs/DATA_ANOMALY_REPORT.md) before they propagate to
 * API responses. Uses fallback defaults for non-critical parse failures.
 */
@Service
public class LoanService {

    private static final Logger log = LoggerFactory.getLogger(LoanService.class);

    // Date format used by legacy CDW system
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

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
                .map(acct -> {
                    // Validate each loan account at ingestion time
                    validator.validateLoanAccount(acct);
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));

        // Validate the loan account before processing
        validator.validateLoanAccount(acct);

        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);

        // Referential integrity check: log warning if product code is orphaned (ANO-004)
        if (product == null && acct.getProductCode() != null) {
            log.warn("DATA_QUALITY_ERROR [LoanAccount:{}] productCode: "
                            + "Referenced product '{}' does not exist (orphaned reference)",
                    acct.getLoanAccountNumber(), acct.getProductCode());
        }

        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .map(borrower -> {
                    // Validate each borrower at ingestion time
                    validator.validateBorrower(borrower);
                    return toBorrowerDto(borrower);
                })
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));

        // Validate borrower before processing
        validator.validateBorrower(borrower);

        BorrowerDto dto = toBorrowerDto(borrower);

        // Attach loans for this borrower
        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> {
                    validator.validateLoanAccount(acct);
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
                .collect(Collectors.toList());
        dto.setLoans(loans);

        return dto;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(pmt -> {
                    // Validate each payment at ingestion time
                    validator.validatePayment(pmt);
                    return toPaymentDto(pmt);
                })
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    // Now includes safe parsing with fallback defaults for malformed data.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());

        // Safe null handling for borrower name concatenation (ANO-008)
        String firstName = acct.getBorrowerFirstName() != null ? acct.getBorrowerFirstName() : "Unknown";
        String lastName = acct.getBorrowerLastName() != null ? acct.getBorrowerLastName() : "Unknown";
        dto.setBorrowerName(firstName + " " + lastName);

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
        dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
        dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
        dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(parseLegacyDateToIso(acct.getOriginationDate()));

        // Safe null handling for property address concatenation (ANO-008)
        String propAddr = acct.getPropertyAddress() != null ? acct.getPropertyAddress() : "";
        String propCity = acct.getPropertyCity() != null ? acct.getPropertyCity() : "";
        String propState = acct.getPropertyState() != null ? acct.getPropertyState() : "";
        String propZip = acct.getPropertyZip() != null ? acct.getPropertyZip() : "";
        dto.setPropertyAddress(propAddr + ", " + propCity + ", " + propState + " " + propZip);

        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        // Expose delinquency days so API consumers can see delinquency state (ANO-003 fix)
        dto.setDelinquencyDays(parseLegacyInteger(acct.getDelinquencyDays()));

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());

        // Safe null handling for name construction (ANO-008)
        String first = borrower.getFirstName() != null ? borrower.getFirstName() : "Unknown";
        String last = borrower.getLastName() != null ? borrower.getLastName() : "Unknown";
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(first + middle + " " + last);

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(parseLegacyDateToIso(pmt.getPaymentDate()));
        dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
        dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
        dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
        dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
        dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    // =========================================================================
    // Safe parsing methods with error handling and fallback defaults
    // =========================================================================

    /**
     * Parse legacy amount strings like "285,000" or "1,487.02" into BigDecimal.
     * Returns BigDecimal.ZERO as fallback if parsing fails. (ANO-005 fix)
     */
    BigDecimal parseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}', using fallback ZERO", amount);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy decimal string (e.g., interest rate "5.250").
     * Returns BigDecimal.ZERO as fallback if parsing fails. (ANO-005 fix)
     */
    BigDecimal parseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}', using fallback ZERO", value);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Parse a legacy integer string (e.g., credit score "745", delinquency days "15").
     * Returns null as fallback if parsing fails. (ANO-005 fix)
     */
    Integer parseLegacyInteger(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}', using fallback null", value);
            return null;
        }
    }

    /**
     * Parse a legacy date string (MM/DD/YYYY) to ISO format (YYYY-MM-DD).
     * Returns the original string as fallback if parsing fails. (ANO-006 fix)
     */
    String parseLegacyDateToIso(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        try {
            LocalDate date = LocalDate.parse(dateStr, LEGACY_DATE_FORMAT);
            return date.toString(); // ISO-8601 format YYYY-MM-DD
        } catch (DateTimeParseException e) {
            log.warn("Failed to parse date '{}', returning raw value as fallback", dateStr);
            return dateStr;
        }
    }

    // =========================================================================
    // Status code expansion methods
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
}
