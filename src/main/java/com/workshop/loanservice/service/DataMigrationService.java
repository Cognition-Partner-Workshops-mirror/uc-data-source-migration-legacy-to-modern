package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.*;
import com.workshop.loanservice.repository.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;

/**
 * Service that reads from legacy CDW tables, transforms the data
 * (parsing dates, amounts, expanding status codes), and writes to
 * the modern normalized schema. Tracks migration statistics for reporting.
 */
@Service
public class DataMigrationService {

    private static final Logger log = LoggerFactory.getLogger(DataMigrationService.class);
    private static final DateTimeFormatter LEGACY_DATE_FORMAT = DateTimeFormatter.ofPattern("MM/dd/yyyy");

    private final LegacyBorrowerRepository legacyBorrowerRepo;
    private final LegacyLoanProductRepository legacyProductRepo;
    private final LegacyLoanAccountRepository legacyAccountRepo;
    private final LegacyPaymentRepository legacyPaymentRepo;

    private final BorrowerRepository borrowerRepo;
    private final LoanProductRepository productRepo;
    private final LoanAccountRepository accountRepo;
    private final PaymentRepository paymentRepo;

    public DataMigrationService(LegacyBorrowerRepository legacyBorrowerRepo,
                                LegacyLoanProductRepository legacyProductRepo,
                                LegacyLoanAccountRepository legacyAccountRepo,
                                LegacyPaymentRepository legacyPaymentRepo,
                                BorrowerRepository borrowerRepo,
                                LoanProductRepository productRepo,
                                LoanAccountRepository accountRepo,
                                PaymentRepository paymentRepo) {
        this.legacyBorrowerRepo = legacyBorrowerRepo;
        this.legacyProductRepo = legacyProductRepo;
        this.legacyAccountRepo = legacyAccountRepo;
        this.legacyPaymentRepo = legacyPaymentRepo;
        this.borrowerRepo = borrowerRepo;
        this.productRepo = productRepo;
        this.accountRepo = accountRepo;
        this.paymentRepo = paymentRepo;
    }

    /**
     * Executes the full migration pipeline: borrowers → products → accounts → payments.
     * Returns a summary report with counts and any warnings.
     */
    @Transactional
    public MigrationReport runMigration() {
        MigrationReport report = new MigrationReport();
        report.setStartTime(LocalDateTime.now());

        log.info("Starting legacy-to-modern data migration...");

        // Phase 1: Migrate borrowers
        Map<String, Borrower> borrowerMap = migrateBorrowers(report);

        // Phase 2: Migrate loan products
        Map<String, LoanProduct> productMap = migrateLoanProducts(report);

        // Phase 3: Migrate loan accounts (depends on borrower + product maps for FK resolution)
        Map<String, LoanAccount> accountMap = migrateLoanAccounts(report, borrowerMap, productMap);

        // Phase 4: Migrate payments (depends on account map for FK resolution)
        migratePayments(report, accountMap);

        report.setEndTime(LocalDateTime.now());
        log.info("Migration complete. {}", report.getSummary());
        return report;
    }

    /**
     * Migrates borrowers from CDW_BORR_MSTR to borrowers table.
     * Transforms: date strings → LocalDate, amount strings → BigDecimal,
     * status codes → expanded values.
     */
    private Map<String, Borrower> migrateBorrowers(MigrationReport report) {
        List<LegacyBorrower> legacyBorrowers = legacyBorrowerRepo.findAll();
        Map<String, Borrower> borrowerMap = new HashMap<>();

        for (LegacyBorrower legacy : legacyBorrowers) {
            try {
                // Skip if already migrated (idempotent)
                if (borrowerRepo.findByExternalId(legacy.getBorrowerId()).isPresent()) {
                    borrowerMap.put(legacy.getBorrowerId(),
                            borrowerRepo.findByExternalId(legacy.getBorrowerId()).get());
                    report.addWarning("Borrower " + legacy.getBorrowerId() + " already exists, skipping");
                    continue;
                }

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
                modern.setCreditScore(parseInteger(legacy.getCreditScore()));
                modern.setEmploymentStatus(legacy.getEmploymentStatus());
                modern.setAnnualIncome(parseAmount(legacy.getAnnualIncome()));
                modern.setStatus(expandBorrowerStatus(legacy.getStatusCode()));
                modern.setCreatedAt(parseLegacyDateTime(legacy.getCreatedDate()));
                modern.setUpdatedAt(parseLegacyDateTime(legacy.getUpdatedDate()));

                Borrower saved = borrowerRepo.save(modern);
                borrowerMap.put(legacy.getBorrowerId(), saved);
                report.incrementBorrowers();
            } catch (Exception e) {
                report.addError("Failed to migrate borrower " + legacy.getBorrowerId() + ": " + e.getMessage());
                log.error("Error migrating borrower {}", legacy.getBorrowerId(), e);
            }
        }

        log.info("Migrated {} borrowers", report.getBorrowersMigrated());
        return borrowerMap;
    }

