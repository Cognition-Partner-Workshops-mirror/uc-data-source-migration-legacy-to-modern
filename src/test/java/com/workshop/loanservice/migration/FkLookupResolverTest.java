package com.workshop.loanservice.migration;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for {@link FkLookupResolver} — validates FK reference resolution,
 * orphan scanning, and denormalization reconciliation.
 */
class FkLookupResolverTest {

    private FkLookupResolver resolver;

    @BeforeEach
    void setUp() {
        // Build lookup maps simulating modern schema auto-increment IDs
        Map<String, Long> borrowerMap = Map.of(
                "B-10001", 1L, "B-10002", 2L, "B-10003", 3L);
        Map<String, Long> productMap = Map.of(
                "FXD30", 1L, "FXD15", 2L, "ARM51", 3L);
        Map<String, Long> loanMap = Map.of(
                "LN-2019-00142", 1L, "LN-2020-00398", 2L);

        resolver = new FkLookupResolver(borrowerMap, productMap, loanMap);
    }

    // =========================================================================
    // resolveBorrowerId — successful and missing lookups
    // =========================================================================

    @Test
    void resolveBorrowerId_exists_returnsModernId() {
        ValidationResult<Long> result = resolver.resolveBorrowerId("B-10001");
        assertTrue(result.isValid());
        assertEquals(1L, result.getValue());
    }

    @Test
    void resolveBorrowerId_missing_returnsError() {
        ValidationResult<Long> result = resolver.resolveBorrowerId("B-99999");
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
        assertTrue(result.getErrorMessage().contains("No matching borrower"));
    }

