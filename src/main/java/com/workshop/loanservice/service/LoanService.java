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
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Service layer that reads from legacy tables and translates
 * cryptic legacy fields into clean DTOs.
 *
 * Data quality validation is applied at ingestion time via
 * {@link DataQualityValidator} to catch anomalies documented
 * in docs/DATA_ANOMALY_REPORT.md.
 */
@Service
public class LoanService {

    private static final DateTimeFormatter OUTPUT_DATE_FORMAT =
            DateTimeFormatter.ofPattern("MM/dd/yyyy");

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

        Set<String> validBorrowerIds = borrowerRepository.findAll()
                .stream()
                .map(LegacyBorrower::getBorrowerId)
                .collect(Collectors.toSet());

        Set<String> validProductCodes = products.keySet();

        return loanAccountRepository.findAll().stream()
                .map(acct -> {
                    validator.validateForeignKey(
                            acct.getBorrowerId(), validBorrowerIds,
                            "BORR_ID", "CDW_BORR_MSTR");
                    validator.validateForeignKey(
                            acct.getProductCode(), validProductCodes,
                            "PROD_CD", "CDW_LN_PROD");
                    return toLoanSummary(acct, products.get(acct.getProductCode()));
                })
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
        Set<String> validLoanIds = loanAccountRepository.findAll()
                .stream()
                .map(LegacyLoanAccount::getLoanAccountNumber)
                .collect(Collectors.toSet());

        List<PaymentDto> payments = paymentRepository
                .findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(pmt -> {
                    validator.validateForeignKey(
                            pmt.getLoanAccountNumber(), validLoanIds,
                            "LN_ACCT_NBR", "CDW_LN_ACCT");
                    return toPaymentDto(pmt);
                })
                .collect(Collectors.toList());

        payments.sort(Comparator.comparing(
                (PaymentDto p) -> {
                    LocalDate d = validator.parseDate(p.getPaymentDate(), "paymentDateSort");
                    return d != null ? d : LocalDate.MIN;
                }).reversed());

        return payments;
    }

    // =========================================================================
    // VALIDATED TRANSLATION METHODS
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());

        String firstName = validator.validateRequiredWithDefault(
                acct.getBorrowerFirstName(), "borrowerFirstName", "");
        String lastName = validator.validateRequiredWithDefault(
                acct.getBorrowerLastName(), "borrowerLastName", "");
        dto.setBorrowerName(validator.safeConcat(" ", firstName, lastName));

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());

        dto.setOriginalAmount(
                validator.parseAmountWithDefault(acct.getOriginalAmount(), "LN_ORIG_AMT", BigDecimal.ZERO));
        dto.setCurrentBalance(
                validator.parseAmountWithDefault(acct.getCurrentBalance(), "LN_CURR_BAL", BigDecimal.ZERO));
        dto.setInterestRate(
                validator.validateInterestRate(acct.getInterestRate()));
        dto.setMonthlyPayment(
                validator.parseAmountWithDefault(acct.getMonthlyPayment(), "LN_PMT_AMT", BigDecimal.ZERO));

        String statusCode = validator.validateLoanStatusCode(acct.getStatusCode());
        dto.setStatus(expandStatusCode(statusCode));

        LocalDate origDate = validator.parseDate(acct.getOriginationDate(), "LN_ORIG_DT");
        dto.setOriginationDate(origDate != null ? origDate.format(OUTPUT_DATE_FORMAT) : null);

        dto.setPropertyAddress(validator.safeConcat(", ",
                acct.getPropertyAddress(),
                acct.getPropertyCity(),
                validator.safeConcat(" ", acct.getPropertyState(), acct.getPropertyZip())));

        String propTypeCode = validator.validatePropertyTypeCode(acct.getPropertyType());
        dto.setPropertyType(expandPropertyType(propTypeCode));

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());

        String firstName = validator.validateRequiredWithDefault(
                borrower.getFirstName(), "BORR_FST_NM", "");
        String lastName = validator.validateRequiredWithDefault(
                borrower.getLastName(), "BORR_LST_NM", "");
        String middle = borrower.getMiddleInitial() != null
                ? borrower.getMiddleInitial() + "."
                : null;
        dto.setFullName(validator.safeConcat(" ", firstName, middle, lastName));

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());
        dto.setCreditScore(validator.validateCreditScore(borrower.getCreditScore()));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(pmt.getPaymentSequenceNumber());
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());

        LocalDate paymentDate = validator.parseDate(pmt.getPaymentDate(), "PMT_DT");
        dto.setPaymentDate(paymentDate != null ? paymentDate.format(OUTPUT_DATE_FORMAT) : null);

        BigDecimal total = validator.parseAmount(pmt.getTotalAmount(), "PMT_AMT");
        BigDecimal principal = validator.parseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT");
        BigDecimal interest = validator.parseAmount(pmt.getInterestAmount(), "PMT_INT_AMT");
        BigDecimal escrow = validator.parseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT");
        BigDecimal lateFee = validator.parseAmount(pmt.getLateFee(), "PMT_LATE_FEE");

        dto.setTotalAmount(total);
        dto.setPrincipalAmount(principal);
        dto.setInterestAmount(interest);
        dto.setEscrowAmount(escrow);
        dto.setLateFee(lateFee);

        validator.validatePaymentComponents(total, principal, interest, escrow, lateFee,
                pmt.getPaymentSequenceNumber());

        String typeCode = validator.validatePaymentTypeCode(pmt.getTypeCode());
        dto.setType(expandPaymentType(typeCode));

        String statusCode = validator.validatePaymentStatusCode(pmt.getStatusCode());
        dto.setStatus(expandPaymentStatus(statusCode));

        LocalDate receivedDate = validator.parseDate(pmt.getReceivedDate(), "PMT_RECV_DT");
        validator.validatePaymentDateOrder(paymentDate, receivedDate,
                pmt.getPaymentSequenceNumber());

        return dto;
    }

    // =========================================================================
    // STATUS CODE EXPANSION
    // =========================================================================

    private String expandStatusCode(String code) {
        if (code == null || "UNKNOWN".equals(code)) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> code;
        };
    }

    private String expandPropertyType(String code) {
        if (code == null || "UNKNOWN".equals(code)) return "Unknown";
        return switch (code) {
            case "SFR" -> "Single Family Residence";
            case "CND" -> "Condominium";
            case "MFR" -> "Multi-Family Residence";
            case "TWN" -> "Townhouse";
            default -> code;
        };
    }

    private String expandPaymentType(String code) {
        if (code == null || "UNKNOWN".equals(code)) return "Unknown";
        return switch (code) {
            case "REG" -> "Regular";
            case "EXT" -> "Extra";
            case "PRT" -> "Partial";
            case "PRE" -> "Prepayment";
            default -> code;
        };
    }

    private String expandPaymentStatus(String code) {
        if (code == null || "UNKNOWN".equals(code)) return "Unknown";
        return switch (code) {
            case "PST" -> "Posted";
            case "REV" -> "Reversed";
            case "NSF" -> "Non-Sufficient Funds";
            case "PND" -> "Pending";
            default -> code;
        };
    }

    public DataQualityValidator getValidator() {
        return validator;
    }
}
