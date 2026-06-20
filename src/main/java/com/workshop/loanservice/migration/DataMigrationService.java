package com.workshop.loanservice.migration;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.entity.modern.Borrower;
import com.workshop.loanservice.entity.modern.LoanAccount;
import com.workshop.loanservice.entity.modern.LoanProduct;
import com.workshop.loanservice.entity.modern.Payment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import com.workshop.loanservice.repository.modern.BorrowerRepository;
import com.workshop.loanservice.repository.modern.LoanAccountRepository;
import com.workshop.loanservice.repository.modern.LoanProductRepository;
import com.workshop.loanservice.repository.modern.PaymentRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

/**
 * Service that migrates data from the legacy CDW tables (all VARCHAR)
 * to the modern normalized schema with proper types.
 *
 * Transformation rules follow data/mappings/column_mappings.md:
 * - Dates: MM/DD/YYYY string → LocalDate
 * - Amounts: comma-separated strings → BigDecimal
 * - Status codes: abbreviations → expanded enum values
 * - Property types: short codes → full descriptions
 * - FK resolution: legacy string IDs → modern BIGINT relationships
 */
@Service
public class DataMigrationService {

    private static final Logger log = LoggerFactory.getLogger(DataMigrationService.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private final LegacyBorrowerRepository legacyBorrowerRepository;
    private final LegacyLoanProductRepository legacyLoanProductRepository;
    private final LegacyLoanAccountRepository legacyLoanAccountRepository;
    private final LegacyPaymentRepository legacyPaymentRepository;

    private final BorrowerRepository borrowerRepository;
    private final LoanProductRepository loanProductRepository;
    private final LoanAccountRepository loanAccountRepository;
    private final PaymentRepository paymentRepository;

    public DataMigrationService(
            LegacyBorrowerRepository legacyBorrowerRepository,
            LegacyLoanProductRepository legacyLoanProductRepository,
            LegacyLoanAccountRepository legacyLoanAccountRepository,
            LegacyPaymentRepository legacyPaymentRepository,
            BorrowerRepository borrowerRepository,
            LoanProductRepository loanProductRepository,
            LoanAccountRepository loanAccountRepository,
            PaymentRepository paymentRepository) {
        this.legacyBorrowerRepository = legacyBorrowerRepository;
        this.legacyLoanProductRepository = legacyLoanProductRepository;
        this.legacyLoanAccountRepository = legacyLoanAccountRepository;
        this.legacyPaymentRepository = legacyPaymentRepository;
        this.borrowerRepository = borrowerRepository;
        this.loanProductRepository = loanProductRepository;
        this.loanAccountRepository = loanAccountRepository;
        this.paymentRepository = paymentRepository;
    }

    /**
     * Executes full migration from legacy to modern schema.
     * Order matters: borrowers and products first, then accounts, then payments.
     */
    @Transactional
    public MigrationResult migrateAll() {
        log.info("Starting data migration from legacy CDW to modern schema");

        int borrowersMigrated = migrateBorrowers();
        int productsMigrated = migrateLoanProducts();
        int accountsMigrated = migrateLoanAccounts();
        int paymentsMigrated = migratePayments();

        MigrationResult result = new MigrationResult(
                borrowersMigrated, productsMigrated, accountsMigrated, paymentsMigrated);
        log.info("Migration complete: {}", result);
        return result;
    }

    /**
     * Migrates borrowers from CDW_BORR_MSTR to the modern borrowers table.
     * Transforms dates from MM/DD/YYYY strings and status codes from abbreviations.
     */
    private int migrateBorrowers() {
        List<LegacyBorrower> legacyBorrowers = legacyBorrowerRepository.findAll();
        int count = 0;

        for (LegacyBorrower legacy : legacyBorrowers) {
            Borrower modern = new Borrower();
            modern.setExternalId(legacy.getBorrowerId());
            modern.setFirstName(legacy.getFirstName());
            modern.setLastName(legacy.getLastName());
            modern.setMiddleInitial(legacy.getMiddleInitial());
            modern.setSsnHash(legacy.getSsnEncrypted());
            modern.setDateOfBirth(parseLegacyDate(legacy.getDateOfBirth()));
            modern.setAddressLine1(legacy.getAddressLine1());
            modern.setAddressLine2(legacy.getAddressLine2());
            modern.setCity(legacy.getCity());
            modern.setState(legacy.getStateCode());
            modern.setZipCode(legacy.getZipCode());
            modern.setPhone(legacy.getPhoneNumber());
            modern.setEmail(legacy.getEmail());
            modern.setCreditScore(parseLegacyInteger(legacy.getCreditScore()));
            modern.setEmploymentStatus(legacy.getEmploymentStatus());
            modern.setAnnualIncome(parseLegacyAmount(legacy.getAnnualIncome()));
            modern.setStatus(expandBorrowerStatus(legacy.getStatusCode()));
            modern.setCreatedAt(parseLegacyDateTime(legacy.getCreatedDate()));
            modern.setUpdatedAt(parseLegacyDateTime(legacy.getUpdatedDate()));

            borrowerRepository.save(modern);
            count++;
        }

        log.info("Migrated {} borrowers", count);
        return count;
    }

    /**
     * Migrates loan products from CDW_LN_PROD to the modern loan_products table.
     * Converts status code to boolean is_active flag.
     */
    private int migrateLoanProducts() {
        List<LegacyLoanProduct> legacyProducts = legacyLoanProductRepository.findAll();
        int count = 0;

        for (LegacyLoanProduct legacy : legacyProducts) {
            LoanProduct modern = new LoanProduct();
            modern.setCode(legacy.getProductCode());
            modern.setName(legacy.getDescription());
            modern.setType(legacy.getTypeCode());
            modern.setTermMonths(parseLegacyInteger(legacy.getTermMonths()));
            modern.setRateType(legacy.getRateType());
            modern.setMinAmount(parseLegacyAmount(legacy.getMinAmount()));
            modern.setMaxAmount(parseLegacyAmount(legacy.getMaxAmount()));
            // ACT→true, INA→false
            modern.setIsActive("ACT".equals(legacy.getStatusCode()));
            modern.setEffectiveDate(parseLegacyDate(legacy.getEffectiveDate()));
            modern.setExpirationDate(parseLegacyDate(legacy.getExpirationDate()));

            loanProductRepository.save(modern);
            count++;
        }

        log.info("Migrated {} loan products", count);
        return count;
    }

    /**
     * Migrates loan accounts from CDW_LN_ACCT to the modern loan_accounts table.
     * Resolves borrower and product FKs, drops denormalized borrower fields,
     * expands status codes and property type codes.
     */
    private int migrateLoanAccounts() {
        List<LegacyLoanAccount> legacyAccounts = legacyLoanAccountRepository.findAll();
        int count = 0;

        for (LegacyLoanAccount legacy : legacyAccounts) {
            LoanAccount modern = new LoanAccount();
            modern.setAccountNumber(legacy.getLoanAccountNumber());

            // FK resolution: lookup borrower by external_id
            Borrower borrower = borrowerRepository.findByExternalId(legacy.getBorrowerId())
                    .orElseThrow(() -> new RuntimeException(
                            "Borrower not found for ID: " + legacy.getBorrowerId()));
            modern.setBorrower(borrower);

            // FK resolution: lookup product by code
            LoanProduct product = loanProductRepository.findByCode(legacy.getProductCode())
                    .orElseThrow(() -> new RuntimeException(
                            "Product not found for code: " + legacy.getProductCode()));
            modern.setProduct(product);

            modern.setOriginalAmount(parseLegacyAmount(legacy.getOriginalAmount()));
            modern.setCurrentBalance(parseLegacyAmount(legacy.getCurrentBalance()));
            modern.setInterestRate(parseLegacyDecimal(legacy.getInterestRate()));
            modern.setTermMonths(parseLegacyInteger(legacy.getTermMonths()));
            modern.setMonthlyPayment(parseLegacyAmount(legacy.getMonthlyPayment()));
            modern.setOriginationDate(parseLegacyDate(legacy.getOriginationDate()));
            modern.setMaturityDate(parseLegacyDate(legacy.getMaturityDate()));
            modern.setFirstPaymentDate(parseLegacyDate(legacy.getFirstPaymentDate()));
            modern.setNextPaymentDate(parseLegacyDate(legacy.getNextPaymentDate()));
            modern.setStatus(expandLoanStatus(legacy.getStatusCode()));
            modern.setDelinquencyDays(parseLegacyInteger(legacy.getDelinquencyDays()));
            modern.setEscrowBalance(parseLegacyAmount(legacy.getEscrowBalance()));
            modern.setLtvPercent(parseLegacyDecimal(legacy.getLtvPercent()));
            modern.setPropertyAddress(legacy.getPropertyAddress());
            modern.setPropertyCity(legacy.getPropertyCity());
            modern.setPropertyState(legacy.getPropertyState());
            modern.setPropertyZip(legacy.getPropertyZip());
            modern.setPropertyType(expandPropertyType(legacy.getPropertyType()));
            modern.setAppraisedValue(parseLegacyAmount(legacy.getAppraisedValue()));
            modern.setCreatedAt(parseLegacyDateTime(legacy.getCreatedDate()));
            modern.setUpdatedAt(parseLegacyDateTime(legacy.getUpdatedDate()));

            loanAccountRepository.save(modern);
            count++;
        }

        log.info("Migrated {} loan accounts", count);
        return count;
    }

    /**
     * Migrates payments from CDW_PMT_HIST to the modern payments table.
     * Resolves loan_account FK and expands type/status codes.
     */
    private int migratePayments() {
        List<LegacyPayment> legacyPayments = legacyPaymentRepository.findAll();
        int count = 0;

        for (LegacyPayment legacy : legacyPayments) {
            Payment modern = new Payment();

            // FK resolution: lookup loan account by account_number
            LoanAccount loanAccount = loanAccountRepository
                    .findByAccountNumber(legacy.getLoanAccountNumber())
                    .orElseThrow(() -> new RuntimeException(
                            "Loan account not found: " + legacy.getLoanAccountNumber()));
            modern.setLoanAccount(loanAccount);

            modern.setPaymentDate(parseLegacyDate(legacy.getPaymentDate()));
            modern.setTotalAmount(parseLegacyAmount(legacy.getTotalAmount()));
            modern.setPrincipalAmount(parseLegacyAmount(legacy.getPrincipalAmount()));
            modern.setInterestAmount(parseLegacyAmount(legacy.getInterestAmount()));
            modern.setEscrowAmount(parseLegacyAmount(legacy.getEscrowAmount()));
            modern.setLateFee(parseLegacyAmount(legacy.getLateFee()));
            modern.setType(expandPaymentType(legacy.getTypeCode()));
            modern.setStatus(expandPaymentStatus(legacy.getStatusCode()));
            modern.setReceivedDate(parseLegacyDate(legacy.getReceivedDate()));
            modern.setProcessedDate(parseLegacyDate(legacy.getProcessedDate()));
            modern.setCreatedAt(parseLegacyDateTime(legacy.getCreatedDate()));
            modern.setUpdatedAt(parseLegacyDateTime(legacy.getUpdatedDate()));

            paymentRepository.save(modern);
            count++;
        }

        log.info("Migrated {} payments", count);
        return count;
    }

    // =========================================================================
    // TRANSFORMATION HELPERS
    // =========================================================================

    /** Parses legacy MM/DD/YYYY date strings to LocalDate */
    private LocalDate parseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
    }

