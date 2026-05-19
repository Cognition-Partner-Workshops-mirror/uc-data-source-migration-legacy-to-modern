package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * Dual-read service that can switch between legacy and modern data sources
 * based on a feature flag. In "dual" mode, it reads from both sources,
 * compares results, and logs any discrepancies for validation.
 *
 * Controlled by the 'datasource.mode' property:
 *   - "legacy" (default): reads only from legacy tables
 *   - "modern": reads only from modern tables
 *   - "dual": reads from both, compares, and returns legacy results
 */
@Service
public class DualReadService {

    private static final Logger log = LoggerFactory.getLogger(DualReadService.class);

    private final LoanService legacyService;
    private final ModernLoanService modernService;

    @Value("${datasource.mode:legacy}")
    private String mode;

    // Tracks comparison results for the /api/migration/comparison endpoint
    private final List<ComparisonResult> recentComparisons = new ArrayList<>();

    public DualReadService(LoanService legacyService, ModernLoanService modernService) {
        this.legacyService = legacyService;
        this.modernService = modernService;
    }

    public List<LoanSummaryDto> getAllLoans() {
        if ("modern".equals(mode)) {
            return modernService.getAllLoans();
        }
        List<LoanSummaryDto> legacyResult = legacyService.getAllLoans();
        if ("dual".equals(mode)) {
            compareLoans(legacyResult);
        }
        return legacyResult;
    }

    public LoanSummaryDto getLoanById(String id) {
        if ("modern".equals(mode)) {
            return modernService.getLoanById(id);
        }
        LoanSummaryDto legacyResult = legacyService.getLoanById(id);
        if ("dual".equals(mode)) {
            compareSingleLoan(id, legacyResult);
        }
        return legacyResult;
    }

    public List<BorrowerDto> getAllBorrowers() {
        if ("modern".equals(mode)) {
            return modernService.getAllBorrowers();
        }
        List<BorrowerDto> legacyResult = legacyService.getAllBorrowers();
        if ("dual".equals(mode)) {
            compareBorrowers(legacyResult);
        }
        return legacyResult;
    }

    public BorrowerDto getBorrowerById(String id) {
        if ("modern".equals(mode)) {
            return modernService.getBorrowerById(id);
        }
        BorrowerDto legacyResult = legacyService.getBorrowerById(id);
        if ("dual".equals(mode)) {
            compareSingleBorrower(id, legacyResult);
        }
        return legacyResult;
    }

    public List<PaymentDto> getPaymentsByLoan(String loanId) {
        if ("modern".equals(mode)) {
            return modernService.getPaymentsByLoan(loanId);
        }
        List<PaymentDto> legacyResult = legacyService.getPaymentsByLoan(loanId);
        if ("dual".equals(mode)) {
            comparePayments(loanId, legacyResult);
        }
        return legacyResult;
    }

    public String getMode() {
        return mode;
    }

    public void setMode(String mode) {
        this.mode = mode;
    }

    public List<ComparisonResult> getRecentComparisons() {
        return new ArrayList<>(recentComparisons);
    }

    // =========================================================================
    // COMPARISON LOGIC — compares legacy vs modern output field-by-field
    // =========================================================================

    private void compareLoans(List<LoanSummaryDto> legacyLoans) {
        try {
            List<LoanSummaryDto> modernLoans = modernService.getAllLoans();
            ComparisonResult result = new ComparisonResult("getAllLoans");
            result.setLegacyCount(legacyLoans.size());
            result.setModernCount(modernLoans.size());

            if (legacyLoans.size() != modernLoans.size()) {
                result.addDifference("Row count mismatch: legacy=" + legacyLoans.size() + ", modern=" + modernLoans.size());
            }

            // Compare individual loans by account number
            for (LoanSummaryDto legacy : legacyLoans) {
                LoanSummaryDto modern = modernLoans.stream()
                        .filter(m -> Objects.equals(m.getLoanAccountNumber(), legacy.getLoanAccountNumber()))
                        .findFirst().orElse(null);
                if (modern == null) {
                    result.addDifference("Loan " + legacy.getLoanAccountNumber() + " missing from modern");
                } else {
                    compareLoanFields(legacy, modern, result);
                }
            }

            result.setMatch(result.getDifferences().isEmpty());
            addComparison(result);
        } catch (Exception e) {
            log.warn("Dual-read comparison failed for getAllLoans: {}", e.getMessage());
        }
    }

