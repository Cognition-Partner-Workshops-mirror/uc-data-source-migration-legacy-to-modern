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
 * Includes data quality validation (see DataQualityValidator) to catch
 * anomalies at ingestion time — null fields, unparseable numbers,
 * invalid status codes, and payment component mismatches.
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
                .map(acct -> {
                    // Validate each loan account before translation (ANOM-002, ANOM-003, ANOM-009)
                    validator.validateLoanAccount(acct);
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));

        // Validate before translation
        validator.validateLoanAccount(acct);

        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .map(borrower -> {
                    // Validate each borrower before translation (ANOM-002, ANOM-003, ANOM-008)
                    validator.validateBorrower(borrower);
                    return toBorrowerDto(borrower);
                })
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));

        // Validate before translation
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
                    // Validate each payment before translation (ANOM-001, ANOM-003, ANOM-006)
                    validator.validatePayment(pmt);
                    return toPaymentDto(pmt);
                })
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    // Now uses safe parsing with fallback defaults to prevent crashes (ANOM-003).
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());

        // ANOM-002 fix: null-safe name concatenation
        dto.setBorrowerName(safeConcat(acct.getBorrowerFirstName(), " ", acct.getBorrowerLastName()));

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());

        // ANOM-003 fix: safe parsing with fallback to ZERO instead of throwing
        dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
        dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
        dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
        dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));

        // ANOM-009 fix: status expansion with "Unknown" fallback for unrecognized codes
        dto.setStatus(expandStatusCode(acct.getStatusCode()));

        // ANOM-008: date passed as-is (string); validated by DataQualityValidator
        dto.setOriginationDate(acct.getOriginationDate());

        // ANOM-002 fix: null-safe address concatenation
        dto.setPropertyAddress(buildPropertyAddress(
                acct.getPropertyAddress(), acct.getPropertyCity(),
                acct.getPropertyState(), acct.getPropertyZip()));

        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());

        // ANOM-002 fix: null-safe name construction
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        String firstName = borrower.getFirstName() != null ? borrower.getFirstName() : "Unknown";
        String lastName = borrower.getLastName() != null ? borrower.getLastName() : "Unknown";
        dto.setFullName(firstName + middle + " " + lastName);

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        // ANOM-003 fix: safe integer parsing with try-catch
        dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));

        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate());

        // ANOM-003 fix: safe amount parsing for all payment fields
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
    // SAFE PARSING METHODS
    // Wrap all conversions in try-catch to prevent a single bad record
    // from crashing the entire endpoint (ANOM-003 fix).
    // =========================================================================

    /**
     * Parses legacy amount strings like "285,000" or "1,487.02" into BigDecimal.
     * Returns BigDecimal.ZERO on null/blank input.
     * Logs warning and returns BigDecimal.ZERO on parse failure instead of throwing.
     */
    BigDecimal parseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(amount.replace(",", ""));
        } catch (NumberFormatException e) {
            log.warn("Failed to parse legacy amount '{}', defaulting to ZERO: {}", amount, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    BigDecimal parseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse legacy decimal '{}', defaulting to ZERO: {}", value, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    Integer parseLegacyInteger(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse legacy integer '{}', returning null: {}", value, e.getMessage());
            return null;
        }
    }

    // =========================================================================
    // NULL-SAFE HELPER METHODS
    // Prevent NPE from null legacy fields in string concatenation (ANOM-002 fix).
    // =========================================================================

    /**
     * Safely concatenates two strings with a separator, substituting "Unknown"
     * for null values to prevent "null" literal in API output.
     */
    private String safeConcat(String first, String separator, String second) {
        String safeFirst = (first != null && !first.isBlank()) ? first : "Unknown";
        String safeSecond = (second != null && !second.isBlank()) ? second : "Unknown";
        return safeFirst + separator + safeSecond;
    }

    /**
     * Builds a property address string, substituting "N/A" for null components
     * to avoid "null, null, null null" in the API response.
     */
    private String buildPropertyAddress(String address, String city, String state, String zip) {
        String safeAddr = address != null ? address : "N/A";
        String safeCity = city != null ? city : "N/A";
        String safeState = state != null ? state : "N/A";
        String safeZip = zip != null ? zip : "N/A";
        return safeAddr + ", " + safeCity + ", " + safeState + " " + safeZip;
    }

    // =========================================================================
    // STATUS/TYPE CODE EXPANSION
    // Returns "Unknown" for null and passes through unrecognized codes
    // with a log warning (ANOM-009 handling).
    // =========================================================================

    private String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> {
                log.warn("Unrecognized loan status code '{}', passing through as-is", code);
                yield code;
            }
        };
    }

    private String expandPropertyType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "SFR" -> "Single Family Residence";
            case "CND" -> "Condominium";
            case "MFR" -> "Multi-Family Residence";
            case "TWN" -> "Townhouse";
            default -> {
                log.warn("Unrecognized property type code '{}', passing through as-is", code);
                yield code;
            }
        };
    }

    private String expandPaymentType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "REG" -> "Regular";
            case "EXT" -> "Extra";
            case "PRT" -> "Partial";
            case "PRE" -> "Prepayment";
            default -> {
                log.warn("Unrecognized payment type code '{}', passing through as-is", code);
                yield code;
            }
        };
    }

    private String expandPaymentStatus(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "PST" -> "Posted";
            case "REV" -> "Reversed";
            case "NSF" -> "Non-Sufficient Funds";
            case "PND" -> "Pending";
            default -> {
                log.warn("Unrecognized payment status code '{}', passing through as-is", code);
                yield code;
            }
        };
    }
}
