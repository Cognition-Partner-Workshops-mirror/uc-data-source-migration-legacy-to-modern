package com.workshop.loanservice.migration;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Orchestrates a complete dry-run validation of the legacy dataset before migration.
 * <p>
 * Loads all legacy data from CDW tables, validates every field that requires
 * transformation (dates, amounts, FK references), checks cross-field constraints
 * (date ordering, payment component sums, denormalization consistency), and
 * aggregates findings into a {@link PreFlightReport}.
 * </p>
 * <p>
 * This service is read-only — it does NOT modify any data.
 * </p>
 */
@Service
public class MigrationPreFlightService {

    private final LegacyBorrowerRepository borrowerRepository;
    private final LegacyLoanProductRepository productRepository;
    private final LegacyLoanAccountRepository loanAccountRepository;
    private final LegacyPaymentRepository paymentRepository;

    private final DateValidator dateValidator = new DateValidator();
    private final AmountValidator amountValidator = new AmountValidator();

    public MigrationPreFlightService(LegacyBorrowerRepository borrowerRepository,
                                     LegacyLoanProductRepository productRepository,
                                     LegacyLoanAccountRepository loanAccountRepository,
                                     LegacyPaymentRepository paymentRepository) {
        this.borrowerRepository = borrowerRepository;
        this.productRepository = productRepository;
        this.loanAccountRepository = loanAccountRepository;
        this.paymentRepository = paymentRepository;
    }

    /**
     * Execute a full pre-flight validation across all legacy tables.
     * This is a read-only operation that validates every row and returns
     * an aggregated report of all findings.
     *
     * @return the complete pre-flight validation report
     */
    public PreFlightReport runFullValidation() {
        // Step 1: Load all legacy data
        List<LegacyBorrower> borrowers = borrowerRepository.findAll();
        List<LegacyLoanProduct> products = productRepository.findAll();
        List<LegacyLoanAccount> loans = loanAccountRepository.findAll();
        List<LegacyPayment> payments = paymentRepository.findAll();

        // Build lookup structures for FK validation
        Set<String> knownBorrowerIds = borrowers.stream()
                .map(LegacyBorrower::getBorrowerId)
                .collect(Collectors.toSet());
        Set<String> knownProductCodes = products.stream()
                .map(LegacyLoanProduct::getProductCode)
                .collect(Collectors.toSet());
        Set<String> knownLoanAccounts = loans.stream()
                .map(LegacyLoanAccount::getLoanAccountNumber)
                .collect(Collectors.toSet());
        Map<String, LegacyBorrower> borrowerMap = borrowers.stream()
                .collect(Collectors.toMap(LegacyBorrower::getBorrowerId, b -> b));

        // Initialize the report with row counts
        PreFlightReport report = new PreFlightReport();
        report.setTotalBorrowers(borrowers.size());
        report.setTotalProducts(products.size());
        report.setTotalLoans(loans.size());
        report.setTotalPayments(payments.size());

        // Step 2: Run FK orphan scan
        PreFlightReport orphanReport = FkLookupResolver.runOrphanScan(
                loans, knownBorrowerIds, knownProductCodes);
        report.getOrphanedBorrowerIds().addAll(orphanReport.getOrphanedBorrowerIds());
        report.getOrphanedProductCodes().addAll(orphanReport.getOrphanedProductCodes());

        // Check payment → loan account orphans
        for (LegacyPayment pmt : payments) {
            if (pmt.getLoanAccountNumber() != null
                    && !knownLoanAccounts.contains(pmt.getLoanAccountNumber())) {
                report.getOrphanedLoanAccounts().add(pmt.getLoanAccountNumber());
            }
        }

        // Step 3: Run denormalization reconciliation
        List<DenormMismatch> mismatches = FkLookupResolver.reconcileDenormalizedFields(
                loans, borrowerMap);
        report.getDenormMismatches().addAll(mismatches);

        int totalErrors = 0;
        int totalWarnings = 0;

        // Step 4: Validate each borrower
        for (LegacyBorrower borrower : borrowers) {
            ValidationReport rowReport = validateBorrower(borrower);
            if (rowReport.hasErrors() || rowReport.hasWarnings()) {
                report.getFailedRows().add(rowReport);
                totalErrors += rowReport.getErrors().size();
                totalWarnings += rowReport.getWarnings().size();
            }
        }

        // Step 5: Validate each loan account
        // Build simulated modern ID maps for FK resolution validation
        // (using sequential IDs since we're just checking existence, not actual values)
        Map<String, Long> borrowerIdMap = new HashMap<>();
        long id = 1;
        for (LegacyBorrower b : borrowers) {
            borrowerIdMap.put(b.getBorrowerId(), id++);
        }
        Map<String, Long> productCodeMap = new HashMap<>();
        id = 1;
        for (LegacyLoanProduct p : products) {
            productCodeMap.put(p.getProductCode(), id++);
        }
        Map<String, Long> loanAccountMap = new HashMap<>();
        id = 1;
        for (LegacyLoanAccount l : loans) {
            loanAccountMap.put(l.getLoanAccountNumber(), id++);
        }
        FkLookupResolver fkResolver = new FkLookupResolver(
                borrowerIdMap, productCodeMap, loanAccountMap);

        for (LegacyLoanAccount loan : loans) {
            ValidationReport rowReport = validateLoanAccount(loan, fkResolver);
            if (rowReport.hasErrors() || rowReport.hasWarnings()) {
                report.getFailedRows().add(rowReport);
                totalErrors += rowReport.getErrors().size();
                totalWarnings += rowReport.getWarnings().size();
            }
        }

        // Step 6: Validate each payment
        for (LegacyPayment payment : payments) {
            ValidationReport rowReport = validatePayment(payment, fkResolver);
            if (rowReport.hasErrors() || rowReport.hasWarnings()) {
                report.getFailedRows().add(rowReport);
                totalErrors += rowReport.getErrors().size();
                totalWarnings += rowReport.getWarnings().size();
            }

            // Track payment sum mismatches separately for easy access
            collectPaymentSumMismatches(payment, report);
        }

        report.setErrorCount(totalErrors);
        report.setWarningCount(totalWarnings);

        return report;
    }

