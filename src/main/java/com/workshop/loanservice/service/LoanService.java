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
 * Data validation is now performed via LegacyDataValidator to catch
 * known CDW anomalies (malformed numerics, nulls, date issues) at
 * ingestion time rather than propagating bad data to API consumers.
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
        return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(this::toPaymentDto)
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. Validation is performed via LegacyDataValidator to
    // catch anomalies at ingestion time. After migration, these should be
    // simplified or removed.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String loanId = acct.getLoanAccountNumber();
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(loanId);

        // Null-safe borrower name construction — avoids "null" literal in output
        String firstName = validator.safeString(acct.getBorrowerFirstName());
        String lastName = validator.safeString(acct.getBorrowerLastName());
        dto.setBorrowerName((firstName + " " + lastName).trim());

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());

        // Validated numeric parsing with error handling and logging
        dto.setOriginalAmount(validator.parseAmount(acct.getOriginalAmount(), "LN_ORIG_AMT", loanId));
        dto.setCurrentBalance(validator.parseAmount(acct.getCurrentBalance(), "LN_CURR_BAL", loanId));
        dto.setInterestRate(validator.parseDecimal(acct.getInterestRate(), "LN_INT_RT", loanId));
        dto.setMonthlyPayment(validator.parseAmount(acct.getMonthlyPayment(), "LN_PMT_AMT", loanId));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));

        // Validated date parsing
        String originationDate = validator.parseAndValidateDate(
                acct.getOriginationDate(), "LN_ORIG_DT", loanId);
        dto.setOriginationDate(originationDate != null ? originationDate : acct.getOriginationDate());

        // Null-safe property address construction
        String addr = validator.safeString(acct.getPropertyAddress());
        String city = validator.safeString(acct.getPropertyCity());
        String state = validator.safeString(acct.getPropertyState());
        String zip = validator.safeString(acct.getPropertyZip());
        dto.setPropertyAddress(buildAddress(addr, city, state, zip));

        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        // Cross-field validation: delinquency days vs. status consistency
        validator.validateLoanStatusConsistency(loanId, acct.getStatusCode(), acct.getDelinquencyDays());

        // Referential integrity check: borrower and product references
        validator.validateReferenceNotEmpty(acct.getBorrowerId(), "BORR_ID", loanId);
        validator.validateReferenceNotEmpty(acct.getProductCode(), "PROD_CD", loanId);

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String borrowerId = borrower.getBorrowerId();
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrowerId);

        // Null-safe full name construction
        String firstName = validator.safeString(borrower.getFirstName());
        String middleInitial = borrower.getMiddleInitial();
        String lastName = validator.safeString(borrower.getLastName());
        String middle = (middleInitial != null && !middleInitial.isBlank())
                ? " " + middleInitial + "." : "";
        dto.setFullName((firstName + middle + " " + lastName).trim());

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        // Validated integer parsing for credit score
        dto.setCreditScore(validator.parseInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", borrowerId));
        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        // Validate date fields
        validator.parseAndValidateDate(borrower.getDateOfBirth(), "BORR_DOB_DT", borrowerId);
        validator.parseAndValidateDate(borrower.getCreatedDate(), "BORR_CRET_DT", borrowerId);

        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String paymentId = pmt.getPaymentSequenceNumber();
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(paymentId);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());

        // Validated date parsing for payment date
        String paymentDate = validator.parseAndValidateDate(
                pmt.getPaymentDate(), "PMT_DT", paymentId);
        dto.setPaymentDate(paymentDate != null ? paymentDate : pmt.getPaymentDate());

        // Validated amount parsing with error handling
        BigDecimal total = validator.parseAmount(pmt.getTotalAmount(), "PMT_AMT", paymentId);
        BigDecimal principal = validator.parseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", paymentId);
        BigDecimal interest = validator.parseAmount(pmt.getInterestAmount(), "PMT_INT_AMT", paymentId);
        BigDecimal escrow = validator.parseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", paymentId);
        BigDecimal lateFee = validator.parseAmount(pmt.getLateFee(), "PMT_LATE_FEE", paymentId);

        dto.setTotalAmount(total);
        dto.setPrincipalAmount(principal);
        dto.setInterestAmount(interest);
        dto.setEscrowAmount(escrow);
        dto.setLateFee(lateFee);

        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));

        // Cross-field validation: payment components should sum to total
        validator.validatePaymentIntegrity(paymentId, total, principal, interest, escrow, lateFee);

        // Referential integrity check: loan account reference
        validator.validateReferenceNotEmpty(pmt.getLoanAccountNumber(), "LN_ACCT_NBR", paymentId);

        return dto;
    }

    /**
     * Builds a formatted address string from components, handling null/empty values gracefully.
     */
    private String buildAddress(String address, String city, String state, String zip) {
        StringBuilder sb = new StringBuilder();
        if (!address.isEmpty()) sb.append(address);
        if (!city.isEmpty()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(city);
        }
        if (!state.isEmpty()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(state);
        }
        if (!zip.isEmpty()) {
            if (sb.length() > 0) sb.append(" ");
            sb.append(zip);
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
}
