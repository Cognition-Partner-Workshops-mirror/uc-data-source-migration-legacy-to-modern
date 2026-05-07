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

        return loanAccountRepository.findAll().stream()
                .map(acct -> toLoanSummary(acct,
                        products.get(acct.getProductCode()),
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
        Map<String, LegacyBorrower> borrowers = borrowerRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyBorrower::getBorrowerId, b -> b));
        List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
                .stream()
                .map(acct -> toLoanSummary(acct,
                        products.get(acct.getProductCode()),
                        borrowers.get(acct.getBorrowerId())))
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

        warnings.addAll(validator.validateLoanAccount(acct));

        if (masterBorrower != null) {
            warnings.addAll(validator.validateDenormalizedBorrowerData(acct, masterBorrower));
        } else if (acct.getBorrowerId() != null) {
            warnings.add(DataQualityWarning.critical("borrowerId",
                    "Orphaned loan — borrower '" + acct.getBorrowerId()
                            + "' not found in CDW_BORR_MSTR"));
        }

        if (product == null && acct.getProductCode() != null && !acct.getProductCode().isBlank()) {
            warnings.add(DataQualityWarning.high("productCode",
                    "Orphaned loan — product '" + acct.getProductCode()
                            + "' not found in CDW_LN_PROD"));
        }

        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());

        String firstName = acct.getBorrowerFirstName() != null ? acct.getBorrowerFirstName() : "";
        String lastName = acct.getBorrowerLastName() != null ? acct.getBorrowerLastName() : "";
        dto.setBorrowerName((firstName + " " + lastName).trim());

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(validator.parseAmount(acct.getOriginalAmount(), "originalAmount", warnings));
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), "currentBalance", warnings));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), "interestRate", warnings));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), "monthlyPayment", warnings));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(validator.parseDate(acct.getOriginationDate(), "originationDate", warnings));

        String propAddr = acct.getPropertyAddress() != null ? acct.getPropertyAddress() : "";
        String propCity = acct.getPropertyCity() != null ? acct.getPropertyCity() : "";
        String propState = acct.getPropertyState() != null ? acct.getPropertyState() : "";
        String propZip = acct.getPropertyZip() != null ? acct.getPropertyZip() : "";
        dto.setPropertyAddress((propAddr + ", " + propCity + ", " + propState + " " + propZip).trim());

        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        dto.setDataQualityWarnings(warnings);

        if (!warnings.isEmpty()) {
            log.info("Loan {} has {} data quality warnings", acct.getLoanAccountNumber(), warnings.size());
        }

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        List<DataQualityWarning> warnings = new ArrayList<>();

        warnings.addAll(validator.validateBorrower(borrower));

        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());

        String first = borrower.getFirstName() != null ? borrower.getFirstName() : "";
        String last = borrower.getLastName() != null ? borrower.getLastName() : "";
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName((first + middle + " " + last).trim());

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(validator.parseInteger(borrower.getCreditScore(), "creditScore", warnings));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());
        dto.setDataQualityWarnings(warnings);

        if (!warnings.isEmpty()) {
            log.info("Borrower {} has {} data quality warnings", borrower.getBorrowerId(), warnings.size());
        }

        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        List<DataQualityWarning> warnings = new ArrayList<>();

        warnings.addAll(validator.validatePayment(pmt));

        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());
        dto.setPaymentDate(validator.parseDate(pmt.getPaymentDate(), "paymentDate", warnings));

        BigDecimal total = validator.parseAmount(pmt.getTotalAmount(), "totalAmount", warnings);
        BigDecimal principal = validator.parseAmount(pmt.getPrincipalAmount(), "principalAmount", warnings);
        BigDecimal interest = validator.parseAmount(pmt.getInterestAmount(), "interestAmount", warnings);
        BigDecimal escrow = validator.parseAmount(pmt.getEscrowAmount(), "escrowAmount", warnings);
        BigDecimal late = validator.parseAmount(pmt.getLateFee(), "lateFee", warnings);

        dto.setTotalAmount(total);
        dto.setPrincipalAmount(principal);
        dto.setInterestAmount(interest);
        dto.setEscrowAmount(escrow);
        dto.setLateFee(late);

        warnings.addAll(validator.validatePaymentComponents(total, principal, interest, escrow, late));
        warnings.addAll(validator.validatePaymentDates(
                pmt.getPaymentDate(), pmt.getReceivedDate(), pmt.getProcessedDate()));

        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        dto.setDataQualityWarnings(warnings);

        if (!warnings.isEmpty()) {
            log.info("Payment {} has {} data quality warnings", pmt.getPaymentSequenceNumber(), warnings.size());
        }

        return dto;
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
