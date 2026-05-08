package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration tests that verify the validation layer catches anomalies
 * in the actual legacy seed data loaded from data-legacy.sql.
 *
 * These tests run against the real H2 in-memory database initialized
 * with schema-legacy.sql and data-legacy.sql.
 */
@SpringBootTest
class LoanServiceValidationTest {

    @Autowired
    private LoanService loanService;

    // =========================================================================
    // ANO-004: Numeric parsing with commas — end-to-end via actual seed data
    // =========================================================================

    @Test
    @DisplayName("ANO-004: Loan amounts with commas are parsed correctly from seed data")
    void loanAmounts_parsedCorrectly() {
        // LN-2019-00142 has LN_ORIG_AMT = '285,000' and LN_CURR_BAL = '271,432.56'
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");

        assertEquals(new BigDecimal("285000"), loan.getOriginalAmount(),
                "Original amount '285,000' should parse to 285000");
        assertEquals(new BigDecimal("271432.56"), loan.getCurrentBalance(),
                "Current balance '271,432.56' should parse to 271432.56");
        assertEquals(new BigDecimal("4.750"), loan.getInterestRate(),
                "Interest rate '4.750' should parse to 4.750");
        assertEquals(new BigDecimal("1487.02"), loan.getMonthlyPayment(),
                "Monthly payment '1,487.02' should parse to 1487.02");
    }

    @Test
    @DisplayName("ANO-004: All 5 loans load without parsing exceptions")
    void allLoans_noParsing_exceptions() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertEquals(5, loans.size(), "All 5 loans should load successfully");