    @Test
    void resolveBorrowerId_null_returnsError() {
        ValidationResult<Long> result = resolver.resolveBorrowerId(null);
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    // =========================================================================
    // resolveProductId — successful and missing lookups
    // =========================================================================

    @Test
    void resolveProductId_exists_returnsModernId() {
        ValidationResult<Long> result = resolver.resolveProductId("FXD30");
        assertTrue(result.isValid());
        assertEquals(1L, result.getValue());
    }

    @Test
    void resolveProductId_missing_returnsError() {
        ValidationResult<Long> result = resolver.resolveProductId("UNKNOWN");
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
        assertTrue(result.getErrorMessage().contains("No matching product"));
    }

    // =========================================================================
    // resolveLoanAccountId — successful and missing lookups
    // =========================================================================

    @Test
    void resolveLoanAccountId_exists_returnsModernId() {
        ValidationResult<Long> result = resolver.resolveLoanAccountId("LN-2019-00142");
        assertTrue(result.isValid());
        assertEquals(1L, result.getValue());
    }

    @Test
    void resolveLoanAccountId_missing_returnsError() {
        ValidationResult<Long> result = resolver.resolveLoanAccountId("LN-INVALID");
        assertFalse(result.isValid());
        assertEquals(ValidationResult.Severity.ERROR, result.getSeverity());
    }

    // =========================================================================
    // runOrphanScan — identifies missing FK references
    // =========================================================================

    @Test
    void runOrphanScan_allReferencesExist_noOrphans() {
        LegacyLoanAccount loan = new LegacyLoanAccount();
        loan.setLoanAccountNumber("LN-001");
        loan.setBorrowerId("B-10001");
        loan.setProductCode("FXD30");

        Set<String> knownBorrowers = Set.of("B-10001", "B-10002");
        Set<String> knownProducts = Set.of("FXD30", "FXD15");

        PreFlightReport report = FkLookupResolver.runOrphanScan(
                List.of(loan), knownBorrowers, knownProducts);
        assertTrue(report.getOrphanedBorrowerIds().isEmpty());
        assertTrue(report.getOrphanedProductCodes().isEmpty());
    }

    @Test
    void runOrphanScan_missingBorrower_identified() {
        LegacyLoanAccount loan = new LegacyLoanAccount();
        loan.setLoanAccountNumber("LN-001");
        loan.setBorrowerId("B-ORPHAN");
        loan.setProductCode("FXD30");

        Set<String> knownBorrowers = Set.of("B-10001");
        Set<String> knownProducts = Set.of("FXD30");

        PreFlightReport report = FkLookupResolver.runOrphanScan(
                List.of(loan), knownBorrowers, knownProducts);
        assertTrue(report.getOrphanedBorrowerIds().contains("B-ORPHAN"));
    }

    @Test
    void runOrphanScan_missingProduct_identified() {
        LegacyLoanAccount loan = new LegacyLoanAccount();
        loan.setLoanAccountNumber("LN-001");
        loan.setBorrowerId("B-10001");
        loan.setProductCode("MYSTERY");

        Set<String> knownBorrowers = Set.of("B-10001");
        Set<String> knownProducts = Set.of("FXD30");

        PreFlightReport report = FkLookupResolver.runOrphanScan(
                List.of(loan), knownBorrowers, knownProducts);
        assertTrue(report.getOrphanedProductCodes().contains("MYSTERY"));
    }

    // =========================================================================
    // reconcileDenormalizedFields — detects name mismatches
    // =========================================================================

    @Test
    void reconcileDenormalizedFields_consistent_noMismatches() {
        // Loan has same names as borrower master — no mismatch expected
        LegacyBorrower borrower = new LegacyBorrower();
        borrower.setBorrowerId("B-10001");
        borrower.setFirstName("James");
        borrower.setLastName("Mitchell");

        LegacyLoanAccount loan = new LegacyLoanAccount();
        loan.setLoanAccountNumber("LN-001");
        loan.setBorrowerId("B-10001");
        loan.setBorrowerFirstName("James");
        loan.setBorrowerLastName("Mitchell");

        Map<String, LegacyBorrower> borrowerMap = Map.of("B-10001", borrower);
        List<DenormMismatch> mismatches = FkLookupResolver.reconcileDenormalizedFields(
                List.of(loan), borrowerMap);
        assertTrue(mismatches.isEmpty());
    }

    @Test
    void reconcileDenormalizedFields_nameMismatch_detected() {
        // Borrower master has different name than denormalized copy in loan
        LegacyBorrower borrower = new LegacyBorrower();
        borrower.setBorrowerId("B-10001");
        borrower.setFirstName("James");
        borrower.setLastName("Mitchell");

        LegacyLoanAccount loan = new LegacyLoanAccount();
        loan.setLoanAccountNumber("LN-001");
        loan.setBorrowerId("B-10001");
        loan.setBorrowerFirstName("Jim");        // Different from master
        loan.setBorrowerLastName("Mitchell");

        Map<String, LegacyBorrower> borrowerMap = Map.of("B-10001", borrower);
        List<DenormMismatch> mismatches = FkLookupResolver.reconcileDenormalizedFields(
                List.of(loan), borrowerMap);
        assertEquals(1, mismatches.size());
        assertEquals("BORR_FST_NM", mismatches.get(0).getFieldName());
        assertEquals("Jim", mismatches.get(0).getLoanValue());
        assertEquals("James", mismatches.get(0).getBorrowerValue());
    }

    @Test
    void reconcileDenormalizedFields_orphanedBorrower_skipped() {
        // If borrower not found in map, it's an orphan — handled by runOrphanScan
        LegacyLoanAccount loan = new LegacyLoanAccount();
        loan.setLoanAccountNumber("LN-001");
        loan.setBorrowerId("B-ORPHAN");
        loan.setBorrowerFirstName("Nobody");
        loan.setBorrowerLastName("Exists");

        Map<String, LegacyBorrower> borrowerMap = Map.of();
        List<DenormMismatch> mismatches = FkLookupResolver.reconcileDenormalizedFields(
                List.of(loan), borrowerMap);
        assertTrue(mismatches.isEmpty(), "Orphaned borrowers should be skipped");
    }
}