    /**
     * Migrates loan products from CDW_LN_PROD to loan_products table.
     * Transforms: term months string → integer, amount strings → BigDecimal,
     * status code → boolean is_active.
     */
    private Map<String, LoanProduct> migrateLoanProducts(MigrationReport report) {
        List<LegacyLoanProduct> legacyProducts = legacyProductRepo.findAll();
        Map<String, LoanProduct> productMap = new HashMap<>();

        for (LegacyLoanProduct legacy : legacyProducts) {
            try {
                // Skip if already migrated (idempotent)
                if (productRepo.findByCode(legacy.getProductCode()).isPresent()) {
                    productMap.put(legacy.getProductCode(),
                            productRepo.findByCode(legacy.getProductCode()).get());
                    report.addWarning("Product " + legacy.getProductCode() + " already exists, skipping");
                    continue;
                }

                LoanProduct modern = new LoanProduct();
                modern.setCode(legacy.getProductCode());
                modern.setName(legacy.getDescription());
                modern.setType(legacy.getTypeCode());
                modern.setTermMonths(parseInteger(legacy.getTermMonths()));
                modern.setRateType(legacy.getRateType());
                modern.setMinAmount(parseAmount(legacy.getMinAmount()));
                modern.setMaxAmount(parseAmount(legacy.getMaxAmount()));
                // Convert status code to boolean: ACT → true, anything else → false
                modern.setIsActive("ACT".equals(legacy.getStatusCode()));
                modern.setEffectiveDate(parseLegacyDate(legacy.getEffectiveDate()));
                modern.setExpirationDate(parseLegacyDate(legacy.getExpirationDate()));

                LoanProduct saved = productRepo.save(modern);
                productMap.put(legacy.getProductCode(), saved);
                report.incrementProducts();
            } catch (Exception e) {
                report.addError("Failed to migrate product " + legacy.getProductCode() + ": " + e.getMessage());
                log.error("Error migrating product {}", legacy.getProductCode(), e);
            }
        }

        log.info("Migrated {} loan products", report.getProductsMigrated());
        return productMap;
    }

    /**
     * Migrates loan accounts from CDW_LN_ACCT to loan_accounts table.
     * Resolves borrower and product foreign keys from the maps built in earlier phases.
     * Drops denormalized borrower fields (first name, last name, SSN last 4).
     * Expands property type codes and loan status codes.
     */
    private Map<String, LoanAccount> migrateLoanAccounts(MigrationReport report,
                                                          Map<String, Borrower> borrowerMap,
                                                          Map<String, LoanProduct> productMap) {
        List<LegacyLoanAccount> legacyAccounts = legacyAccountRepo.findAll();
        Map<String, LoanAccount> accountMap = new HashMap<>();

        for (LegacyLoanAccount legacy : legacyAccounts) {
            try {
                // Skip if already migrated (idempotent)
                if (accountRepo.findByAccountNumber(legacy.getLoanAccountNumber()).isPresent()) {
                    accountMap.put(legacy.getLoanAccountNumber(),
                            accountRepo.findByAccountNumber(legacy.getLoanAccountNumber()).get());
                    report.addWarning("Account " + legacy.getLoanAccountNumber() + " already exists, skipping");
                    continue;
                }

                // Resolve FK references
                Borrower borrower = borrowerMap.get(legacy.getBorrowerId());
                LoanProduct product = productMap.get(legacy.getProductCode());

                if (borrower == null) {
                    report.addError("Borrower " + legacy.getBorrowerId() + " not found for account " + legacy.getLoanAccountNumber());
                    continue;
                }
                if (product == null) {
                    report.addError("Product " + legacy.getProductCode() + " not found for account " + legacy.getLoanAccountNumber());
                    continue;
                }

                LoanAccount modern = new LoanAccount();
                modern.setAccountNumber(legacy.getLoanAccountNumber());
                modern.setBorrower(borrower);
                modern.setProduct(product);
                modern.setOriginalAmount(parseAmount(legacy.getOriginalAmount()));
                modern.setCurrentBalance(parseAmount(legacy.getCurrentBalance()));
                modern.setInterestRate(parseDecimal(legacy.getInterestRate()));
                modern.setTermMonths(parseInteger(legacy.getTermMonths()));
                modern.setMonthlyPayment(parseAmount(legacy.getMonthlyPayment()));
                modern.setOriginationDate(parseLegacyDate(legacy.getOriginationDate()));
                modern.setMaturityDate(parseLegacyDate(legacy.getMaturityDate()));
                modern.setFirstPaymentDate(parseLegacyDate(legacy.getFirstPaymentDate()));
                modern.setNextPaymentDate(parseLegacyDate(legacy.getNextPaymentDate()));
                modern.setStatus(expandLoanStatus(legacy.getStatusCode()));
                modern.setDelinquencyDays(parseInteger(legacy.getDelinquencyDays()));
                modern.setEscrowBalance(parseAmount(legacy.getEscrowBalance()));
                modern.setLtvPercent(parseDecimal(legacy.getLtvPercent()));
                modern.setPropertyAddress(legacy.getPropertyAddress());
                modern.setPropertyCity(legacy.getPropertyCity());
                modern.setPropertyState(legacy.getPropertyState());
                modern.setPropertyZip(legacy.getPropertyZip());
                modern.setPropertyType(expandPropertyType(legacy.getPropertyType()));
                modern.setAppraisedValue(parseAmount(legacy.getAppraisedValue()));
                modern.setCreatedAt(parseLegacyDateTime(legacy.getCreatedDate()));
                modern.setUpdatedAt(parseLegacyDateTime(legacy.getUpdatedDate()));

                LoanAccount saved = accountRepo.save(modern);
                accountMap.put(legacy.getLoanAccountNumber(), saved);
                report.incrementAccounts();
            } catch (Exception e) {
                report.addError("Failed to migrate account " + legacy.getLoanAccountNumber() + ": " + e.getMessage());
                log.error("Error migrating account {}", legacy.getLoanAccountNumber(), e);
            }
        }

        log.info("Migrated {} loan accounts", report.getAccountsMigrated());
        return accountMap;
    }

