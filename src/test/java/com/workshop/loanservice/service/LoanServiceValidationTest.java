package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration tests verifying that the LoanService correctly applies
 * data quality validation when translating legacy seed data.
 */
@SpringBootTest
class LoanServiceValidationTest {

    @Autowired
    private LoanService loanService;

    // =========================================================================
    // ANO-001: Numeric parsing — no more unhandled NumberFormatException
    // =========================================================================

    @Test
    void allLoansReturnValidNumericFields() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertFalse(loans.isEmpty());
        for (LoanSummaryDto loan : loans) {
            assertNotNull(loan.getOriginalAmount(), "originalAmount should not be null for " + loan.getLoanAccountNumber());
            assertNotNull(loan.getCurrentBalance(), "currentBalance should not be null for " + loan.getLoanAccountNumber());
            assertNotNull(loan.getInterestRate(), "interestRate should not be null for " + loan.getLoanAccountNumber());
            assertNotNull(loan.getMonthlyPayment(), "monthlyPayment should not be null for " + loan.getLoanAccountNumber());
            assertTrue(loan.getOriginalAmount().compareTo(BigDecimal.ZERO) > 0);
        }
    }

    // =========================================================================
    // ANO-002: Dates normalized to ISO format
    // =========================================================================

    @Test
    void originationDatesAreIsoFormatted() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        for (LoanSummaryDto loan : loans) {
            String date = loan.getOriginationDate();
            assertNotNull(date);
            // ISO format: yyyy-MM-dd
            assertTrue(date.matches("\\d{4}-\\d{2}-\\d{2}"),
                    "Expected ISO date format but got: " + date + " for " + loan.getLoanAccountNumber());
        }
    }

    @Test
    void paymentDatesAreIsoFormatted() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());
        for (PaymentDto pmt : payments) {
            String date = pmt.getPaymentDate();
            assertNotNull(date);
            assertTrue(date.matches("\\d{4}-\\d{2}-\\d{2}"),
                    "Expected ISO date format but got: " + date + " for " + pmt.getPaymentId());
        }
    }

    // =========================================================================
    // ANO-003: Payment integrity warnings surfaced
    // =========================================================================

    @Test
    void paymentIntegrityWarningsForMismatchedComponents() {
        // PMT-2025120001 has components that exceed the total by $400
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());

        boolean foundWarning = payments.stream()
                .anyMatch(p -> !p.getDataQualityWarnings().isEmpty());
        assertTrue(foundWarning, "Expected data quality warnings for payment component mismatch");
    }

    @Test
    void paymentWithMatchingComponentsHasNoIntegrityWarning() {
        // LN-2020-00398 payments should sum correctly
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");
        for (PaymentDto pmt : payments) {
            boolean hasIntegrityWarning = pmt.getDataQualityWarnings().stream()
                    .anyMatch(w -> w.contains("component sum"));
            assertFalse(hasIntegrityWarning,
                    "Did not expect integrity warnings for " + pmt.getPaymentId());
        }
    }

    // =========================================================================
    // ANO-006: Null safety for required fields
    // =========================================================================

    @Test
    void borrowerNamesAreNeverNull() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        for (BorrowerDto b : borrowers) {
            assertNotNull(b.getFullName());
            assertFalse(b.getFullName().contains("null"),
                    "Borrower name should not contain 'null': " + b.getFullName());
        }
    }

    @Test
    void loanBorrowerNamesAreNeverNull() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        for (LoanSummaryDto loan : loans) {
            assertNotNull(loan.getBorrowerName());
            assertFalse(loan.getBorrowerName().contains("null"),
                    "Loan borrower name should not contain 'null': " + loan.getBorrowerName());
        }
    }

    // =========================================================================
    // ANO-009: Credit scores are valid
    // =========================================================================

    @Test
    void allCreditScoresAreInValidRange() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        for (BorrowerDto b : borrowers) {
            if (b.getCreditScore() != null) {
                assertTrue(b.getCreditScore() >= 300 && b.getCreditScore() <= 850,
                        "Credit score out of range for " + b.getId() + ": " + b.getCreditScore());
            }
        }
    }

    // =========================================================================
    // ANO-011: Delinquency/status warnings
    // =========================================================================

    @Test
    void delinquentActiveLoanHasWarning() {
        // LN-2018-00089 has 15 delinquency days but status ACT
        LoanSummaryDto loan = loanService.getLoanById("LN-2018-00089");
        boolean hasDelinquencyWarning = loan.getDataQualityWarnings().stream()
                .anyMatch(w -> w.contains("delinquency days"));
        assertTrue(hasDelinquencyWarning,
                "Expected delinquency/status consistency warning for LN-2018-00089");
    }

    @Test
    void nonDelinquentLoanHasNoStatusWarning() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        boolean hasDelinquencyWarning = loan.getDataQualityWarnings().stream()
                .anyMatch(w -> w.contains("delinquency days"));
        assertFalse(hasDelinquencyWarning,
                "Did not expect delinquency warning for LN-2019-00142");
    }

    // =========================================================================
    // ANO-013: Payment sort order is chronological
    // =========================================================================

    @Test
    void paymentsAreSortedChronologicallyDescending() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(2, payments.size());
        // December should come before November in descending order
        assertTrue(payments.get(0).getPaymentDate().compareTo(payments.get(1).getPaymentDate()) >= 0,
                "Payments should be sorted descending: " + payments.get(0).getPaymentDate()
                        + " >= " + payments.get(1).getPaymentDate());
    }

    // =========================================================================
    // ANO-014: Annual income now exposed
    // =========================================================================

    @Test
    void borrowerHasAnnualIncome() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertNotNull(borrower.getAnnualIncome());
        assertEquals(new BigDecimal("92500"), borrower.getAnnualIncome());
    }

    @Test
    void allBorrowersHaveAnnualIncome() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        for (BorrowerDto b : borrowers) {
            assertNotNull(b.getAnnualIncome(),
                    "Annual income should be parsed for " + b.getId());
            assertTrue(b.getAnnualIncome().compareTo(BigDecimal.ZERO) > 0,
                    "Annual income should be positive for " + b.getId());
        }
    }
}
