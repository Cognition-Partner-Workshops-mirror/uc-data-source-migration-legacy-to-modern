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
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Comparator;
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

    private static final Logger log = LoggerFactory.getLogger(LoanService.class);

    static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/uuuu")
            .withResolverStyle(java.time.format.ResolverStyle.STRICT);
    static final int CREDIT_SCORE_MIN = 300;
    static final int CREDIT_SCORE_MAX = 850;

    private final LegacyBorrowerRepository borrowerRepository;
    private final LegacyLoanAccountRepository loanAccountRepository;
    private final LegacyLoanProductRepository loanProductRepository;
    private final LegacyPaymentRepository paymentRepository;

    public LoanService(LegacyBorrowerRepository borrowerRepository,
                       LegacyLoanAccountRepository loanAccountRepository,
                       LegacyLoanProductRepository loanProductRepository,
                       LegacyPaymentRepository paymentRepository) {
        this.borrowerRepository = borrowerRepository;
        this.loanAccountRepository = loanAccountRepository;
        this.loanProductRepository = loanProductRepository;
        this.paymentRepository = paymentRepository;
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
        List<PaymentDto> payments = paymentRepository
                .findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(this::toPaymentDto)
                .collect(Collectors.toList());

        payments.sort(Comparator.comparing(
                (PaymentDto p) -> parseLegacyDate(p.getPaymentDate()),
                Comparator.nullsLast(Comparator.reverseOrder())
        ));

        return payments;
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    // =========================================================================

    LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        List<String> warnings = new ArrayList<>();

        dto.setLoanAccountNumber(acct.getLoanAccountNumber());
        dto.setBorrowerName(nullSafe(acct.getBorrowerFirstName()) + " " + nullSafe(acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount(), "originalAmount", acct.getLoanAccountNumber(), warnings));
        dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance(), "currentBalance", acct.getLoanAccountNumber(), warnings));
        dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate(), "interestRate", acct.getLoanAccountNumber(), warnings));
        dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment(), "monthlyPayment", acct.getLoanAccountNumber(), warnings));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));

        String validatedDate = validateLegacyDate(acct.getOriginationDate(), "originationDate", acct.getLoanAccountNumber(), warnings);
        dto.setOriginationDate(validatedDate);

        dto.setPropertyAddress(
                nullSafe(acct.getPropertyAddress()) + ", "
                + nullSafe(acct.getPropertyCity()) + ", "
                + nullSafe(acct.getPropertyState()) + " "
                + nullSafe(acct.getPropertyZip()));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        validateDelinquencyStatus(acct, warnings);

        if (product == null && acct.getProductCode() != null) {
            warnings.add("Orphaned product code: " + acct.getProductCode() + " not found in CDW_LN_PROD");
            log.warn("Loan {} references unknown product code: {}", acct.getLoanAccountNumber(), acct.getProductCode());
        }

        dto.setDataQualityWarnings(warnings);
        return dto;
    }

    BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        List<String> warnings = new ArrayList<>();

        dto.setId(borrower.getBorrowerId());

        String first = nullSafe(borrower.getFirstName());
        String last = nullSafe(borrower.getLastName());
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(first + middle + " " + last);

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        Integer creditScore = parseLegacyInteger(borrower.getCreditScore(), "creditScore", borrower.getBorrowerId(), warnings);
        if (creditScore != null) {
            validateCreditScoreRange(creditScore, borrower.getBorrowerId(), warnings);
        }
        dto.setCreditScore(creditScore);

        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        dto.setDataQualityWarnings(warnings);
        return dto;
    }

    PaymentDto toPaymentDto(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        List<String> warnings = new ArrayList<>();
        String id = pmt.getPaymentSequenceNumber();

        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());

        String validatedDate = validateLegacyDate(pmt.getPaymentDate(), "paymentDate", id, warnings);
        dto.setPaymentDate(validatedDate);

        BigDecimal total = parseLegacyAmount(pmt.getTotalAmount(), "totalAmount", id, warnings);
        BigDecimal principal = parseLegacyAmount(pmt.getPrincipalAmount(), "principalAmount", id, warnings);
        BigDecimal interest = parseLegacyAmount(pmt.getInterestAmount(), "interestAmount", id, warnings);
        BigDecimal escrow = parseLegacyAmount(pmt.getEscrowAmount(), "escrowAmount", id, warnings);
        BigDecimal late = parseLegacyAmount(pmt.getLateFee(), "lateFee", id, warnings);

        dto.setTotalAmount(total);
        dto.setPrincipalAmount(principal);
        dto.setInterestAmount(interest);
        dto.setEscrowAmount(escrow);
        dto.setLateFee(late);
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));

        BigDecimal computedTotal = principal.add(interest).add(escrow).add(late);
        dto.setComputedTotal(computedTotal);
        validatePaymentComponentSum(total, computedTotal, id, warnings);

        dto.setDataQualityWarnings(warnings);
        return dto;
    }

    // =========================================================================
    // DEFENSIVE PARSING
    // =========================================================================

    BigDecimal parseLegacyAmount(String amount, String fieldName, String recordId, List<String> warnings) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        try {
            String cleaned = amount.replace(",", "").replace("$", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            warnings.add("Unparseable amount in " + fieldName + ": '" + amount + "'");
            log.warn("Record {}: failed to parse {} value '{}' as BigDecimal", recordId, fieldName, amount);
            return BigDecimal.ZERO;
        }
    }

    BigDecimal parseLegacyDecimal(String value, String fieldName, String recordId, List<String> warnings) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        try {
            String cleaned = value.replace("%", "").trim();
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            warnings.add("Unparseable decimal in " + fieldName + ": '" + value + "'");
            log.warn("Record {}: failed to parse {} value '{}' as BigDecimal", recordId, fieldName, value);
            return BigDecimal.ZERO;
        }
    }

    Integer parseLegacyInteger(String value, String fieldName, String recordId, List<String> warnings) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            warnings.add("Unparseable integer in " + fieldName + ": '" + value + "'");
            log.warn("Record {}: failed to parse {} value '{}' as Integer", recordId, fieldName, value);
            return null;
        }
    }

    // =========================================================================
    // DATE VALIDATION
    // =========================================================================

    String validateLegacyDate(String dateStr, String fieldName, String recordId, List<String> warnings) {
        if (dateStr == null || dateStr.isBlank()) return null;
        try {
            LocalDate.parse(dateStr, LEGACY_DATE_FORMAT);
            return dateStr;
        } catch (DateTimeParseException e) {
            warnings.add("Invalid date in " + fieldName + ": '" + dateStr + "'");
            log.warn("Record {}: invalid date format in {} value '{}'", recordId, fieldName, dateStr);
            return null;
        }
    }

    LocalDate parseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        try {
            return LocalDate.parse(dateStr, LEGACY_DATE_FORMAT);
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    // =========================================================================
    // CROSS-FIELD VALIDATION
    // =========================================================================

    void validatePaymentComponentSum(BigDecimal statedTotal, BigDecimal computedTotal,
                                     String paymentId, List<String> warnings) {
        if (statedTotal.compareTo(computedTotal) != 0) {
            BigDecimal delta = computedTotal.subtract(statedTotal);
            String msg = "Payment component mismatch: stated total=" + statedTotal
                    + ", computed (prin+int+escrow+late)=" + computedTotal
                    + ", delta=" + delta;
            warnings.add(msg);
            log.warn("Payment {}: {}", paymentId, msg);
        }
    }

    void validateDelinquencyStatus(LegacyLoanAccount acct, List<String> warnings) {
        Integer dlqDays = null;
        if (acct.getDelinquencyDays() != null && !acct.getDelinquencyDays().isBlank()) {
            try {
                dlqDays = Integer.parseInt(acct.getDelinquencyDays().trim());
            } catch (NumberFormatException e) {
                // non-critical; skip validation
            }
        }
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            String msg = "Delinquency/status inconsistency: " + dlqDays
                    + " days delinquent but status is ACT (Active)";
            warnings.add(msg);
            log.warn("Loan {}: {}", acct.getLoanAccountNumber(), msg);
        }
    }

    void validateCreditScoreRange(int score, String borrowerId, List<String> warnings) {
        if (score < CREDIT_SCORE_MIN || score > CREDIT_SCORE_MAX) {
            String msg = "Credit score " + score + " outside valid FICO range ("
                    + CREDIT_SCORE_MIN + "-" + CREDIT_SCORE_MAX + ")";
            warnings.add(msg);
            log.warn("Borrower {}: {}", borrowerId, msg);
        }
    }

    // =========================================================================
    // UTILITY METHODS
    // =========================================================================

    static String nullSafe(String value) {
        return value != null ? value : "";
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
