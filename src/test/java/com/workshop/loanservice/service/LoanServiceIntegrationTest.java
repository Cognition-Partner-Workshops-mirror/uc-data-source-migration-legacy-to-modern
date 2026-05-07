package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.validation.DataQualityValidator;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration tests that verify the validated LoanService against
 * the actual legacy seed data loaded from data-legacy.sql.
 */
@SpringBootTest
class LoanServiceIntegrationTest {

    @Autowired
    private LoanService loanService;

    @Test
    @DisplayName("getAllLoans returns all 5 loans with validated data")
    void getAllLoansReturnsValidatedData() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertEquals(5, loans.size());

        LoanSummaryDto first = loans.stream()
                .filter(l -> "LN-2019-00142".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();

        assertEquals("James Mitchell", first.getBorrowerName());
        assertEquals("30-Year Fixed Rate Mortgage", first.getProductDescription());
        assertNotNull(first.getOriginalAmount());
        assertNotNull(first.getInterestRate());
        assertEquals("Active", first.getStatus());
        assertEquals("02/15/2019", first.getOriginationDate());
        assertEquals("Single Family Residence", first.getPropertyType());
    }

    @Test
    @DisplayName("getAllBorrowers returns all 5 borrowers with validated credit scores")
    void getAllBorrowersReturnsValidatedData() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertEquals(5, borrowers.size());

        BorrowerDto james = borrowers.stream()
                .filter(b -> "B-10001".equals(b.getId()))
                .findFirst()
                .orElseThrow();

        assertEquals("James R. Mitchell", james.getFullName());
        assertEquals(745, james.getCreditScore());
        assertEquals("j.mitchell@email.com", james.getEmail());

        // B-10005 has null middle initial - should still produce valid name
        BorrowerDto robert = borrowers.stream()
                .filter(b -> "B-10005".equals(b.getId()))
                .findFirst()
                .orElseThrow();

        assertEquals("Robert Williams", robert.getFullName());
        assertEquals(658, robert.getCreditScore());
    }

    @Test
    @DisplayName("getPaymentsByLoan returns chronologically sorted payments")
    void getPaymentsByLoanReturnsSortedPayments() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(2, payments.size());

        // Should be sorted descending by date (December before November)
        assertEquals("12/15/2025", payments.get(0).getPaymentDate());
        assertEquals("11/15/2025", payments.get(1).getPaymentDate());

        assertNotNull(payments.get(0).getTotalAmount());
        assertNotNull(payments.get(0).getPrincipalAmount());
        assertEquals("Regular", payments.get(0).getType());
        assertEquals("Posted", payments.get(0).getStatus());
    }

    @Test
    @DisplayName("getBorrowerById returns borrower with attached loans")
    void getBorrowerByIdReturnsLoans() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertNotNull(borrower);
        assertEquals("James R. Mitchell", borrower.getFullName());
        assertNotNull(borrower.getLoans());
        assertFalse(borrower.getLoans().isEmpty());
    }

    @Test
    @DisplayName("getLoanById validates property address without null components")
    void getLoanByIdValidatesPropertyAddress() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertNotNull(loan);
        assertNotNull(loan.getPropertyAddress());
        assertFalse(loan.getPropertyAddress().contains("null"));
    }

    @Test
    @DisplayName("Validator detects payment component mismatches in seed data")
    void validatorDetectsPaymentComponentMismatch() {
        DataQualityValidator validator = loanService.getValidator();
        validator.clearResults();

        // This triggers validation on all payments for this loan
        loanService.getPaymentsByLoan("LN-2019-00142");

        // The seed data has known mismatches (PMT-2025120001: components sum != total)
        long mediumIssues = validator.countBySeverity(DataQualityValidator.Severity.MEDIUM);
        assertTrue(mediumIssues > 0, "Should detect payment component mismatches");
    }

    @Test
    @DisplayName("Validator has no critical errors on valid seed data")
    void validatorHasNoCriticalErrorsOnSeedData() {
        DataQualityValidator validator = loanService.getValidator();
        validator.clearResults();

        loanService.getAllLoans();
        loanService.getAllBorrowers();

        long criticalErrors = validator.countBySeverity(DataQualityValidator.Severity.CRITICAL);
        assertEquals(0, criticalErrors, "Seed data should have no critical FK/parsing errors");
    }
}
