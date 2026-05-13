package com.workshop.loanservice.migration;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Resolves legacy VARCHAR foreign key references to modern BIGINT ids.
 * <p>
 * In the legacy CDW schema, relationships are implicit string references
 * (e.g. BORR_ID in CDW_LN_ACCT references CDW_BORR_MSTR). The modern
 * schema uses auto-increment BIGINT primary keys with explicit FK constraints.
 * This resolver validates that every FK reference can be resolved before
 * the actual migration runs.
 * </p>
 */
public class FkLookupResolver {

    private final Map<String, Long> borrowerIdMap;   // legacy BORR_ID → modern borrowers.id
    private final Map<String, Long> productCodeMap;  // legacy PROD_CD → modern loan_products.id
    private final Map<String, Long> loanAccountMap;  // legacy LN_ACCT_NBR → modern loan_accounts.id

    /**
     * @param borrowerIdMap  mapping of legacy BORR_ID to modern borrowers.id
     * @param productCodeMap mapping of legacy PROD_CD to modern loan_products.id
     * @param loanAccountMap mapping of legacy LN_ACCT_NBR to modern loan_accounts.id
     */
    public FkLookupResolver(Map<String, Long> borrowerIdMap,
                            Map<String, Long> productCodeMap,
                            Map<String, Long> loanAccountMap) {
        this.borrowerIdMap = borrowerIdMap;
        this.productCodeMap = productCodeMap;
        this.loanAccountMap = loanAccountMap;
    }

    /**
     * Resolve a legacy BORR_ID to the modern borrowers.id.
     * Returns ERROR if not found (borrower_id is NOT NULL with FK constraint).
     */
    public ValidationResult<Long> resolveBorrowerId(String legacyBorrId) {
        if (legacyBorrId == null || legacyBorrId.isBlank()) {
            return ValidationResult.error("borrower_id", legacyBorrId,
                    "Borrower ID is null or blank — cannot resolve FK reference");
        }
        Long modernId = borrowerIdMap.get(legacyBorrId);
        if (modernId == null) {
            return ValidationResult.error("borrower_id", legacyBorrId,
                    "No matching borrower found for legacy BORR_ID '" + legacyBorrId
                            + "' — FK constraint will fail");
        }
        return ValidationResult.ok(modernId);
    }

    /**
     * Resolve a legacy PROD_CD to the modern loan_products.id.
     * Returns ERROR if not found (product_id is NOT NULL with FK constraint).
     */
    public ValidationResult<Long> resolveProductId(String legacyProdCd) {
        if (legacyProdCd == null || legacyProdCd.isBlank()) {
            return ValidationResult.error("product_id", legacyProdCd,
                    "Product code is null or blank — cannot resolve FK reference");
        }
        Long modernId = productCodeMap.get(legacyProdCd);
        if (modernId == null) {
            return ValidationResult.error("product_id", legacyProdCd,
                    "No matching product found for legacy PROD_CD '" + legacyProdCd
                            + "' — FK constraint will fail");
        }
        return ValidationResult.ok(modernId);
    }

    /**
     * Resolve a legacy LN_ACCT_NBR to the modern loan_accounts.id.
     * Returns ERROR if not found (loan_account_id is NOT NULL with FK constraint).
     */
    public ValidationResult<Long> resolveLoanAccountId(String legacyAcctNbr) {
        if (legacyAcctNbr == null || legacyAcctNbr.isBlank()) {
            return ValidationResult.error("loan_account_id", legacyAcctNbr,
                    "Loan account number is null or blank — cannot resolve FK reference");
        }
        Long modernId = loanAccountMap.get(legacyAcctNbr);
        if (modernId == null) {
            return ValidationResult.error("loan_account_id", legacyAcctNbr,
                    "No matching loan account found for legacy LN_ACCT_NBR '" + legacyAcctNbr
                            + "' — FK constraint will fail");
        }
        return ValidationResult.ok(modernId);
    }

    /**
     * Pre-flight orphan scan: finds all BORR_ID and PROD_CD references in loan accounts
     * that do not exist in the borrower/product master tables.
     *
     * @param loans             all legacy loan accounts
     * @param knownBorrowerIds  set of all BORR_ID values from CDW_BORR_MSTR
     * @param knownProductCodes set of all PROD_CD values from CDW_LN_PROD
     * @return a PreFlightReport populated with orphaned references
     */
    public static PreFlightReport runOrphanScan(List<LegacyLoanAccount> loans,
                                                Set<String> knownBorrowerIds,
                                                Set<String> knownProductCodes) {
        PreFlightReport report = new PreFlightReport();

        for (LegacyLoanAccount loan : loans) {
            // Check borrower reference
            if (loan.getBorrowerId() != null
                    && !knownBorrowerIds.contains(loan.getBorrowerId())) {
                report.getOrphanedBorrowerIds().add(loan.getBorrowerId());
            }
            // Check product reference
            if (loan.getProductCode() != null
                    && !knownProductCodes.contains(loan.getProductCode())) {
                report.getOrphanedProductCodes().add(loan.getProductCode());
            }
        }

        return report;
    }

    /**
     * Reconcile denormalized borrower fields in CDW_LN_ACCT against CDW_BORR_MSTR.
     * Compares BORR_FST_NM and BORR_LST_NM in the loan record against the borrower master.
     *
     * @param loans       all legacy loan accounts
     * @param borrowerMap map of BORR_ID → LegacyBorrower for lookup
     * @return list of mismatches where the denormalized copy differs from the master
     */
    public static List<DenormMismatch> reconcileDenormalizedFields(
            List<LegacyLoanAccount> loans,
            Map<String, LegacyBorrower> borrowerMap) {

        List<DenormMismatch> mismatches = new ArrayList<>();

        for (LegacyLoanAccount loan : loans) {
            LegacyBorrower borrower = borrowerMap.get(loan.getBorrowerId());
            if (borrower == null) {
                // Orphan — handled by runOrphanScan; skip here
                continue;
            }

            // Compare first name
            if (!Objects.equals(loan.getBorrowerFirstName(), borrower.getFirstName())) {
                mismatches.add(new DenormMismatch(
                        loan.getLoanAccountNumber(), loan.getBorrowerId(),
                        "BORR_FST_NM",
                        loan.getBorrowerFirstName(), borrower.getFirstName()));
            }

            // Compare last name
            if (!Objects.equals(loan.getBorrowerLastName(), borrower.getLastName())) {
                mismatches.add(new DenormMismatch(
                        loan.getLoanAccountNumber(), loan.getBorrowerId(),
                        "BORR_LST_NM",
                        loan.getBorrowerLastName(), borrower.getLastName()));
            }
        }

        return mismatches;
    }
}