    // =========================================================================
    // Per-entity validation methods
    // =========================================================================

    /** Validate all transformable fields on a single borrower row */
    private ValidationReport validateBorrower(LegacyBorrower borrower) {
        ValidationReport report = new ValidationReport("CDW_BORR_MSTR", borrower.getBorrowerId());

        // Date fields
        report.add(dateValidator.parseDate(borrower.getDateOfBirth(), "date_of_birth", false));
        report.add(dateValidator.parseTimestamp(borrower.getCreatedDate(), "created_at", false));
        report.add(dateValidator.parseTimestamp(borrower.getUpdatedDate(), "updated_at", false));

        // Amount fields
        report.add(amountValidator.parseAmount(
                borrower.getAnnualIncome(), "annual_income", false, 12, 2));
        report.add(amountValidator.parseCreditScore(borrower.getCreditScore()));

        return report;
    }

    /** Validate all transformable fields on a single loan account row */
    private ValidationReport validateLoanAccount(LegacyLoanAccount loan,
                                                  FkLookupResolver fkResolver) {
        ValidationReport report = new ValidationReport("CDW_LN_ACCT", loan.getLoanAccountNumber());

        // FK references
        report.add(fkResolver.resolveBorrowerId(loan.getBorrowerId()));
        report.add(fkResolver.resolveProductId(loan.getProductCode()));

        // Date fields
        ValidationResult<LocalDate> origDate = dateValidator.parseDate(
                loan.getOriginationDate(), "origination_date", true);
        ValidationResult<LocalDate> matDate = dateValidator.parseDate(
                loan.getMaturityDate(), "maturity_date", true);
        ValidationResult<LocalDate> firstPmtDate = dateValidator.parseDate(
                loan.getFirstPaymentDate(), "first_payment_date", false);
        ValidationResult<LocalDate> nextPmtDate = dateValidator.parseDate(
                loan.getNextPaymentDate(), "next_payment_date", false);

        report.add(origDate);
        report.add(matDate);
        report.add(firstPmtDate);
        report.add(nextPmtDate);
        report.add(dateValidator.parseTimestamp(loan.getCreatedDate(), "created_at", false));
        report.add(dateValidator.parseTimestamp(loan.getUpdatedDate(), "updated_at", false));

        // Date ordering validation
        report.addAll(dateValidator.validateDateOrdering(
                origDate.getValue(), matDate.getValue(),
                firstPmtDate.getValue(), nextPmtDate.getValue()));

        // Amount fields
        report.add(amountValidator.parseAmount(
                loan.getOriginalAmount(), "original_amount", true, 12, 2));
        report.add(amountValidator.parseAmount(
                loan.getCurrentBalance(), "current_balance", true, 12, 2));
        report.add(amountValidator.parseInterestRate(loan.getInterestRate()));
        report.add(amountValidator.parseInteger(loan.getTermMonths(), "term_months", true));
        report.add(amountValidator.parseAmount(
                loan.getMonthlyPayment(), "monthly_payment", true, 10, 2));
        report.add(amountValidator.parseAmount(
                loan.getEscrowBalance(), "escrow_balance", false, 10, 2));
        report.add(amountValidator.parseLtvPercent(loan.getLtvPercent()));
        report.add(amountValidator.parseAmount(
                loan.getAppraisedValue(), "appraised_value", false, 12, 2));
        report.add(amountValidator.parseInteger(
                loan.getDelinquencyDays(), "delinquency_days", false));

        return report;
    }

