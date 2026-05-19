package com.workshop.loanservice;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.service.DataMigrationService;
import com.workshop.loanservice.service.DualReadService;
import com.workshop.loanservice.service.LoanService;
import com.workshop.loanservice.service.ModernLoanService;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration tests that verify the full migration pipeline:
 * 1. Run migration from legacy to modern
 * 2. Verify row counts match
 * 3. Compare legacy vs modern API output (golden file parity)
 * 4. Verify dual-read mode detects no differences
 */
@SpringBootTest
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class DataMigrationTest {

    @Autowired
    private DataMigrationService migrationService;

    @Autowired
    private LoanService legacyService;

    @Autowired
    private ModernLoanService modernService;

    @Autowired
    private DualReadService dualReadService;

    private DataMigrationService.MigrationReport report;

    @BeforeAll
    void runMigration() {
        // Run migration once before all tests
        report = migrationService.runMigration();
    }

    @Test
    @Order(1)
    void migrationShouldCompleteWithoutErrors() {
        // Verify no errors occurred during migration
        assertTrue(report.getErrors().isEmpty(),
                "Migration had errors: " + report.getErrors());
    }

    @Test
    @Order(2)
    void migrationShouldMigrateAllBorrowers() {
        // 5 borrowers in legacy seed data
        assertEquals(5, report.getBorrowersMigrated(),
                "Expected 5 borrowers migrated");
    }

    @Test
    @Order(3)
    void migrationShouldMigrateAllProducts() {
        // 5 loan products in legacy seed data
        assertEquals(5, report.getProductsMigrated(),
                "Expected 5 products migrated");
    }

    @Test
    @Order(4)
    void migrationShouldMigrateAllAccounts() {
        // 5 loan accounts in legacy seed data
        assertEquals(5, report.getAccountsMigrated(),
                "Expected 5 accounts migrated");
    }

    @Test
    @Order(5)
    void migrationShouldMigrateAllPayments() {
        // 10 payments in legacy seed data
        assertEquals(10, report.getPaymentsMigrated(),
                "Expected 10 payments migrated");
    }

    @Test
    @Order(6)
    void modernLoansShouldMatchLegacyLoans() {
        // Golden file parity: compare loan list from both sources
        List<LoanSummaryDto> legacyLoans = legacyService.getAllLoans();
        List<LoanSummaryDto> modernLoans = modernService.getAllLoans();

        assertEquals(legacyLoans.size(), modernLoans.size(),
                "Loan count mismatch");

        for (LoanSummaryDto legacy : legacyLoans) {
            LoanSummaryDto modern = modernLoans.stream()
                    .filter(m -> m.getLoanAccountNumber().equals(legacy.getLoanAccountNumber()))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError("Loan " + legacy.getLoanAccountNumber() + " missing from modern"));

            assertEquals(legacy.getBorrowerName(), modern.getBorrowerName(),
                    "Borrower name mismatch for " + legacy.getLoanAccountNumber());
            assertEquals(0, legacy.getOriginalAmount().compareTo(modern.getOriginalAmount()),
                    "Original amount mismatch for " + legacy.getLoanAccountNumber());
            assertEquals(0, legacy.getCurrentBalance().compareTo(modern.getCurrentBalance()),
                    "Current balance mismatch for " + legacy.getLoanAccountNumber());
            assertEquals(0, legacy.getInterestRate().compareTo(modern.getInterestRate()),
                    "Interest rate mismatch for " + legacy.getLoanAccountNumber());
            assertEquals(0, legacy.getMonthlyPayment().compareTo(modern.getMonthlyPayment()),
                    "Monthly payment mismatch for " + legacy.getLoanAccountNumber());
            assertEquals(legacy.getStatus(), modern.getStatus(),
                    "Status mismatch for " + legacy.getLoanAccountNumber());
            assertEquals(legacy.getPropertyType(), modern.getPropertyType(),
                    "Property type mismatch for " + legacy.getLoanAccountNumber());
        }
    }

    @Test
    @Order(7)
    void modernBorrowersShouldMatchLegacyBorrowers() {
        // Golden file parity: compare borrower list from both sources
        List<BorrowerDto> legacyBorrowers = legacyService.getAllBorrowers();
        List<BorrowerDto> modernBorrowers = modernService.getAllBorrowers();

        assertEquals(legacyBorrowers.size(), modernBorrowers.size(),
                "Borrower count mismatch");

        for (BorrowerDto legacy : legacyBorrowers) {
            BorrowerDto modern = modernBorrowers.stream()
                    .filter(m -> m.getId().equals(legacy.getId()))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError("Borrower " + legacy.getId() + " missing from modern"));

            assertEquals(legacy.getFullName(), modern.getFullName(),
                    "Name mismatch for " + legacy.getId());
            assertEquals(legacy.getEmail(), modern.getEmail(),
                    "Email mismatch for " + legacy.getId());
            assertEquals(legacy.getCreditScore(), modern.getCreditScore(),
                    "Credit score mismatch for " + legacy.getId());
            assertEquals(legacy.getEmploymentStatus(), modern.getEmploymentStatus(),
                    "Employment status mismatch for " + legacy.getId());
            assertEquals(legacy.getCity(), modern.getCity(),
                    "City mismatch for " + legacy.getId());
            assertEquals(legacy.getState(), modern.getState(),
                    "State mismatch for " + legacy.getId());
        }
    }

    @Test
    @Order(8)
    void modernPaymentsShouldMatchLegacyPayments() {
        // Golden file parity: compare payments for each loan
        List<LoanSummaryDto> loans = legacyService.getAllLoans();

        for (LoanSummaryDto loan : loans) {
            List<PaymentDto> legacyPayments = legacyService.getPaymentsByLoan(loan.getLoanAccountNumber());
            List<PaymentDto> modernPayments = modernService.getPaymentsByLoan(loan.getLoanAccountNumber());

            assertEquals(legacyPayments.size(), modernPayments.size(),
                    "Payment count mismatch for loan " + loan.getLoanAccountNumber());

            for (int i = 0; i < legacyPayments.size(); i++) {
                PaymentDto legacy = legacyPayments.get(i);
                PaymentDto modern = modernPayments.get(i);

                assertEquals(0, legacy.getTotalAmount().compareTo(modern.getTotalAmount()),
                        "Total amount mismatch for payment " + i + " on loan " + loan.getLoanAccountNumber());
                assertEquals(0, legacy.getPrincipalAmount().compareTo(modern.getPrincipalAmount()),
                        "Principal mismatch for payment " + i);
                assertEquals(0, legacy.getInterestAmount().compareTo(modern.getInterestAmount()),
                        "Interest mismatch for payment " + i);
                assertEquals(legacy.getType(), modern.getType(),
                        "Type mismatch for payment " + i);
                assertEquals(legacy.getStatus(), modern.getStatus(),
                        "Status mismatch for payment " + i);
            }
        }
    }

    @Test
    @Order(9)
    void dualReadModeShouldDetectNoDifferences() {
        // Switch to dual mode, exercise all endpoints, check comparisons
        dualReadService.setMode("dual");

        dualReadService.getAllLoans();
        dualReadService.getAllBorrowers();
        dualReadService.getLoanById("LN-2019-00142");
        dualReadService.getBorrowerById("B-10001");
        dualReadService.getPaymentsByLoan("LN-2019-00142");

        List<DualReadService.ComparisonResult> comparisons = dualReadService.getRecentComparisons();
        assertFalse(comparisons.isEmpty(), "No comparisons were recorded");

        for (DualReadService.ComparisonResult result : comparisons) {
            assertTrue(result.isMatch(),
                    "Dual-read mismatch in " + result.getOperation() + ": " + result.getDifferences());
        }

        // Reset mode
        dualReadService.setMode("legacy");
    }

    @Test
    @Order(10)
    void migrationShouldBeIdempotent() {
        // Running migration again should skip already-migrated records
        DataMigrationService.MigrationReport secondReport = migrationService.runMigration();
        assertEquals(0, secondReport.getBorrowersMigrated(),
                "Second migration should skip borrowers");
        assertEquals(0, secondReport.getProductsMigrated(),
                "Second migration should skip products");
        assertEquals(0, secondReport.getAccountsMigrated(),
                "Second migration should skip accounts");
        assertTrue(secondReport.getErrors().isEmpty(),
                "Second migration should have no errors");
    }
}
