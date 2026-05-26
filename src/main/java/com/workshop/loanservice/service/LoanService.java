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
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Service layer that reads from legacy tables and translates
 * cryptic legacy fields into clean DTOs.
 *
 * Data validation is delegated to {@link LegacyDataValidator} which catches
 * the anomalies documented in docs/DATA_ANOMALY_REPORT.md at ingestion time.
 * Safe parsing helpers in the validator prevent NumberFormatException and
 * null-literal issues (ANM-003, ANM-004).
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

        // Build a borrower lookup for cross-validation (ANM-001, ANM-005, ANM-008)
        Map<String, LegacyBorrower> borrowers = borrowerRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyBorrower::getBorrowerId, b -> b));

        return loanAccountRepository.findAll().stream()
                .map(acct -> {
                    LegacyBorrower borrower = borrowers.get(acct.getBorrowerId());
                    // Validate the loan account against its borrower (ANM-001 through ANM-009)
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

        // Validate with borrower lookup for cross-field checks
        LegacyBorrower borrower = borrowerRepository.findById(acct.getBorrowerId()).orElse(null);
        validator.validateLoanAccount(acct, borrower);

        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        return borrowerRepository.findAll().stream()
                .map(b -> {
                    // Validate each borrower record at ingestion time (ANM-003, ANM-004, ANM-007, ANM-009)
                    validator.validateBorrower(b);
                    return toBorrowerDto(b);
                })
                .collect(Collectors.toList());
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));

        // Validate the borrower record
        validator.validateBorrower(borrower);

        BorrowerDto dto = toBorrowerDto(borrower);

        // Attach loans for this borrower
        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> {
                    // Validate each loan as it is loaded (ANM-001 through ANM-009)
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
                    // Validate each payment for component-sum consistency (ANM-002) and other checks
                    validator.validatePayment(pmt);
                    return toPaymentDto(pmt);
                })
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods now use the validator's safe-parsing helpers to avoid
    // NumberFormatException (ANM-004) and null-literal issues (ANM-003).
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());

        // ANM-003: null-safe name concatenation — use validator.safeString() to prevent "null null"
        String firstName = validator.safeString(acct.getBorrowerFirstName(), "[Unknown]");
        String lastName = validator.safeString(acct.getBorrowerLastName(), "[Unknown]");
        dto.setBorrowerName(firstName + " " + lastName);

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());

        // ANM-004: use validator's safe parsing to prevent NumberFormatException
        dto.setOriginalAmount(validator.safeParseAmount(acct.getOriginalAmount()));
        dto.setCurrentBalance(validator.safeParseAmount(acct.getCurrentBalance()));
        dto.setInterestRate(validator.safeParseDecimal(acct.getInterestRate()));
        dto.setMonthlyPayment(validator.safeParseAmount(acct.getMonthlyPayment()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(acct.getOriginationDate());

        // ANM-003: null-safe property address assembly
        String propAddr = validator.safeString(acct.getPropertyAddress(), "");
        String propCity = validator.safeString(acct.getPropertyCity(), "");
        String propState = validator.safeString(acct.getPropertyState(), "");
        String propZip = validator.safeString(acct.getPropertyZip(), "");
        dto.setPropertyAddress(propAddr + ", " + propCity + ", " + propState + " " + propZip);

        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());

        // ANM-003: null-safe name concatenation — prevent "null R. null" in the API response
        String first = validator.safeString(borrower.getFirstName(), "[Unknown]");
        String last = validator.safeString(borrower.getLastName(), "[Unknown]");
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(first + middle + " " + last);

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        // ANM-004: use validator's safe integer parsing to prevent NumberFormatException
        dto.setCreditScore(validator.safeParseInteger(borrower.getCreditScore()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(pmt.getPaymentDate());

        // ANM-004: use validator's safe parsing for all amount fields
        dto.setTotalAmount(validator.safeParseAmount(pmt.getTotalAmount()));
        dto.setPrincipalAmount(validator.safeParseAmount(pmt.getPrincipalAmount()));
        dto.setInterestAmount(validator.safeParseAmount(pmt.getInterestAmount()));
        dto.setEscrowAmount(validator.safeParseAmount(pmt.getEscrowAmount()));
        dto.setLateFee(validator.safeParseAmount(pmt.getLateFee()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    // ANM-009: status expansion methods log unrecognized codes instead of silently passing them through
    private String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> {
                log.warn("Unrecognized loan status code: '{}'", code);
                yield "Unknown(" + code + ")";
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
                yield "Unknown(" + code + ")";
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
                yield "Unknown(" + code + ")";
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
                yield "Unknown(" + code + ")";
            }
        };
    }
}
