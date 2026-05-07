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

        List<LoanSummaryDto> results = new ArrayList<>();
        for (LegacyLoanAccount acct : loanAccountRepository.findAll()) {
            LegacyBorrower borrower = borrowers.get(acct.getBorrowerId());
            ValidationResult vr = validator.validateLoanAccount(acct, borrower);
            if (vr.hasErrors()) {
                log.error("Skipping loan {} due to validation errors", acct.getLoanAccountNumber());
                continue;
            }
            results.add(toLoanSummary(acct, products.get(acct.getProductCode())));
        }
        return results;
    }

    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
                .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
        LegacyBorrower borrower = borrowerRepository.findById(acct.getBorrowerId()).orElse(null);
        ValidationResult vr = validator.validateLoanAccount(acct, borrower);
        if (vr.hasErrors()) {
            log.warn("Loan {} has validation errors but returning with warnings",
                    loanAccountNumber);
        }
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        return toLoanSummary(acct, product);
    }

    public List<BorrowerDto> getAllBorrowers() {
        List<BorrowerDto> results = new ArrayList<>();
        for (LegacyBorrower borrower : borrowerRepository.findAll()) {
            ValidationResult vr = validator.validateBorrower(borrower);
            if (vr.hasErrors()) {
                log.error("Skipping borrower {} due to validation errors",
                        borrower.getBorrowerId());
                continue;
            }
            results.add(toBorrowerDto(borrower));
        }
        return results;
    }

    public BorrowerDto getBorrowerById(String borrowerId) {
        LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
                .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
        validator.validateBorrower(borrower);
        BorrowerDto dto = toBorrowerDto(borrower);

        Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
        Map<String, LegacyBorrower> borrowers = borrowerRepository.findAll()
                .stream()
                .collect(Collectors.toMap(LegacyBorrower::getBorrowerId, b -> b));

        List<LoanSummaryDto> loans = new ArrayList<>();
        for (LegacyLoanAccount acct : loanAccountRepository.findByBorrowerId(borrowerId)) {
            LegacyBorrower acctBorrower = borrowers.get(acct.getBorrowerId());
            ValidationResult vr = validator.validateLoanAccount(acct, acctBorrower);
            if (vr.hasErrors()) {
                log.error("Skipping loan {} for borrower {} due to validation errors",
                        acct.getLoanAccountNumber(), borrowerId);
                continue;
            }
            loans.add(toLoanSummary(acct, products.get(acct.getProductCode())));
        }
        dto.setLoans(loans);

        return dto;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        List<PaymentDto> results = new ArrayList<>();
        for (LegacyPayment pmt : paymentRepository
                .findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)) {
            ValidationResult vr = validator.validatePayment(pmt);
            if (vr.hasErrors()) {
                log.warn("Payment {} has validation errors — including with warnings",
                        pmt.getPaymentSequenceNumber());
            }
            results.add(toPaymentDto(pmt));
        }
        return results;
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // These methods handle the messy conversion from legacy string fields
    // to proper types. After migration, these should be simplified or removed.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(acct.getLoanAccountNumber());
        dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
        dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
        dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
        dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
        dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
        dto.setStatus(expandStatusCode(acct.getStatusCode()));
        dto.setOriginationDate(acct.getOriginationDate());
        dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
                + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
        dto.setPropertyType(expandPropertyType(acct.getPropertyType()));
        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        BorrowerDto dto = new BorrowerDto();
        dto.setId(borrower.getBorrowerId());
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
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
        dto.setPaymentDate(pmt.getPaymentDate());
        dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
        dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
        dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
        dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
        dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
        dto.setType(expandPaymentType(pmt.getTypeCode()));
        dto.setStatus(expandPaymentStatus(pmt.getStatusCode()));
        return dto;
    }

    /**
     * Parse legacy amount strings like "285,000" or "1,487.02" into BigDecimal.
     * Strips commas, dollar signs, and whitespace. Returns ZERO with a warning log
     * for null/blank inputs, and catches NumberFormatException for malformed values.
     */
    BigDecimal parseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) {
            log.warn("Null or blank amount field — defaulting to ZERO");
            return BigDecimal.ZERO;
        }
        try {
            String cleaned = amount.replace(",", "").trim();
            if (cleaned.startsWith("$")) {
                cleaned = cleaned.substring(1);
            }
            if (cleaned.startsWith("(") && cleaned.endsWith(")")) {
                cleaned = "-" + cleaned.substring(1, cleaned.length() - 1);
            }
            return new BigDecimal(cleaned);
        } catch (NumberFormatException e) {
            log.error("Failed to parse amount '{}' — defaulting to ZERO", amount);
            return BigDecimal.ZERO;
        }
    }

    BigDecimal parseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) {
            log.warn("Null or blank decimal field — defaulting to ZERO");
            return BigDecimal.ZERO;
        }
        try {
            return new BigDecimal(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.error("Failed to parse decimal '{}' — defaulting to ZERO", value);
            return BigDecimal.ZERO;
        }
    }

    Integer parseLegacyInteger(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return Integer.parseInt(value.replace(",", "").trim());
        } catch (NumberFormatException e) {
            log.error("Failed to parse integer '{}' — returning null", value);
            return null;
        }
    }

    String expandStatusCode(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "ACT" -> "Active";
            case "CLO" -> "Closed";
            case "DFT" -> "Default";
            case "FRB" -> "Forbearance";
            default -> {
                log.warn("Unrecognized loan status code '{}' — passing through", code);
                yield code;
            }
        };
    }

    String expandPropertyType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "SFR" -> "Single Family Residence";
            case "CND" -> "Condominium";
            case "MFR" -> "Multi-Family Residence";
            case "TWN" -> "Townhouse";
            default -> {
                log.warn("Unrecognized property type code '{}' — passing through", code);
                yield code;
            }
        };
    }

    String expandPaymentType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "REG" -> "Regular";
            case "EXT" -> "Extra";
            case "PRT" -> "Partial";
            case "PRE" -> "Prepayment";
            default -> {
                log.warn("Unrecognized payment type code '{}' — passing through", code);
                yield code;
            }
        };
    }

    String expandPaymentStatus(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "PST" -> "Posted";
            case "REV" -> "Reversed";
            case "NSF" -> "Non-Sufficient Funds";
            case "PND" -> "Pending";
            default -> {
                log.warn("Unrecognized payment status code '{}' — passing through", code);
                yield code;
            }
        };
    }
}
