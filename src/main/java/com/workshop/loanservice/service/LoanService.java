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
import com.workshop.loanservice.validation.ValidationResult;
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
 * Includes data quality validation that catches known CDW anomalies
 * at ingestion time: numeric parsing errors, date format issues,
 * business rule violations, and referential integrity problems.
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
    // LEGACY TRANSLATION METHODS WITH VALIDATION
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        ValidationResult validation = validator.validateLoanAccount(acct);

        boolean borrowerExists = acct.getBorrowerId() != null
                && borrowerRepository.existsById(acct.getBorrowerId());
        boolean productExists = acct.getProductCode() != null
                && loanProductRepository.existsById(acct.getProductCode());
        validator.validateReferentialIntegrity(acct, borrowerExists, productExists, validation);

        if (acct.getBorrowerId() != null && acct.getBorrowerSsnLast4() != null) {
            borrowerRepository.findById(acct.getBorrowerId()).ifPresent(borrower ->
                    validator.validateSsnAgainstPhone(
                            acct.getBorrowerSsnLast4(),
                            borrower.getPhoneNumber(),
                            acct.getLoanAccountNumber(),
                            validation));
        }

        logValidationWarnings(validation, "LoanAccount", acct.getLoanAccountNumber());

        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());
        dto.setBorrowerName(safeConcatName(acct.getBorrowerFirstName(), acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
        dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
        dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
        dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
        dto.setStatus(resolveEffectiveStatus(acct));
        dto.setOriginationDate(acct.getOriginationDate());
        dto.setPropertyAddress(buildPropertyAddress(acct));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        dto.setDataQualityWarnings(toWarningStrings(validation));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        ValidationResult validation = validator.validateBorrower(borrower);
        logValidationWarnings(validation, "Borrower", borrower.getBorrowerId());

        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(safeConcatName(borrower.getFirstName(), borrower.getLastName(), middle));
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        dto.setDataQualityWarnings(toWarningStrings(validation));
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        ValidationResult validation = validator.validatePayment(pmt);
        logValidationWarnings(validation, "Payment", pmt.getPaymentSequenceNumber());

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate());
        dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
        dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
        dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
        dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
        dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));

        BigDecimal safeTotal = safeParseAmount(pmt.getTotalAmount());
        BigDecimal safePrincipal = safeParseAmount(pmt.getPrincipalAmount());
        BigDecimal safeInterest = safeParseAmount(pmt.getInterestAmount());
        BigDecimal safeEscrow = safeParseAmount(pmt.getEscrowAmount());
        BigDecimal safeLateFee = safeParseAmount(pmt.getLateFee());

        if (safeTotal != null && safePrincipal != null && safeInterest != null
                && safeEscrow != null && safeLateFee != null) {
            BigDecimal componentSum = safePrincipal.add(safeInterest).add(safeEscrow).add(safeLateFee);
            BigDecimal diff = componentSum.subtract(safeTotal).abs();
            if (diff.compareTo(new BigDecimal("0.01")) > 0) {
                dto.setRecalculatedTotal(componentSum);
            }
        }

        dto.setDataQualityWarnings(toWarningStrings(validation));
        return dto;
    }

    // =========================================================================
    // SAFE PARSING WITH ERROR HANDLING
    // =========================================================================

    BigDecimal parseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(amount.replace(",", ""));
        } catch (NumberFormatException e) {
            log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    BigDecimal parseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        try {
            return new BigDecimal(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse decimal '{}': {}", value, e.getMessage());
            return BigDecimal.ZERO;
        }
    }

    Integer parseLegacyInteger(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            log.warn("Failed to parse integer '{}': {}", value, e.getMessage());
            return null;
        }
    }

    private BigDecimal safeParseAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(amount.replace(",", ""));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    // =========================================================================
    // BUSINESS LOGIC HELPERS
    // =========================================================================

    private String resolveEffectiveStatus(LegacyLoanAccount acct) {
        String baseStatus = expandStatusCode(acct.getStatusCode());
        Integer dlqDays = parseLegacyInteger(acct.getDelinquencyDays());
        if (dlqDays != null && dlqDays > 0 && "ACT".equals(acct.getStatusCode())) {
            return baseStatus + " (Delinquent - " + dlqDays + " days)";
        }
        return baseStatus;
    }

    private String safeConcatName(String firstName, String lastName) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName : "[Unknown]";
        String last = (lastName != null && !lastName.isBlank()) ? lastName : "[Unknown]";
        return first + " " + last;
    }

    private String safeConcatName(String firstName, String lastName, String middle) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName : "[Unknown]";
        String last = (lastName != null && !lastName.isBlank()) ? lastName : "[Unknown]";
        return first + middle + " " + last;
    }

    private String buildPropertyAddress(LegacyLoanAccount acct) {
        StringBuilder sb = new StringBuilder();
        if (acct.getPropertyAddress() != null) sb.append(acct.getPropertyAddress());
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
        return sb.toString();
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

    private void logValidationWarnings(ValidationResult result, String entityType, String entityId) {
        if (result.hasWarnings()) {
            for (DataQualityWarning warning : result.getWarnings()) {
                if (warning.getSeverity() == DataQualityWarning.Severity.CRITICAL
                        || warning.getSeverity() == DataQualityWarning.Severity.HIGH) {
                    log.warn("Data quality issue in {} [{}]: {}", entityType, entityId, warning);
                } else {
                    log.info("Data quality note in {} [{}]: {}", entityType, entityId, warning);
                }
            }
        }
    }

    private List<String> toWarningStrings(ValidationResult result) {
        if (!result.hasWarnings()) return null;
        return result.getWarnings().stream()
                .map(DataQualityWarning::toString)
                .collect(Collectors.toList());
    }
}
