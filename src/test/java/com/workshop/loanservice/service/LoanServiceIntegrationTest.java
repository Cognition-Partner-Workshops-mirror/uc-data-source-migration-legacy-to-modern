package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration test that verifies the LoanService correctly handles
 * the actual legacy seed data including known anomalies.
 * Uses the H2 in-memory database with data-legacy.sql loaded on startup.
 */
@SpringBootTest
class LoanServiceIntegrationTest {

    @Autowired
    private LoanService loanService;

    @Test
    @DisplayName("getAllLoans returns all 5 loans without throwing exceptions")
    void getAllLoansDoesNotThrow() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertEquals(5, loans.size());
    }

    @Test
    @DisplayName("Loan amounts are parsed correctly from comma-separated strings")
    void loanAmountsParsedCorrectly() {
        // LN-2019-00142: original amount "285,000"
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals(new BigDecimal("285000"), loan.getOriginalAmount());
        assertEquals(new BigDecimal("271432.56"), loan.getCurrentBalance());
        assertEquals(new BigDecimal("4.750"), loan.getInterestRate());
        assertEquals(new BigDecimal("1487.02"), loan.getMonthlyPayment());
    }

    @Test
    @DisplayName("Borrower name is constructed without 'null' literal when middle initial is null")
    void borrowerNameHandlesNullMiddleInitial() {
        // B-10005 (Robert Williams) has NULL middle initial
        BorrowerDto borrower = loanService.getBorrowerById("B-10005");
        assertEquals("Robert Williams", borrower.getFullName());
        assertFalse(borrower.getFullName().contains("null"));
    }

    @Test
    @DisplayName("Borrower name includes middle initial when present")
    void borrowerNameIncludesMiddleInitial() {
        // B-10001 (James R. Mitchell) has middle initial 'R'
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals("James R. Mitchell", borrower.getFullName());
    }

    @Test
    @DisplayName("Credit score is parsed as integer from string")
    void creditScoreParsedAsInteger() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals(745, borrower.getCreditScore());
    }

    @Test
    @DisplayName("Property address does not contain 'null' literals for complete records")
    void propertyAddressNoNullLiterals() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertFalse(loan.getPropertyAddress().contains("null"));
        assertTrue(loan.getPropertyAddress().contains("742 Elm Street"));
        assertTrue(loan.getPropertyAddress().contains("Springfield"));
    }

    @Test
    @DisplayName("Status codes are expanded correctly")
    void statusCodesExpanded() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("Active", loan.getStatus());
    }

    @Test
    @DisplayName("Property types are expanded correctly")
    void propertyTypesExpanded() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2021-00567");
        assertEquals("Townhouse", loan.getPropertyType());
    }

    @Test
    @DisplayName("Payments are returned and parsed without exceptions despite sum mismatches in data")
    void paymentsReturnedDespiteSumMismatches() {
        // PMT-2025120001 has a known component sum mismatch
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(2, payments.size());

        // Verify amounts are still parsed correctly
        PaymentDto payment = payments.stream()
                .filter(p -> "PMT-2025120001".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();
        assertEquals(new BigDecimal("1487.02"), payment.getTotalAmount());
        assertEquals(new BigDecimal("456.78"), payment.getPrincipalAmount());
        assertEquals(new BigDecimal("1074.69"), payment.getInterestAmount());
    }

    @Test
    @DisplayName("Payment types and statuses are expanded correctly")
    void paymentTypesAndStatusesExpanded() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        PaymentDto payment = payments.get(0);
        assertEquals("Regular", payment.getType());
        assertEquals("Posted", payment.getStatus());
    }

    @Test
    @DisplayName("getAllBorrowers returns all 5 borrowers without throwing exceptions")
    void getAllBorrowersDoesNotThrow() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertEquals(5, borrowers.size());
    }

    @Test
    @DisplayName("Borrower with loans has loan list populated")
    void borrowerHasLoansPopulated() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertNotNull(borrower.getLoans());
        assertFalse(borrower.getLoans().isEmpty());
        assertEquals("LN-2019-00142", borrower.getLoans().get(0).getLoanAccountNumber());
    }

    @Test
    @DisplayName("Delinquent loan still returns successfully with validated status")
    void delinquentLoanReturnsSuccessfully() {
        // LN-2018-00089 has 15 days delinquent but ACT status — validation logs warning
        LoanSummaryDto loan = loanService.getLoanById("LN-2018-00089");
        assertNotNull(loan);
        assertEquals("Active", loan.getStatus());
    }
}
