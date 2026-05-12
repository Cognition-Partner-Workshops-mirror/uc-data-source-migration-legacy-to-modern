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
 * MIGRATION TASK: This service contains all the translation logic
 * between legacy string-typed fields and proper Java types.
 * When switching data sources, this layer needs to be updated
 * (or replaced) to read from the modern schema.
 *
 * Data validation is performed at ingestion time via LegacyDataValidator
 * to catch known anomalies (see docs/DATA_ANOMALY_REPORT.md) before
 * they reach the API layer. Parsing methods use safe try-catch wrappers
 * with fallback defaults to prevent unhandled NumberFormatException crashes.
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

        // Build borrower lookup for validation cross-references (ANM-001, ANM-007)
        Map<String, LegacyBorrower> borrowers = borrowerRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyBorrower::getBorrowerId, b -> b));

        return loanAccountRepository.findAll().stream()
                .map(acct -> {
                    // Validate loan account at ingestion time
                    LegacyBorrower borrower = borrowers.get(acct.getBorrowerId());
                    validator.validateLoanAccount(acct, borrower);
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);

        // Validate loan account with borrower cross-reference
        LegacyBorrower borrower = acct.getBorrowerId() != null
                ? borrowerRepository.findById(acct.getBorrowerId()).orElse(null)
                : null;
        validator.validateLoanAccount(acct, borrower);

        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .map(borrower -> {
                    // Validate borrower at ingestion time
                    validator.validateBorrower(borrower);
                    return toBorrowerDto(borrower);
                })
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));

        // Validate borrower at ingestion time
        validator.validateBorrower(borrower);

        BorrowerDto dto = toBorrowerDto(borrower);

        // Attach loans for this borrower
        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> {
                    validator.validateLoanAccount(acct, borrower);
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
                    // Validate payment at ingestion time
                    validator.validatePayment(pmt);
                    return toPaymentDto(pmt);
                })
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    //
    // All parsing now uses safe try-catch wrappers (parseLegacyAmountSafe,
    // parseLegacyDecimalSafe, parseLegacyIntegerSafe) to prevent unhandled
    // NumberFormatException from poisoning entire list responses (RCA-003).
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());

        // ANM-006: Null-safe name concatenation to avoid "null null" in API responses
        dto.setBorrowerName(safeConcat(acct.getBorrowerFirstName(), acct.getBorrowerLastName()));

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(parseLegacyAmountSafe(acct.getOriginalAmount(), "LN_ORIG_AMT", acct.getLoanAccountNumber()));
        dto.setCurrentBalance(parseLegacyAmountSafe(acct.getCurrentBalance(), "LN_CURR_BAL", acct.getLoanAccountNumber()));
        dto.setInterestRate(parseLegacyDecimalSafe(acct.getInterestRate(), "LN_INT_RT", acct.getLoanAccountNumber()));
        dto.setMonthlyPayment(parseLegacyAmountSafe(acct.getMonthlyPayment(), "LN_PMT_AMT", acct.getLoanAccountNumber()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(acct.getOriginationDate());

        // ANM-006: Null-safe property address concatenation
        dto.setPropertyAddress(safePropertyAddress(
                acct.getPropertyAddress(), acct.getPropertyCity(),
                acct.getPropertyState(), acct.getPropertyZip()));

        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());

        // ANM-006: Null-safe name building to avoid "null" appearing in API output
        String firstName = nullSafe(borrower.getFirstName());
        String lastName = nullSafe(borrower.getLastName());
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName((firstName + middle + " " + lastName).trim());

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(parseLegacyIntegerSafe(borrower.getCreditScore(), "BORR_CRDT_SCR", borrower.getBorrowerId()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate());
        dto.setTotalAmount(parseLegacyAmountSafe(pmt.getTotalAmount(), "PMT_AMT", pmt.getPaymentSequenceNumber()));
        dto.setPrincipalAmount(parseLegacyAmountSafe(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", pmt.getPaymentSequenceNumber()));
        dto.setInterestAmount(parseLegacyAmountSafe(pmt.getInterestAmount(), "PMT_INT_AMT", pmt.getPaymentSequenceNumber()));
        dto.setEscrowAmount(parseLegacyAmountSafe(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", pmt.getPaymentSequenceNumber()));
        dto.setLateFee(parseLegacyAmountSafe(pmt.getLateFee(), "PMT_LATE_FEE", pmt.getPaymentSequenceNumber()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    // =========================================================================
    // SAFE PARSING METHODS
    // These replace the original parseLegacyAmount/Integer/Decimal methods
    // with try-catch wrappers that log parse failures and return fallback
    // defaults instead of throwing unhandled NumberFormatException (RCA-003).
    // =========================================================================

    /**
     * Safely parses legacy amount strings like "285,000" or "1,487.02" into BigDecimal.
     * Returns BigDecimal.ZERO and logs an error if the value cannot be parsed.
     */
    BigDecimal parseLegacyAmountSafe(String amount, String columnName, String recordId) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(amount.replace(",", "").trim());
        } catch (NumberFormatException e) {
            // RCA-003: Log instead of crashing — prevents one bad record from poisoning list endpoints
            log.error("Failed to parse amount for {} in record [{}]: '{}' — returning ZERO as fallback",
                    columnName, recordId, amount);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parses decimal strings like "4.750" into BigDecimal.
     * Also handles comma-separated values for robustness.
     */
    BigDecimal parseLegacyDecimalSafe(String value, String columnName, String recordId) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        try {
            // Also strip commas for consistency — parseLegacyDecimal originally did not
            return new BigDecimal(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.error("Failed to parse decimal for {} in record [{}]: '{}' — returning ZERO as fallback",
                    columnName, recordId, value);
            return BigDecimal.ZERO;
        }
    }

    /**
     * Safely parses integer strings like "745" into Integer.
     * Returns null and logs an error if the value cannot be parsed.
     */
    Integer parseLegacyIntegerSafe(String value, String columnName, String recordId) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.error("Failed to parse integer for {} in record [{}]: '{}' — returning null as fallback",
                    columnName, recordId, value);
            return null;
        }
    }

    // =========================================================================
    // STATUS CODE EXPANSION
    // ANM-010: Unknown codes are logged as warnings and returned as-is
    // rather than silently passing through.
    // =========================================================================

    private String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> {
                // ANM-010: Log unknown status codes instead of silently passing through
                log.warn("Unknown loan status code: '{}' — returning raw code", code);
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
                log.warn("Unknown property type code: '{}' — returning raw code", code);
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
                log.warn("Unknown payment type code: '{}' — returning raw code", code);
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
                log.warn("Unknown payment status code: '{}' — returning raw code", code);
                yield code;
            }
        };
    }

    // =========================================================================
    // NULL-SAFE STRING HELPERS
    // ANM-006: Prevent "null" from appearing in string concatenation output.
    // =========================================================================

    /** Returns empty string for null values instead of literal "null". */
    private String nullSafe(String value) {
        return value != null ? value : "";
    }

    /** Builds borrower display name with null-safe handling. */
    private String safeConcat(String firstName, String lastName) {
        String first = nullSafe(firstName);
        String last = nullSafe(lastName);
        return (first + " " + last).trim();
    }

    /** Builds a property address string with null-safe handling for each component. */
    private String safePropertyAddress(String address, String city, String state, String zip) {
        StringBuilder sb = new StringBuilder();
        if (address != null && !address.isBlank()) sb.append(address);
        if (city != null && !city.isBlank()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(city);
        }
        if (state != null && !state.isBlank()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(state);
        }
        if (zip != null && !zip.isBlank()) {
            if (sb.length() > 0) sb.append(" ");
            sb.append(zip);
        }
        return sb.length() > 0 ? sb.toString() : "Unknown";
    }
}
