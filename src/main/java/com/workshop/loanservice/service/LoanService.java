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
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Service layer that reads from legacy tables and translates
 * cryptic legacy fields into clean DTOs.
 *
 * Data quality validation is applied during translation to catch
 * anomalies at ingestion time rather than letting them propagate
 * to API consumers as runtime errors or silent data corruption.
 */
@Service
public class LoanService {

    private static final Logger log = LoggerFactory.getLogger(LoanService.class);
    private static final DateTimeFormatter ISO_DATE = DateTimeFormatter.ISO_LOCAL_DATE;

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
        List<PaymentDto> payments = paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(this::toPaymentDto)
                .collect(Collectors.toList());

        // Re-sort by parsed date (chronological descending) to fix lexicographic VARCHAR sorting
        payments.sort(Comparator.comparing(
                (PaymentDto p) -> parsePaymentDateForSort(p.getPaymentDate()),
                Comparator.nullsLast(Comparator.reverseOrder())));

        return payments;
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS — with data quality validation
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String id = acct.getLoanAccountNumber();
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);

        // Validate required fields and build borrower name safely
        String firstName = acct.getBorrowerFirstName();
        String lastName = acct.getBorrowerLastName();
        if (!DataQualityValidator.isRequiredFieldPresent(firstName, "borrowerFirstName", id)) {
            dto.addDataQualityWarning("Missing borrower first name");
            firstName = "Unknown";
        }
        if (!DataQualityValidator.isRequiredFieldPresent(lastName, "borrowerLastName", id)) {
            dto.addDataQualityWarning("Missing borrower last name");
            lastName = "Unknown";
        }
        dto.setBorrowerName(firstName + " " + lastName);

        // Product validation
        if (product != null) {
            dto.setProductDescription(product.getDescription());
        } else {
            dto.setProductDescription(acct.getProductCode());
            dto.addDataQualityWarning("Product code '" + acct.getProductCode() + "' not found in product table (orphaned reference)");
        }

        // Validated numeric parsing
        dto.setOriginalAmount(DataQualityValidator.parseAmount(acct.getOriginalAmount(), "originalAmount", id));
        dto.setCurrentBalance(DataQualityValidator.parseAmount(acct.getCurrentBalance(), "currentBalance", id));
        dto.setInterestRate(DataQualityValidator.parseDecimal(acct.getInterestRate(), "interestRate", id));
        dto.setMonthlyPayment(DataQualityValidator.parseAmount(acct.getMonthlyPayment(), "monthlyPayment", id));

        if (dto.getOriginalAmount() == null) dto.addDataQualityWarning("Unparseable original amount: " + acct.getOriginalAmount());
        if (dto.getCurrentBalance() == null) dto.addDataQualityWarning("Unparseable current balance: " + acct.getCurrentBalance());
        if (dto.getInterestRate() == null) dto.addDataQualityWarning("Unparseable interest rate: " + acct.getInterestRate());
        if (dto.getMonthlyPayment() == null) dto.addDataQualityWarning("Unparseable monthly payment: " + acct.getMonthlyPayment());

        // Status validation
        DataQualityValidator.isValidStatusCode(acct.getStatusCode(),
                DataQualityValidator.getValidLoanStatuses(), "loanStatus", id);
        dto.setStatus(expandStatusCode(acct.getStatusCode()));

        // Date validation — parse and normalize to ISO format
        LocalDate origDate = DataQualityValidator.parseDate(acct.getOriginationDate(), "originationDate", id);
        if (origDate != null) {
            dto.setOriginationDate(origDate.format(ISO_DATE));
        } else {
            dto.setOriginationDate(acct.getOriginationDate());
            if (acct.getOriginationDate() != null && !acct.getOriginationDate().isBlank()) {
                dto.addDataQualityWarning("Unparseable origination date: " + acct.getOriginationDate());
            }
        }

        // Property address with null safety
        String propAddr = safeString(acct.getPropertyAddress());
        String propCity = safeString(acct.getPropertyCity());
        String propState = safeString(acct.getPropertyState());
        String propZip = safeString(acct.getPropertyZip());
        dto.setPropertyAddress(propAddr + ", " + propCity + ", " + propState + " " + propZip);
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));

        // Business rule validation
        List<String> statusWarnings = DataQualityValidator.validateLoanStatusConsistency(
                acct.getStatusCode(), acct.getDelinquencyDays(), id);
        statusWarnings.forEach(dto::addDataQualityWarning);

        List<String> ltvWarnings = DataQualityValidator.validateLtvPercent(acct.getLtvPercent(), id);
        ltvWarnings.forEach(dto::addDataQualityWarning);

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();
        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);

        // Validate required name fields
        String first = borrower.getFirstName();
        String last = borrower.getLastName();
        if (!DataQualityValidator.isRequiredFieldPresent(first, "firstName", id)) {
            dto.addDataQualityWarning("Missing first name");
            first = "Unknown";
        }
        if (!DataQualityValidator.isRequiredFieldPresent(last, "lastName", id)) {
            dto.addDataQualityWarning("Missing last name");
            last = "Unknown";
        }

        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(first + middle + " " + last);
        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        // Validated credit score
        Integer creditScore = DataQualityValidator.validateCreditScore(borrower.getCreditScore(), id);
        dto.setCreditScore(creditScore);
        if (creditScore == null && borrower.getCreditScore() != null && !borrower.getCreditScore().isBlank()) {
            dto.addDataQualityWarning("Unparseable credit score: " + borrower.getCreditScore());
        }

        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        // Parse and expose annual income (was previously dropped)
        BigDecimal income = DataQualityValidator.parseAmount(borrower.getAnnualIncome(), "annualIncome", id);
        dto.setAnnualIncome(income);
        if (income == null && borrower.getAnnualIncome() != null && !borrower.getAnnualIncome().isBlank()) {
            dto.addDataQualityWarning("Unparseable annual income: " + borrower.getAnnualIncome());
        }

        // Validate borrower status
        DataQualityValidator.isValidStatusCode(borrower.getStatusCode(),
                DataQualityValidator.getValidBorrowerStatuses(), "borrowerStatus", id);

        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String id = pmt.getPaymentSequenceNumber();
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());

        // Date validation — parse and normalize
        LocalDate pmtDate = DataQualityValidator.parseDate(pmt.getPaymentDate(), "paymentDate", id);
        if (pmtDate != null) {
            dto.setPaymentDate(pmtDate.format(ISO_DATE));
        } else {
            dto.setPaymentDate(pmt.getPaymentDate());
            if (pmt.getPaymentDate() != null && !pmt.getPaymentDate().isBlank()) {
                dto.addDataQualityWarning("Unparseable payment date: " + pmt.getPaymentDate());
            }
        }

        // Validated numeric parsing
        BigDecimal total = DataQualityValidator.parseAmount(pmt.getTotalAmount(), "totalAmount", id);
        BigDecimal principal = DataQualityValidator.parseAmount(pmt.getPrincipalAmount(), "principalAmount", id);
        BigDecimal interest = DataQualityValidator.parseAmount(pmt.getInterestAmount(), "interestAmount", id);
        BigDecimal escrow = DataQualityValidator.parseAmount(pmt.getEscrowAmount(), "escrowAmount", id);
        BigDecimal lateFee = DataQualityValidator.parseAmount(pmt.getLateFee(), "lateFee", id);

        dto.setTotalAmount(total);
        dto.setPrincipalAmount(principal);
        dto.setInterestAmount(interest);
        dto.setEscrowAmount(escrow);
        dto.setLateFee(lateFee);

        // Payment integrity check — components must sum to total
        List<String> integrityWarnings = DataQualityValidator.validatePaymentIntegrity(
                total, principal, interest, escrow, lateFee, id);
        integrityWarnings.forEach(dto::addDataQualityWarning);

        // Status and type validation
        DataQualityValidator.isValidStatusCode(pmt.getStatusCode(),
                DataQualityValidator.getValidPaymentStatuses(), "paymentStatus", id);
        DataQualityValidator.isValidStatusCode(pmt.getTypeCode(),
                DataQualityValidator.getValidPaymentTypes(), "paymentType", id);

        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    // =========================================================================
    // HELPER METHODS
    // =========================================================================

    private LocalDate parsePaymentDateForSort(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        try {
            return LocalDate.parse(dateStr, ISO_DATE);
        } catch (Exception e) {
            return null;
        }
    }

    private String safeString(String value) {
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