    /** Validate all transformable fields on a single payment row */
    private ValidationReport validatePayment(LegacyPayment payment,
                                              FkLookupResolver fkResolver) {
        ValidationReport report = new ValidationReport(
                "CDW_PMT_HIST", payment.getPaymentSequenceNumber());

        // FK reference — payment → loan account
        report.add(fkResolver.resolveLoanAccountId(payment.getLoanAccountNumber()));

        // Date fields
        ValidationResult<LocalDate> pmtDate = dateValidator.parseDate(
                payment.getPaymentDate(), "payment_date", true);
        ValidationResult<LocalDate> recvDate = dateValidator.parseDate(
                payment.getReceivedDate(), "received_date", false);
        ValidationResult<LocalDate> procDate = dateValidator.parseDate(
                payment.getProcessedDate(), "processed_date", false);

        report.add(pmtDate);
        report.add(recvDate);
        report.add(procDate);
        report.add(dateValidator.parseTimestamp(
                payment.getCreatedDate(), "created_at", false));
        report.add(dateValidator.parseTimestamp(
                payment.getUpdatedDate(), "updated_at", false));

        // Payment date ordering validation
        report.addAll(dateValidator.validatePaymentDateOrdering(
                pmtDate.getValue(), recvDate.getValue(), procDate.getValue()));

        // Amount fields
        report.add(amountValidator.parseAmount(
                payment.getTotalAmount(), "total_amount", true, 10, 2));
        report.add(amountValidator.parseAmount(
                payment.getPrincipalAmount(), "principal_amount", false, 10, 2));
        report.add(amountValidator.parseAmount(
                payment.getInterestAmount(), "interest_amount", false, 10, 2));
        report.add(amountValidator.parseAmount(
                payment.getEscrowAmount(), "escrow_amount", false, 10, 2));
        report.add(amountValidator.parseAmount(
                payment.getLateFee(), "late_fee", false, 10, 2));

        // Payment component sum validation
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        report.addAll(amountValidator.validatePaymentComponentSum(
                total, principal, interest, escrow, lateFee,
                payment.getPaymentSequenceNumber()));

        return report;
    }

    /**
     * Collect payment sum mismatches into the report's dedicated list
     * for easy top-level access.
     */
    private void collectPaymentSumMismatches(LegacyPayment payment, PreFlightReport report) {
        BigDecimal total = safeParseAmount(payment.getTotalAmount());
        BigDecimal principal = safeParseAmount(payment.getPrincipalAmount());
        BigDecimal interest = safeParseAmount(payment.getInterestAmount());
        BigDecimal escrow = safeParseAmount(payment.getEscrowAmount());
        BigDecimal lateFee = safeParseAmount(payment.getLateFee());

        if (total != null && principal != null && interest != null) {
            BigDecimal esc = escrow != null ? escrow : BigDecimal.ZERO;
            BigDecimal fee = lateFee != null ? lateFee : BigDecimal.ZERO;
            BigDecimal componentSum = principal.add(interest).add(esc).add(fee);

            if (componentSum.compareTo(total) != 0) {
                report.getPaymentSumMismatches().add(new PaymentSumMismatch(
                        payment.getPaymentSequenceNumber(),
                        payment.getLoanAccountNumber(),
                        total, componentSum,
                        componentSum.subtract(total)));
            }
        }
    }

    /** Safely parse an amount string, returning null on failure */
    private BigDecimal safeParseAmount(String raw) {
        if (raw == null || raw.isBlank()) return null;
        try {
            return new BigDecimal(raw.trim().replace(",", ""));
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