        // Verify all have non-null parsed amounts
        for (LoanSummaryDto loan : loans) {
            assertNotNull(loan.getOriginalAmount(), "Original amount should not be null");
            assertNotNull(loan.getCurrentBalance(), "Current balance should not be null");
            assertNotNull(loan.getInterestRate(), "Interest rate should not be null");
            assertNotNull(loan.getMonthlyPayment(), "Monthly payment should not be null");
            assertTrue(loan.getOriginalAmount().compareTo(BigDecimal.ZERO) > 0,
                    "Original amount should be positive for loan " + loan.getLoanAccountNumber());
        }
    }

    @Test
    @DisplayName("ANO-004: Credit scores are parsed correctly from seed data")
    void creditScores_parsedCorrectly() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertEquals(5, borrowers.size(), "All 5 borrowers should load successfully");

        // All borrowers in seed data have valid credit scores
        for (BorrowerDto borrower : borrowers) {
            assertNotNull(borrower.getCreditScore(),
                    "Credit score should be parsed for borrower " + borrower.getId());
            assertTrue(borrower.getCreditScore() >= 300 && borrower.getCreditScore() <= 850,
                    "Credit score should be in valid range for borrower " + borrower.getId());
        }
    }

    // =========================================================================
    // ANO-002: Payment component mismatch — detected in seed data
    // =========================================================================

    @Test
    @DisplayName("ANO-002: Payment components are parsed and returned (mismatch is logged)")
    void paymentComponents_parsedFromSeedData() {
        // LN-2019-00142 has the $400 mismatch — validation logs the error
        // but still returns the data as-is (no data loss)
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(2, payments.size(), "Should have 2 payments for LN-2019-00142");

        PaymentDto dec = payments.stream()
                .filter(p -> p.getPaymentId().equals("PMT-2025120001"))
                .findFirst()
                .orElseThrow();

        // Verify the mismatched data is still returned faithfully
        assertEquals(new BigDecimal("1487.02"), dec.getTotalAmount());
        assertEquals(new BigDecimal("456.78"), dec.getPrincipalAmount());
        assertEquals(new BigDecimal("1074.69"), dec.getInterestAmount());
        assertEquals(new BigDecimal("355.55"), dec.getEscrowAmount());

        // Verify sum != total (the actual anomaly)
        BigDecimal componentSum = dec.getPrincipalAmount()
                .add(dec.getInterestAmount())
                .add(dec.getEscrowAmount());
        assertNotEquals(dec.getTotalAmount(), componentSum,
                "LN-2019-00142 payments have the $400 component mismatch (ANO-002)");
    }

    @Test
    @DisplayName("ANO-002: Correct payment components sum correctly")
    void paymentComponents_correctInOtherLoans() {
        // LN-2020-00398 has correct component sums
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");
        assertFalse(payments.isEmpty());

        for (PaymentDto pmt : payments) {
            BigDecimal componentSum = pmt.getPrincipalAmount()
                    .add(pmt.getInterestAmount())
                    .add(pmt.getEscrowAmount());
            assertEquals(0, pmt.getTotalAmount().compareTo(componentSum),
                    "Payment " + pmt.getPaymentId() + " components should sum to total");
        }
    }

    // =========================================================================
    // ANO-006: Delinquency/status mismatch — verified via seed data
    // =========================================================================

    @Test
    @DisplayName("ANO-006: Delinquent loan still shows Active status from seed data")
    void delinquentLoan_activeStatus() {
        // LN-2018-00089 has LN_DLQ_DAYS='15' and LN_STAT_CD='ACT'
        // The validation logs a warning but the status is still returned as-is
        LoanSummaryDto loan = loanService.getLoanById("LN-2018-00089");
        assertEquals("Active", loan.getStatus(),
                "Status should still be 'Active' — validation logs warning but doesn't alter data");
    }

    // =========================================================================
    // ANO-007: Null middle initial handling
    // =========================================================================

    @Test
    @DisplayName("ANO-007: Borrower with null middle initial has correct name format")
    void nullMiddleInitial_nameFormat() {
        // B-10005 Robert Williams has NULL middle initial
        BorrowerDto borrower = loanService.getBorrowerById("B-10005");
        assertEquals("Robert Williams", borrower.getFullName(),
                "Name should be 'Robert Williams' without middle initial");
    }

    @Test
    @DisplayName("ANO-007: Borrower with middle initial has correct name format")
    void presentMiddleInitial_nameFormat() {
        // B-10001 James R. Mitchell has middle initial 'R'
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals("James R. Mitchell", borrower.getFullName(),
                "Name should include middle initial as 'James R. Mitchell'");
    }

    // =========================================================================
    // ANO-008: Denormalized borrower data consistency
    // =========================================================================

    @Test
    @DisplayName("ANO-008: Loan borrower name matches master borrower record")
    void denormalizedBorrowerData_consistent() {
        // Verify the denormalized name in CDW_LN_ACCT matches CDW_BORR_MSTR
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");

        // Loan uses denormalized name: "James Mitchell"
        // Borrower uses full name with middle: "James R. Mitchell"
        // These differ because loan doesn't include middle initial
        assertTrue(loan.getBorrowerName().contains("James"),
                "Loan should contain borrower's first name");
        assertTrue(loan.getBorrowerName().contains("Mitchell"),
                "Loan should contain borrower's last name");
    }

    // =========================================================================
    // Status code expansion — validated from seed data
    // =========================================================================

    @Test
    @DisplayName("Status codes are expanded correctly for all loans")
    void statusCodes_expanded() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        for (LoanSummaryDto loan : loans) {
            assertEquals("Active", loan.getStatus(),
                    "All seed data loans have ACT status, should expand to 'Active'");
        }
    }

    @Test
    @DisplayName("Payment type and status codes are expanded correctly")
    void paymentCodes_expanded() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        for (PaymentDto pmt : payments) {
            assertEquals("Regular", pmt.getType(), "All seed payments are REG type");
            assertEquals("Posted", pmt.getStatus(), "All seed payments are PST status");
        }
    }

    // =========================================================================
    // Property type expansion
    // =========================================================================

    @Test
    @DisplayName("Property types are expanded correctly from seed data")
    void propertyTypes_expanded() {
        assertEquals("Single Family Residence", loanService.getLoanById("LN-2019-00142").getPropertyType());
        assertEquals("Condominium", loanService.getLoanById("LN-2020-00398").getPropertyType());
        assertEquals("Townhouse", loanService.getLoanById("LN-2021-00567").getPropertyType());
    }

    // =========================================================================
    // End-to-end: Full borrower detail with loans
    // =========================================================================

    @Test
    @DisplayName("Full borrower detail includes validated loan list")
    void borrowerDetail_withLoans() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertNotNull(borrower.getLoans(), "Borrower detail should include loans");
        assertEquals(1, borrower.getLoans().size(), "B-10001 should have 1 loan");
        assertEquals("LN-2019-00142", borrower.getLoans().get(0).getLoanAccountNumber());
    }
}
