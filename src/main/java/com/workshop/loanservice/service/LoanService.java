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
import com.workshop.loanservice.validation.DataQualityIssue;
import com.workshop.loanservice.validation.LegacyDataValidator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Service layer that reads from legacy tables and translates
 * cryptic legacy fields into clean DTOs.
 *
 * Includes data validation at ingestion time to catch anomalies
 * in the legacy CDW data before they cause runtime failures.
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
        List<DataQualityIssue> issues = validator.validateLoanAccount(acct);
        String id = acct.getLoanAccountNumber();

        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);
        dto.setBorrowerName(safeFullName(acct.getBorrowerFirstName(), acct.getBorrowerLastName()));
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(validator.safeParseAmount(
                acct.getOriginalAmount(), "CDW_LN_ACCT", "LN_ORIG_AMT", id, issues));
        dto.setCurrentBalance(validator.safeParseAmount(
                acct.getCurrentBalance(), "CDW_LN_ACCT", "LN_CURR_BAL", id, issues));
        dto.setInterestRate(validator.safeParseDecimal(
                acct.getInterestRate(), "CDW_LN_ACCT", "LN_INT_RT", id, issues));
        dto.setMonthlyPayment(validator.safeParseAmount(
                acct.getMonthlyPayment(), "CDW_LN_ACCT", "LN_PMT_AMT", id, issues));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(safeFormatDate(acct.getOriginationDate(), id));
        dto.setPropertyAddress(safePropertyAddress(acct));
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        if (!issues.isEmpty()) {
            dto.setDataQualityWarnings(issues.stream()
                    .map(DataQualityIssue::getDescription)
                    .collect(Collectors.toList()));
        }

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        List<DataQualityIssue> issues = validator.validateBorrower(borrower);
        String id = borrower.getBorrowerId();

        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(safeFullName(borrower.getFirstName(), borrower.getLastName()) + middle);
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(validator.safeParseInteger(
                borrower.getCreditScore(), "CDW_BORR_MSTR", "BORR_CRDT_SCR", id, issues));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        List<DataQualityIssue> issues = validator.validatePayment(pmt);
        String id = pmt.getPaymentSequenceNumber();

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(safeFormatDate(pmt.getPaymentDate(), id));
        dto.setTotalAmount(validator.safeParseAmount(
                pmt.getTotalAmount(), "CDW_PMT_HIST", "PMT_AMT", id, issues));
        dto.setPrincipalAmount(validator.safeParseAmount(
                pmt.getPrincipalAmount(), "CDW_PMT_HIST", "PMT_PRIN_AMT", id, issues));
        dto.setInterestAmount(validator.safeParseAmount(
                pmt.getInterestAmount(), "CDW_PMT_HIST", "PMT_INT_AMT", id, issues));
        dto.setEscrowAmount(validator.safeParseAmount(
                pmt.getEscrowAmount(), "CDW_PMT_HIST", "PMT_ESCROW_AMT", id, issues));
        dto.setLateFee(validator.safeParseAmount(
                pmt.getLateFee(), "CDW_PMT_HIST", "PMT_LATE_FEE", id, issues));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));

        return dto;
    }

    // =========================================================================
    // SAFE HELPER METHODS
    // =========================================================================

    private String safeFullName(String firstName, String lastName) {
        String first = (firstName != null && !firstName.isBlank()) ? firstName.trim() : "Unknown";
        String last = (lastName != null && !lastName.isBlank()) ? lastName.trim() : "Unknown";
        return first + " " + last;
    }

    private String safePropertyAddress(LegacyLoanAccount acct) {
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
        return sb.length() > 0 ? sb.toString() : "Address not available";
    }

    private String safeFormatDate(String legacyDate, String recordId) {
        if (legacyDate == null || legacyDate.isBlank()) {
            return null;
        }
        List<DataQualityIssue> issues = new ArrayList<>();
        LocalDate parsed = validator.safeParseDate(
                legacyDate, "LEGACY", "DATE_FIELD", recordId, issues);
        if (parsed != null) {
            return parsed.format(DateTimeFormatter.ISO_LOCAL_DATE);
        }
        return legacyDate;
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