    /** Parses legacy MM/DD/YYYY date strings to LocalDateTime (start of day) */
    private LocalDateTime parseLegacyDateTime(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT).atStartOfDay();
    }

    /** Removes commas from legacy amount strings and parses to BigDecimal */
    private BigDecimal parseLegacyAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        return new BigDecimal(amount.replace(",", "").trim());
    }

    /** Parses legacy decimal strings (no commas) to BigDecimal */
    private BigDecimal parseLegacyDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        return new BigDecimal(value.trim());
    }

    /** Parses legacy integer strings */
    private Integer parseLegacyInteger(String value) {
        if (value == null || value.isBlank()) return null;
        return Integer.parseInt(value.trim());
    }

    /** Expands borrower status: ACT→ACTIVE, INA→INACTIVE */
    private Borrower.Status expandBorrowerStatus(String code) {
        if (code == null) return Borrower.Status.ACTIVE;
        return switch (code) {
            case "ACT" -> Borrower.Status.ACTIVE;
            case "INA" -> Borrower.Status.INACTIVE;
            default -> Borrower.Status.ACTIVE;
        };
    }

    /** Expands loan status: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE */
    private LoanAccount.Status expandLoanStatus(String code) {
        if (code == null) return LoanAccount.Status.ACTIVE;
        return switch (code) {
            case "ACT" -> LoanAccount.Status.ACTIVE;
            case "CLO" -> LoanAccount.Status.CLOSED;
            case "DFT" -> LoanAccount.Status.DEFAULT;
            case "FRB" -> LoanAccount.Status.FORBEARANCE;
            default -> LoanAccount.Status.ACTIVE;
        };
    }

    /** Expands property type: SFR→Single Family, CND→Condominium, etc. */
    private String expandPropertyType(String code) {
        if (code == null) return null;
        return switch (code) {
            case "SFR" -> "Single Family";
            case "CND" -> "Condominium";
            case "MFR" -> "Multi-Family";
            case "TWN" -> "Townhouse";
            default -> code;
        };
    }

    /** Expands payment type: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT */
    private Payment.PaymentType expandPaymentType(String code) {
        if (code == null) return Payment.PaymentType.REGULAR;
        return switch (code) {
            case "REG" -> Payment.PaymentType.REGULAR;
            case "EXT" -> Payment.PaymentType.EXTRA;
            case "PRT" -> Payment.PaymentType.PARTIAL;
            case "PRE" -> Payment.PaymentType.PREPAYMENT;
            default -> Payment.PaymentType.REGULAR;
        };
    }

    /** Expands payment status: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING */
    private Payment.PaymentStatus expandPaymentStatus(String code) {
        if (code == null) return Payment.PaymentStatus.PENDING;
        return switch (code) {
            case "PST" -> Payment.PaymentStatus.POSTED;
            case "REV" -> Payment.PaymentStatus.REVERSED;
            case "NSF" -> Payment.PaymentStatus.NSF;
            case "PND" -> Payment.PaymentStatus.PENDING;
            default -> Payment.PaymentStatus.PENDING;
        };
    }

    /**
     * Holds migration result counts for verification.
     */
    public record MigrationResult(
            int borrowersMigrated,
            int productsMigrated,
            int accountsMigrated,
            int paymentsMigrated
    ) {
        @Override
        public String toString() {
            return String.format("borrowers=%d, products=%d, accounts=%d, payments=%d",
                    borrowersMigrated, productsMigrated, accountsMigrated, paymentsMigrated);
        }
    }
}
