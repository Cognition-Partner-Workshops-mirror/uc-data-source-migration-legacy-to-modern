package com.workshop.loanservice.migration;

import java.util.ArrayList;
import java.util.List;

/**
 * Aggregated report from a complete pre-flight validation run across
 * all legacy tables. Contains row counts, error/warning tallies,
 * failed row details, orphaned FK references, denormalization mismatches,
 * and payment sum discrepancies.
 */
public class PreFlightReport {

    private int totalBorrowers;
    private int totalProducts;
    private int totalLoans;
    private int totalPayments;
    private int errorCount;
    private int warningCount;

    // Detailed per-row validation reports for rows that have errors or warnings
    private final List<ValidationReport> failedRows = new ArrayList<>();

    // Denormalized field mismatches (CDW_LN_ACCT vs CDW_BORR_MSTR)
    private final List<DenormMismatch> denormMismatches = new ArrayList<>();

    // Orphaned FK references — legacy IDs with no matching master record
    private final List<String> orphanedBorrowerIds = new ArrayList<>();
    private final List<String> orphanedProductCodes = new ArrayList<>();
    private final List<String> orphanedLoanAccounts = new ArrayList<>();

    // Payment component sum mismatches
    private final List<PaymentSumMismatch> paymentSumMismatches = new ArrayList<>();

    /** Human-readable summary of the entire pre-flight validation */
    public String toSummaryString() {
        StringBuilder sb = new StringBuilder();
        sb.append("=== Migration Pre-Flight Report ===\n");
        sb.append(String.format("Borrowers: %d | Products: %d | Loans: %d | Payments: %d%n",
                totalBorrowers, totalProducts, totalLoans, totalPayments));
        sb.append(String.format("Errors: %d | Warnings: %d%n", errorCount, warningCount));
        sb.append(String.format("Failed rows: %d%n", failedRows.size()));
        sb.append(String.format("Orphaned borrower IDs: %s%n", orphanedBorrowerIds));
        sb.append(String.format("Orphaned product codes: %s%n", orphanedProductCodes));
        sb.append(String.format("Orphaned loan accounts: %s%n", orphanedLoanAccounts));
        sb.append(String.format("Denorm mismatches: %d%n", denormMismatches.size()));
        sb.append(String.format("Payment sum mismatches: %d%n", paymentSumMismatches.size()));

        // List each failed row summary
        if (!failedRows.isEmpty()) {
            sb.append("\n--- Failed Row Details ---\n");
            for (ValidationReport row : failedRows) {
                sb.append("  ").append(row.getSummary()).append("\n");
                for (ValidationResult<?> r : row.getResults()) {
                    sb.append("    ").append(r.toString()).append("\n");
                }
            }
        }

        // List payment sum mismatches
        if (!paymentSumMismatches.isEmpty()) {
            sb.append("\n--- Payment Sum Mismatches ---\n");
            for (PaymentSumMismatch m : paymentSumMismatches) {
                sb.append("  ").append(m.toString()).append("\n");
            }
        }

        return sb.toString();
    }

    // ---- Accessors and mutators ----

    public int getTotalBorrowers() { return totalBorrowers; }
    public void setTotalBorrowers(int totalBorrowers) { this.totalBorrowers = totalBorrowers; }

    public int getTotalProducts() { return totalProducts; }
    public void setTotalProducts(int totalProducts) { this.totalProducts = totalProducts; }

    public int getTotalLoans() { return totalLoans; }
    public void setTotalLoans(int totalLoans) { this.totalLoans = totalLoans; }

    public int getTotalPayments() { return totalPayments; }
    public void setTotalPayments(int totalPayments) { this.totalPayments = totalPayments; }

    public int getErrorCount() { return errorCount; }
    public void setErrorCount(int errorCount) { this.errorCount = errorCount; }

    public int getWarningCount() { return warningCount; }
    public void setWarningCount(int warningCount) { this.warningCount = warningCount; }

    public List<ValidationReport> getFailedRows() { return failedRows; }

    public List<DenormMismatch> getDenormMismatches() { return denormMismatches; }

    public List<String> getOrphanedBorrowerIds() { return orphanedBorrowerIds; }

    public List<String> getOrphanedProductCodes() { return orphanedProductCodes; }

    public List<String> getOrphanedLoanAccounts() { return orphanedLoanAccounts; }

    public List<PaymentSumMismatch> getPaymentSumMismatches() { return paymentSumMismatches; }
}