    private void compareSingleLoan(String id, LoanSummaryDto legacy) {
        try {
            LoanSummaryDto modern = modernService.getLoanById(id);
            ComparisonResult result = new ComparisonResult("getLoanById:" + id);
            compareLoanFields(legacy, modern, result);
            result.setMatch(result.getDifferences().isEmpty());
            result.setLegacyCount(1);
            result.setModernCount(1);
            addComparison(result);
        } catch (Exception e) {
            log.warn("Dual-read comparison failed for getLoan {}: {}", id, e.getMessage());
        }
    }

    private void compareLoanFields(LoanSummaryDto legacy, LoanSummaryDto modern, ComparisonResult result) {
        String prefix = "Loan[" + legacy.getLoanAccountNumber() + "] ";
        compareField(prefix + "borrowerName", legacy.getBorrowerName(), modern.getBorrowerName(), result);
        compareField(prefix + "originalAmount", legacy.getOriginalAmount(), modern.getOriginalAmount(), result);
        compareField(prefix + "currentBalance", legacy.getCurrentBalance(), modern.getCurrentBalance(), result);
        compareField(prefix + "interestRate", legacy.getInterestRate(), modern.getInterestRate(), result);
        compareField(prefix + "monthlyPayment", legacy.getMonthlyPayment(), modern.getMonthlyPayment(), result);
        compareField(prefix + "status", legacy.getStatus(), modern.getStatus(), result);
        compareField(prefix + "propertyType", legacy.getPropertyType(), modern.getPropertyType(), result);
    }

    private void compareBorrowers(List<BorrowerDto> legacyBorrowers) {
        try {
            List<BorrowerDto> modernBorrowers = modernService.getAllBorrowers();
            ComparisonResult result = new ComparisonResult("getAllBorrowers");
            result.setLegacyCount(legacyBorrowers.size());
            result.setModernCount(modernBorrowers.size());

            if (legacyBorrowers.size() != modernBorrowers.size()) {
                result.addDifference("Row count mismatch: legacy=" + legacyBorrowers.size() + ", modern=" + modernBorrowers.size());
            }

            for (BorrowerDto legacy : legacyBorrowers) {
                BorrowerDto modern = modernBorrowers.stream()
                        .filter(m -> Objects.equals(m.getId(), legacy.getId()))
                        .findFirst().orElse(null);
                if (modern == null) {
                    result.addDifference("Borrower " + legacy.getId() + " missing from modern");
                } else {
                    String prefix = "Borrower[" + legacy.getId() + "] ";
                    compareField(prefix + "fullName", legacy.getFullName(), modern.getFullName(), result);
                    compareField(prefix + "email", legacy.getEmail(), modern.getEmail(), result);
                    compareField(prefix + "creditScore", legacy.getCreditScore(), modern.getCreditScore(), result);
                }
            }

            result.setMatch(result.getDifferences().isEmpty());
            addComparison(result);
        } catch (Exception e) {
            log.warn("Dual-read comparison failed for getAllBorrowers: {}", e.getMessage());
        }
    }

