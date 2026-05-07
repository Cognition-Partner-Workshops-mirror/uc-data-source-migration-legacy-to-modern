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
import com.workshop.loanservice.validation.ValidationResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
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

        Set<String> validBorrowerIds = borrowers.keySet();
        Set<String> validProductCodes = products.keySet();

        return loanAccountRepository.findAll().stream()
                .map(acct -> {
                    ValidationResult vr = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
                    LegacyBorrower borrower = borrowers.get(acct.getBorrowerId());
                    if (borrower != null) {
                        vr.merge(validator.validateLoanAccountDenormalizedData(acct, borrower));
                    }
                    logValidationWarnings(vr);
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
                .collect(Collectors.toList());
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);

        Set<String> validBorrowerIds = borrowerRepository.findAll().stream()
                .map(LegacyBorrower::getBorrowerId)
                .collect(Collectors.toSet());
        Set<String> validProductCodes = loanProductRepository.findAll().stream()
                .map(LegacyLoanProduct::getProductCode)
                .collect(Collectors.toSet());

        ValidationResult vr = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
        LegacyBorrower borrower = acct.getBorrowerId() != null
                ? borrowerRepository.findById(acct.getBorrowerId()).orElse(null)
                : null;
        if (borrower != null) {
            vr.merge(validator.validateLoanAccountDenormalizedData(acct, borrower));
        }
        logValidationWarnings(vr);

        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .map(borrower -> {
                    ValidationResult vr = validator.validateBorrower(borrower);
                    logValidationWarnings(vr);
                    return toBorrowerDto(borrower);
                })
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));

        ValidationResult vr = validator.validateBorrower(borrower);
        logValidationWarnings(vr);

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
        Set<String> validLoanAccountNumbers = loanAccountRepository.findAll().stream()
                .map(LegacyLoanAccount::getLoanAccountNumber)
                .collect(Collectors.toSet());

        return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(pmt -> {
                    ValidationResult vr = validator.validatePayment(pmt, validLoanAccountNumbers);
                    logValidationWarnings(vr);
                    return toPaymentDto(pmt);
                })
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());
        dto.setBorrowerName(Objects.toString(acct.getBorrowerFirstName(), "")
                + " " + Objects.toString(acct.getBorrowerLastName(), ""));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
        dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
        dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
        dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(validator.safeFormatDate(acct.getOriginationDate()));
        dto.setPropertyAddress(buildPropertyAddress(acct));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private String buildPropertyAddress(LegacyLoanAccount acct) {
        StringBuilder sb = new StringBuilder();
        if (acct.getPropertyAddress() != null) sb.append(acct.getPropertyAddress());
        if (acct.getPropertyCity() != null) sb.append(", ").append(acct.getPropertyCity());
        if (acct.getPropertyState() != null) sb.append(", ").append(acct.getPropertyState());
        if (acct.getPropertyZip() != null) sb.append(" ").append(acct.getPropertyZip());
        return sb.toString();
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(Objects.toString(borrower.getFirstName(), "")
                + middle + " " + Objects.toString(borrower.getLastName(), ""));
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
        dto.setPaymentDate(validator.safeFormatDate(pmt.getPaymentDate()));
        dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
        dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
        dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
        dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
        dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    private BigDecimal parseLegacyAmount(String amount) {
        return validator.safeParseAmount(amount);
    }

    private BigDecimal parseLegacyDecimal(String value) {
        return validator.safeParseDecimal(value);
    }

    private Integer parseLegacyInteger(String value) {
        return validator.safeParseInteger(value);
    }

    private String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> {
                log.warn("Unrecognized loan status code: '{}'", code);
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
                log.warn("Unrecognized property type code: '{}'", code);
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
                log.warn("Unrecognized payment type code: '{}'", code);
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
                log.warn("Unrecognized payment status code: '{}'", code);
                yield code;
            }
        };
    }

    private void logValidationWarnings(ValidationResult result) {
        if (!result.hasWarnings()) {
            return;
        }
        for (ValidationResult.ValidationWarning w : result.getWarnings()) {
            switch (w.severity()) {
                case CRITICAL -> log.error("[DATA_QUALITY] {} | table={} record={} field={} value='{}' | {}",
                        w.severity(), w.table(), w.recordId(), w.field(), w.rawValue(), w.message());
                case HIGH -> log.warn("[DATA_QUALITY] {} | table={} record={} field={} value='{}' | {}",
                        w.severity(), w.table(), w.recordId(), w.field(), w.rawValue(), w.message());
                default -> log.info("[DATA_QUALITY] {} | table={} record={} field={} value='{}' | {}",
                        w.severity(), w.table(), w.recordId(), w.field(), w.rawValue(), w.message());
            }
        }
    }
}