    /**
     * Migrates payments from CDW_PMT_HIST to payments table.
     * Resolves loan account FK from the account map.
     * Expands payment type and status codes to readable values.
     */
    private void migratePayments(MigrationReport report, Map<String, LoanAccount> accountMap) {
        // Skip if payments already exist (idempotency check)
        if (paymentRepo.count() > 0) {
            report.addWarning("Payments already exist in modern table, skipping payment migration");
            return;
        }

        List<LegacyPayment> legacyPayments = legacyPaymentRepo.findAll();

        for (LegacyPayment legacy : legacyPayments) {
            try {
                LoanAccount account = accountMap.get(legacy.getLoanAccountNumber());
                if (account == null) {
                    report.addError("Account " + legacy.getLoanAccountNumber() + " not found for payment " + legacy.getPaymentSequenceNumber());
                    continue;
                }

                Payment modern = new Payment();
                modern.setLoanAccount(account);
                modern.setPaymentDate(parseLegacyDate(legacy.getPaymentDate()));
                modern.setTotalAmount(parseAmount(legacy.getTotalAmount()));
                modern.setPrincipalAmount(parseAmount(legacy.getPrincipalAmount()));
                modern.setInterestAmount(parseAmount(legacy.getInterestAmount()));
                modern.setEscrowAmount(parseAmount(legacy.getEscrowAmount()));
                modern.setLateFee(parseAmount(legacy.getLateFee()));
                modern.setType(expandPaymentType(legacy.getTypeCode()));
                modern.setStatus(expandPaymentStatus(legacy.getStatusCode()));
                modern.setReceivedDate(parseLegacyDate(legacy.getReceivedDate()));
                modern.setProcessedDate(parseLegacyDate(legacy.getProcessedDate()));
                modern.setCreatedAt(parseLegacyDateTime(legacy.getCreatedDate()));
                modern.setUpdatedAt(parseLegacyDateTime(legacy.getUpdatedDate()));

                paymentRepo.save(modern);
                report.incrementPayments();
            } catch (Exception e) {
                report.addError("Failed to migrate payment " + legacy.getPaymentSequenceNumber() + ": " + e.getMessage());
                log.error("Error migrating payment {}", legacy.getPaymentSequenceNumber(), e);
            }
        }

        log.info("Migrated {} payments", report.getPaymentsMigrated());
    }

    // =========================================================================
    // TRANSFORMATION HELPERS
    // =========================================================================