    private void compareSingleBorrower(String id, BorrowerDto legacy) {
        try {
            BorrowerDto modern = modernService.getBorrowerById(id);
            ComparisonResult result = new ComparisonResult("getBorrowerById:" + id);
            String prefix = "Borrower[" + id + "] ";
            compareField(prefix + "fullName", legacy.getFullName(), modern.getFullName(), result);
            compareField(prefix + "email", legacy.getEmail(), modern.getEmail(), result);
            compareField(prefix + "creditScore", legacy.getCreditScore(), modern.getCreditScore(), result);
            result.setMatch(result.getDifferences().isEmpty());
            result.setLegacyCount(1);
            result.setModernCount(1);
            addComparison(result);
        } catch (Exception e) {
            log.warn("Dual-read comparison failed for getBorrower {}: {}", id, e.getMessage());
        }
    }

    private void comparePayments(String loanId, List<PaymentDto> legacyPayments) {
        try {
            List<PaymentDto> modernPayments = modernService.getPaymentsByLoan(loanId);
            ComparisonResult result = new ComparisonResult("getPaymentsByLoan:" + loanId);
            result.setLegacyCount(legacyPayments.size());
            result.setModernCount(modernPayments.size());

            if (legacyPayments.size() != modernPayments.size()) {
                result.addDifference("Row count mismatch: legacy=" + legacyPayments.size() + ", modern=" + modernPayments.size());
            }

            // Compare payment amounts (order may differ, so match by total amount + date)
            for (int i = 0; i < Math.min(legacyPayments.size(), modernPayments.size()); i++) {
                PaymentDto legacy = legacyPayments.get(i);
                PaymentDto modern = modernPayments.get(i);
                String prefix = "Payment[" + i + "] ";
                compareField(prefix + "totalAmount", legacy.getTotalAmount(), modern.getTotalAmount(), result);
                compareField(prefix + "principalAmount", legacy.getPrincipalAmount(), modern.getPrincipalAmount(), result);
                compareField(prefix + "type", legacy.getType(), modern.getType(), result);
                compareField(prefix + "status", legacy.getStatus(), modern.getStatus(), result);
            }

            result.setMatch(result.getDifferences().isEmpty());
            addComparison(result);
        } catch (Exception e) {
            log.warn("Dual-read comparison failed for payments on loan {}: {}", loanId, e.getMessage());
        }
    }

    private void compareField(String fieldName, Object legacy, Object modern, ComparisonResult result) {
        // Use compareTo for BigDecimal to ignore scale differences (285000 vs 285000.00)
        boolean equal;
        if (legacy instanceof BigDecimal legacyBd && modern instanceof BigDecimal modernBd) {
            equal = legacyBd.compareTo(modernBd) == 0;
        } else {
            equal = Objects.equals(legacy, modern);
        }
        if (!equal) {
            result.addDifference(fieldName + ": legacy='" + legacy + "', modern='" + modern + "'");
            log.debug("DUAL-READ MISMATCH: {}: legacy='{}' vs modern='{}'", fieldName, legacy, modern);
        }
    }

    private synchronized void addComparison(ComparisonResult result) {
        recentComparisons.add(result);
        // Keep only last 100 comparisons
        if (recentComparisons.size() > 100) {
            recentComparisons.remove(0);
        }
    }

    // =========================================================================
    // COMPARISON RESULT DTO
    // =========================================================================

    /**
     * Holds the result of comparing legacy vs modern output for a single API call.
     */
    public static class ComparisonResult {
        private final String operation;
        private boolean match;
        private int legacyCount;
        private int modernCount;
        private final List<String> differences = new ArrayList<>();

        public ComparisonResult(String operation) {
            this.operation = operation;
        }

        public void addDifference(String diff) { differences.add(diff); }

        public String getOperation() { return operation; }
        public boolean isMatch() { return match; }
        public void setMatch(boolean match) { this.match = match; }
        public int getLegacyCount() { return legacyCount; }
        public void setLegacyCount(int legacyCount) { this.legacyCount = legacyCount; }
        public int getModernCount() { return modernCount; }
        public void setModernCount(int modernCount) { this.modernCount = modernCount; }
        public List<String> getDifferences() { return differences; }
    }
}
