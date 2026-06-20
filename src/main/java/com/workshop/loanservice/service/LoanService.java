package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Loan service router that delegates to the appropriate data source based on
 * the datasource.mode feature flag. Supports three modes for safe rollout:
 *
 * - "legacy"  : reads from CDW tables only (original behavior, zero risk)
 * - "modern"  : reads from normalized schema only (full cutover)
 * - "dual"    : reads from BOTH sources, serves legacy response, and shadow-compares
 *               modern response for reconciliation logging (safe rollout mode)
 *
 * The dual-read mode allows detecting transformation mismatches before cutover
 * without impacting production responses. Set datasource.mode via application
 * properties or environment variable for zero-downtime switching.
 */
@Service
public class LoanService {

    private static final Logger log = LoggerFactory.getLogger(LoanService.class);

    private final LegacyLoanDataSource legacyDataSource;
    private final ModernLoanDataSource modernDataSource;
    private final DualReadComparator comparator;

    // Feature flag: "legacy", "modern", or "dual"
    @Value("${datasource.mode:modern}")
    private String mode;

    public LoanService(LegacyLoanDataSource legacyDataSource,
                       ModernLoanDataSource modernDataSource,
                       DualReadComparator comparator) {
        this.legacyDataSource = legacyDataSource;
        this.modernDataSource = modernDataSource;
        this.comparator = comparator;
    }

    /** Returns all loan summaries — routed based on datasource.mode */
    public List<LoanSummaryDto> getAllLoans() {
        if ("legacy".equals(mode)) {
            return legacyDataSource.getAllLoans();
        }
        if ("dual".equals(mode)) {
            // Dual-read: serve legacy response, shadow-compare modern
            List<LoanSummaryDto> legacyResult = legacyDataSource.getAllLoans();
            List<LoanSummaryDto> modernResult = modernDataSource.getAllLoans();
            comparator.compareSilently(legacyResult, modernResult, "getAllLoans");
            return legacyResult;
        }
        // Default: modern mode
        return modernDataSource.getAllLoans();
    }

    /** Returns a single loan by account number — routed based on datasource.mode */
    public LoanSummaryDto getLoanById(String loanAccountNumber) {
        if ("legacy".equals(mode)) {
            return legacyDataSource.getLoanById(loanAccountNumber);
        }
        if ("dual".equals(mode)) {
            LoanSummaryDto legacyResult = legacyDataSource.getLoanById(loanAccountNumber);
            LoanSummaryDto modernResult = modernDataSource.getLoanById(loanAccountNumber);
            comparator.compareSilently(legacyResult, modernResult,
                    "getLoanById(" + loanAccountNumber + ")");
            return legacyResult;
        }
        return modernDataSource.getLoanById(loanAccountNumber);
    }

    /** Returns all borrowers — routed based on datasource.mode */
    public List<BorrowerDto> getAllBorrowers() {
        if ("legacy".equals(mode)) {
            return legacyDataSource.getAllBorrowers();
        }
        if ("dual".equals(mode)) {
            List<BorrowerDto> legacyResult = legacyDataSource.getAllBorrowers();
            List<BorrowerDto> modernResult = modernDataSource.getAllBorrowers();
            comparator.compareSilently(legacyResult, modernResult, "getAllBorrowers");
            return legacyResult;
        }
        return modernDataSource.getAllBorrowers();
    }

    /** Returns a borrower with attached loans — routed based on datasource.mode */
    public BorrowerDto getBorrowerById(String borrowerId) {
        if ("legacy".equals(mode)) {
            return legacyDataSource.getBorrowerById(borrowerId);
        }
        if ("dual".equals(mode)) {
            BorrowerDto legacyResult = legacyDataSource.getBorrowerById(borrowerId);
            BorrowerDto modernResult = modernDataSource.getBorrowerById(borrowerId);
            comparator.compareSilently(legacyResult, modernResult,
                    "getBorrowerById(" + borrowerId + ")");
            return legacyResult;
        }
        return modernDataSource.getBorrowerById(borrowerId);
    }

    /** Returns payments for a loan — routed based on datasource.mode */
    public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
        if ("legacy".equals(mode)) {
            return legacyDataSource.getPaymentsByLoan(loanAccountNumber);
        }
        if ("dual".equals(mode)) {
            List<PaymentDto> legacyResult = legacyDataSource.getPaymentsByLoan(loanAccountNumber);
            List<PaymentDto> modernResult = modernDataSource.getPaymentsByLoan(loanAccountNumber);
            comparator.compareSilently(legacyResult, modernResult,
                    "getPaymentsByLoan(" + loanAccountNumber + ")");
            return legacyResult;
        }
        return modernDataSource.getPaymentsByLoan(loanAccountNumber);
    }

    /** Returns the current datasource mode (for health/status endpoints) */
    public String getMode() {
        return mode;
    }

    /**
     * Allows runtime mode switching without restart.
     * Useful for toggling via an admin endpoint or during tests.
     */
    public void setMode(String mode) {
        log.info("Datasource mode changed from '{}' to '{}'", this.mode, mode);
        this.mode = mode;
    }
}