    /** Parse legacy MM/DD/YYYY date string to LocalDate. */
    private LocalDate parseLegacyDate(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT);
    }

    /** Parse legacy MM/DD/YYYY date string to LocalDateTime (midnight). */
    private LocalDateTime parseLegacyDateTime(String dateStr) {
        if (dateStr == null || dateStr.isBlank()) return null;
        return LocalDate.parse(dateStr.trim(), LEGACY_DATE_FORMAT).atStartOfDay();
    }

    /** Parse legacy amount string (e.g., "285,000" or "1,487.02") to BigDecimal. */
    private BigDecimal parseAmount(String amount) {
        if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
        return new BigDecimal(amount.replace(",", "").trim());
    }

    /** Parse a plain decimal string (e.g., "5.250") to BigDecimal. */
    private BigDecimal parseDecimal(String value) {
        if (value == null || value.isBlank()) return BigDecimal.ZERO;
        return new BigDecimal(value.trim());
    }

    /** Parse a string integer (e.g., "360") to Integer. */
    private Integer parseInteger(String value) {
        if (value == null || value.isBlank()) return 0;
        return Integer.parseInt(value.trim());
    }

    /** Expand borrower status: ACT → ACTIVE, INA → INACTIVE. */
    private String expandBorrowerStatus(String code) {
        if (code == null) return "UNKNOWN";
        return switch (code) {
            case "ACT" -> "ACTIVE";
            case "INA" -> "INACTIVE";
            default -> code;
        };
    }

    /** Expand loan status: ACT → ACTIVE, CLO → CLOSED, DFT → DEFAULT, FRB → FORBEARANCE. */
    private String expandLoanStatus(String code) {
        if (code == null) return "UNKNOWN";
        return switch (code) {
            case "ACT" -> "ACTIVE";
            case "CLO" -> "CLOSED";
            case "DFT" -> "DEFAULT";
            case "FRB" -> "FORBEARANCE";
            default -> code;
        };
    }

    /** Expand property type: SFR → Single Family, CND → Condominium, etc. */
    private String expandPropertyType(String code) {
        if (code == null) return "Unknown";
        return switch (code) {
            case "SFR" -> "Single Family";
            case "CND" -> "Condominium";
            case "MFR" -> "Multi-Family";
            case "TWN" -> "Townhouse";
            default -> code;
        };
    }

    /** Expand payment type: REG → REGULAR, EXT → EXTRA, PRT → PARTIAL, PRE → PREPAYMENT. */
    private String expandPaymentType(String code) {
        if (code == null) return "UNKNOWN";
        return switch (code) {
            case "REG" -> "REGULAR";
            case "EXT" -> "EXTRA";
            case "PRT" -> "PARTIAL";
            case "PRE" -> "PREPAYMENT";
            default -> code;
        };
    }

    /** Expand payment status: PST → POSTED, REV → REVERSED, NSF → NSF, PND → PENDING. */
    private String expandPaymentStatus(String code) {
        if (code == null) return "UNKNOWN";
        return switch (code) {
            case "PST" -> "POSTED";
            case "REV" -> "REVERSED";
            case "NSF" -> "NSF";
            case "PND" -> "PENDING";
            default -> code;
        };
    }

    // =========================================================================
    // MIGRATION REPORT
    // =========================================================================

    /**
     * Holds migration statistics: counts of records migrated per table,
     * any warnings (e.g., duplicates skipped), and errors encountered.
     */
    public static class MigrationReport {
        private LocalDateTime startTime;
        private LocalDateTime endTime;
        private int borrowersMigrated;
        private int productsMigrated;
        private int accountsMigrated;
        private int paymentsMigrated;
        private final List<String> warnings = new ArrayList<>();
        private final List<String> errors = new ArrayList<>();

        public void incrementBorrowers() { borrowersMigrated++; }
        public void incrementProducts() { productsMigrated++; }
        public void incrementAccounts() { accountsMigrated++; }
        public void incrementPayments() { paymentsMigrated++; }
        public void addWarning(String warning) { warnings.add(warning); }
        public void addError(String error) { errors.add(error); }

        public String getSummary() {
            return String.format("Borrowers: %d, Products: %d, Accounts: %d, Payments: %d, Warnings: %d, Errors: %d",
                    borrowersMigrated, productsMigrated, accountsMigrated, paymentsMigrated,
                    warnings.size(), errors.size());
        }

        public LocalDateTime getStartTime() { return startTime; }
        public void setStartTime(LocalDateTime startTime) { this.startTime = startTime; }
        public LocalDateTime getEndTime() { return endTime; }
        public void setEndTime(LocalDateTime endTime) { this.endTime = endTime; }
        public int getBorrowersMigrated() { return borrowersMigrated; }
        public int getProductsMigrated() { return productsMigrated; }
        public int getAccountsMigrated() { return accountsMigrated; }
        public int getPaymentsMigrated() { return paymentsMigrated; }
        public List<String> getWarnings() { return warnings; }
        public List<String> getErrors() { return errors; }
    }
}
