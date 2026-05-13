package com.workshop.loanservice.migration;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration test for {@link MigrationPreFlightService} using the actual
 * seed data from data-legacy.sql. Verifies the full validation pipeline
 * against real CDW data loaded into the H2 in-memory database.
 */
@SpringBootTest
class MigrationPreFlightServiceTest {

    @Autowired
    private MigrationPreFlightService preFlightService;

    @Test
    void runFullValidation_seedData_returnsExpectedCounts() {
        // The seed data contains 5 borrowers, 5 products, 5 loans, 10 payments
        PreFlightReport report = preFlightService.runFullValidation();

        assertEquals(5, report.getTotalBorrowers(), "Expected 5 borrowers from seed data");
        assertEquals(5, report.getTotalProducts(), "Expected 5 products from seed data");
        assertEquals(5, report.getTotalLoans(), "Expected 5 loans from seed data");
        assertEquals(10, report.getTotalPayments(), "Expected 10 payments from seed data");
    }

    @Test
    void runFullValidation_catchesPaymentSumMismatch() {
        // PMT-2025120001 has components summing to 1887.02 vs total 1487.02 (delta 400.00)
        PreFlightReport report = preFlightService.runFullValidation();

        assertFalse(report.getPaymentSumMismatches().isEmpty(),
                "Expected at least one payment sum mismatch");
        assertTrue(report.getPaymentSumMismatches().stream()
                        .anyMatch(m -> "PMT-2025120001".equals(m.getPaymentId())),
                "Expected PMT-2025120001 to be flagged for component sum mismatch");
    }

    @Test
    void runFullValidation_denormalizationConsistent() {
        // Seed data has matching borrower names in CDW_LN_ACCT and CDW_BORR_MSTR
        PreFlightReport report = preFlightService.runFullValidation();

        assertTrue(report.getDenormMismatches().isEmpty(),
                "Expected no denormalization mismatches in seed data — all names should match");
    }

    @Test
    void runFullValidation_allFkReferencesResolve() {
        // All BORR_ID, PROD_CD, and LN_ACCT_NBR references in seed data should resolve
        PreFlightReport report = preFlightService.runFullValidation();

        assertTrue(report.getOrphanedBorrowerIds().isEmpty(),
                "Expected no orphaned borrower IDs in seed data");
        assertTrue(report.getOrphanedProductCodes().isEmpty(),
                "Expected no orphaned product codes in seed data");
        assertTrue(report.getOrphanedLoanAccounts().isEmpty(),
                "Expected no orphaned loan account numbers in seed data");
    }

    @Test
    void runFullValidation_allDatesParseCorrectly() {
        // All dates in seed data are in valid MM/DD/YYYY format
        // Errors would only come from date fields — no ERROR-level date issues expected
        PreFlightReport report = preFlightService.runFullValidation();

        // Check that no ERROR is about unparseable dates
        boolean hasDateError = report.getFailedRows().stream()
                .flatMap(row -> row.getErrors().stream())
                .anyMatch(e -> e.getErrorMessage() != null
                        && e.getErrorMessage().contains("Cannot parse date"));
        assertFalse(hasDateError, "Expected all dates to parse correctly in seed data");
    }

    @Test
    void runFullValidation_overallReportSummary() {
        PreFlightReport report = preFlightService.runFullValidation();

        // Should have warnings but the exact count depends on ambiguous dates, sum mismatches, etc.
        assertTrue(report.getWarningCount() > 0,
                "Expected at least some warnings (ambiguous dates, payment sum mismatch)");

        // Verify toSummaryString doesn't throw and contains key sections
        String summary = report.toSummaryString();
        assertNotNull(summary);
        assertTrue(summary.contains("Migration Pre-Flight Report"));
        assertTrue(summary.contains("Borrowers: 5"));
    }
}
