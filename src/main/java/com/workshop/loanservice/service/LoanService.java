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
 * All legacy string fields are validated and parsed using LegacyDataValidator
 * to catch known data quality anomalies (see docs/DATA_ANOMALY_REPORT.md).
 */
@Service
public class LoanService {

    private static final Logger log = LoggerFactory.getLogger(LoanService.class);

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

        // Validate referential integrity for product code (ANO-003)
        LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
                .orElse(null);
        if (product == null) {
            log.error("Orphaned product reference: loan '{}' references product code '{}' which does not exist (ANO-003)",
                    loanAccountNumber, acct.getProductCode());
        }

        // Validate referential integrity for borrower ID (ANO-003)
        if (acct.getBorrowerId() != null && borrowerRepository.findById(acct.getBorrowerId()).isEmpty()) {
            log.error("Orphaned borrower reference: loan '{}' references borrower '{}' which does not exist (ANO-003)",
                    loanAccountNumber, acct.getBorrowerId());
        }

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
        // Validate referential integrity: check that the loan account exists (ANO-003)
        if (loanAccountRepository.findById(loanAccountNumber).isEmpty()) {
            log.error("Payment query for non-existent loan account '{}' (ANO-003)", loanAccountNumber);
        }

        return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
                .stream()
                .map(this::toPaymentDto)
                .collect(Collectors.toList());
    }

    // =========================================================================
    // LEGACY TRANSLATION METHODS
    // All parsing now routes through LegacyDataValidator for safe type coercion,
    // error handling, and anomaly logging.
    // =========================================================================

    private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
        String id = acct.getLoanAccountNumber();
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber(id);

        // Validate borrower name fields are not null (ANO-007/ANO-008)
        String firstName = LegacyDataValidator.requireNonBlank(
                acct.getBorrowerFirstName(), "BORR_FST_NM", id, "Unknown");
        String lastName = LegacyDataValidator.requireNonBlank(
                acct.getBorrowerLastName(), "BORR_LST_NM", id, "Unknown");
        dto.setBorrowerName(firstName + " " + lastName);

        dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());

        // Parse numeric fields with validation (ANO-004)
        BigDecimal originalAmount = LegacyDataValidator.parseAmount(acct.getOriginalAmount(), "LN_ORIG_AMT", id);
        BigDecimal currentBalance = LegacyDataValidator.parseAmount(acct.getCurrentBalance(), "LN_CURR_BAL", id);
        dto.setOriginalAmount(originalAmount);
        dto.setCurrentBalance(currentBalance);
        dto.setInterestRate(LegacyDataValidator.parseDecimal(acct.getInterestRate(), "LN_INT_RT", id));
        dto.setMonthlyPayment(LegacyDataValidator.parseAmount(acct.getMonthlyPayment(), "LN_PMT_AMT", id));

        // Validate status code (ANO-006)
        String statusCode = LegacyDataValidator.validateStatusCode(
                acct.getStatusCode(), LegacyDataValidator.getValidLoanStatusCodes(), "LN_STAT_CD", id);
        dto.setStatus(expandStatusCode(statusCode));

        // Validate date format (ANO-010)
        LegacyDataValidator.parseDate(acct.getOriginationDate(), "LN_ORIG_DT", id);
        dto.setOriginationDate(acct.getOriginationDate());

        // Validate property address fields for nulls (ANO-007)
        String propAddr = LegacyDataValidator.requireNonBlank(acct.getPropertyAddress(), "PROP_ADDR_LN1", id, "N/A");
        String propCity = LegacyDataValidator.requireNonBlank(acct.getPropertyCity(), "PROP_CTY_NM", id, "N/A");
        String propState = LegacyDataValidator.requireNonBlank(acct.getPropertyState(), "PROP_ST_CD", id, "N/A");
        String propZip = LegacyDataValidator.requireNonBlank(acct.getPropertyZip(), "PROP_ZIP_CD", id, "N/A");
        dto.setPropertyAddress(propAddr + ", " + propCity + ", " + propState + " " + propZip);

        // Validate property type code
        String propTypeCode = LegacyDataValidator.validateStatusCode(
                acct.getPropertyType(), LegacyDataValidator.getValidPropertyTypeCodes(), "PROP_TYP_CD", id);
        dto.setPropertyType(expandPropertyType(propTypeCode));

        // Cross-field validation: delinquency vs status (ANO-006)
        Integer delinquencyDays = LegacyDataValidator.parseInteger(acct.getDelinquencyDays(), "LN_DLQ_DAYS", id);
        // Use validated (trimmed) statusCode, not raw acct.getStatusCode(), to ensure
        // exact string matching works even if raw value has whitespace
        LegacyDataValidator.validateDelinquencyStatus(delinquencyDays, statusCode, id);

        // Cross-field validation: LTV percent vs computed value (ANO-009)
        BigDecimal storedLtv = LegacyDataValidator.parseDecimal(acct.getLtvPercent(), "LN_LTV_PCT", id);
        BigDecimal appraisedValue = LegacyDataValidator.parseAmount(acct.getAppraisedValue(), "PROP_APRS_VAL", id);
        LegacyDataValidator.validateLtvPercent(storedLtv, originalAmount, appraisedValue, id);

        return dto;
    }

    private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
        String id = borrower.getBorrowerId();
        BorrowerDto dto = new BorrowerDto();
        dto.setId(id);

        // Validate required name fields (ANO-007)
        String firstName = LegacyDataValidator.requireNonBlank(borrower.getFirstName(), "BORR_FST_NM", id, "Unknown");
        String lastName = LegacyDataValidator.requireNonBlank(borrower.getLastName(), "BORR_LST_NM", id, "Unknown");
        String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
        dto.setFullName(firstName + middle + " " + lastName);

        dto.setEmail(borrower.getEmail());
        dto.setPhone(borrower.getPhoneNumber());
        dto.setCity(borrower.getCity());
        dto.setState(borrower.getStateCode());

        // Parse and validate credit score (ANO-004)
        Integer creditScore = LegacyDataValidator.parseInteger(borrower.getCreditScore(), "BORR_CRDT_SCR", id);
        dto.setCreditScore(LegacyDataValidator.validateCreditScore(creditScore, id));

        dto.setEmploymentStatus(borrower.getEmploymentStatus());

        // Validate date fields (ANO-010)
        LegacyDataValidator.parseDate(borrower.getDateOfBirth(), "BORR_DOB_DT", id);
        LegacyDataValidator.parseDate(borrower.getCreatedDate(), "BORR_CRET_DT", id);
        LegacyDataValidator.parseDate(borrower.getUpdatedDate(), "BORR_UPDT_DT", id);

        // Validate borrower status code
        LegacyDataValidator.validateStatusCode(
                borrower.getStatusCode(), LegacyDataValidator.getValidBorrowerStatusCodes(), "BORR_STAT_CD", id);

        // Validate annual income parses correctly (ANO-004)
        LegacyDataValidator.parseAmount(borrower.getAnnualIncome(), "BORR_ANN_INCM", id);

        return dto;
    }

    private PaymentDto toPaymentDto(LegacyPayment pmt) {
        String id = pmt.getPaymentSequenceNumber();
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId(id);
        dto.setLoanAccountNumber(pmt.getLoanAccountNumber());

        // Validate date format (ANO-010)
        LegacyDataValidator.parseDate(pmt.getPaymentDate(), "PMT_DT", id);
        dto.setPaymentDate(pmt.getPaymentDate());

        // Parse all amount fields with validation (ANO-004)
        BigDecimal totalAmount = LegacyDataValidator.parseAmount(pmt.getTotalAmount(), "PMT_AMT", id);
        BigDecimal principalAmount = LegacyDataValidator.parseAmount(pmt.getPrincipalAmount(), "PMT_PRIN_AMT", id);
        BigDecimal interestAmount = LegacyDataValidator.parseAmount(pmt.getInterestAmount(), "PMT_INT_AMT", id);
        BigDecimal escrowAmount = LegacyDataValidator.parseAmount(pmt.getEscrowAmount(), "PMT_ESCROW_AMT", id);
        BigDecimal lateFee = LegacyDataValidator.parseAmount(pmt.getLateFee(), "PMT_LATE_FEE", id);

        dto.setTotalAmount(totalAmount);
        dto.setPrincipalAmount(principalAmount);
        dto.setInterestAmount(interestAmount);
        dto.setEscrowAmount(escrowAmount);
        dto.setLateFee(lateFee);

        // Cross-field validation: components must sum to total (ANO-002)
        LegacyDataValidator.validatePaymentComponents(totalAmount, principalAmount, interestAmount, escrowAmount, id);

        // Validate payment type code
        String typeCode = LegacyDataValidator.validateStatusCode(
                pmt.getTypeCode(), LegacyDataValidator.getValidPaymentTypeCodes(), "PMT_TYP_CD", id);
        dto.setType(expandPaymentType(typeCode));

        // Validate payment status code
        String statusCode = LegacyDataValidator.validateStatusCode(
                pmt.getStatusCode(), LegacyDataValidator.getValidPaymentStatusCodes(), "PMT_STAT_CD", id);
        dto.setStatus(expandPaymentStatus(statusCode));

        // Validate additional date fields (ANO-010)
        LegacyDataValidator.parseDate(pmt.getReceivedDate(), "PMT_RECV_DT", id);
        LegacyDataValidator.parseDate(pmt.getProcessedDate(), "PMT_PROC_DT", id);

        return dto;
    }

    // =========================================================================
    // STATUS CODE EXPANSION METHODS
    // =========================================================================

    // Handle both null and "UNKNOWN" (returned by validateStatusCode for blank inputs)
    // to preserve backward-compatible "Unknown" label in API responses
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
}
