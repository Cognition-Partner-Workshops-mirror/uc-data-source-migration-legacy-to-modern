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
 * Integration tests that exercise LoanService against the real legacy seed data
 * (data-legacy.sql) loaded into the in-memory H2 database. Verifies that the
 * validator's safe-parsing prevents crashes on the known anomalies.
 */
@SpringBootTest
class LoanServiceIntegrationTest {

    @Autowired
    private LoanService loanService;

    @Test
    void getAllLoansReturnsAllRecordsWithoutException() {
        // The legacy seed data contains 5 loan accounts — all should load
        // despite the known anomalies (ANM-001 SSN corruption, ANM-006 delinquency mismatch)
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertEquals(5, loans.size(), "Should return all 5 loan accounts from seed data");

        // Verify amounts were parsed correctly (ANM-004 safe parsing)
        LoanSummaryDto firstLoan = loans.stream()
                .filter(l -> "LN-2019-00142".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertEquals(new BigDecimal("285000"), firstLoan.getOriginalAmount());
        assertEquals(new BigDecimal("271432.56"), firstLoan.getCurrentBalance());
    }

    @Test
    void getAllBorrowersReturnsAllRecordsWithoutException() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertEquals(5, borrowers.size(), "Should return all 5 borrowers from seed data");

        // Verify credit score was safely parsed (ANM-004)
        BorrowerDto james = borrowers.stream()
                .filter(b -> "B-10001".equals(b.getId()))
                .findFirst()
                .orElseThrow();
        assertEquals(745, james.getCreditScore());
    }

    @Test
    void getBorrowerByIdIncludesLoans() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertNotNull(borrower);
        assertEquals("James R. Mitchell", borrower.getFullName());
        assertFalse(borrower.getLoans().isEmpty(), "Should include loans for borrower");
    }

    @Test
    void getPaymentsByLoanReturnsRecordsWithoutException() {
        // LN-2019-00142 has 2 payment records, including ones with component-sum
        // mismatches (ANM-002). The service should still return them without crashing.
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(2, payments.size());

        // Verify amounts were safely parsed despite the sum mismatch
        PaymentDto pmt = payments.stream()
                .filter(p -> "PMT-2025120001".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();
        assertEquals(new BigDecimal("1487.02"), pmt.getTotalAmount());
        assertEquals(new BigDecimal("456.78"), pmt.getPrincipalAmount());
    }

    @Test
    void nullSafeNameHandlingForBorrowerWithNullMiddleInitial() {
        // B-10005 Robert Williams has NULL middle initial
        BorrowerDto borrower = loanService.getBorrowerById("B-10005");
        assertEquals("Robert Williams", borrower.getFullName(),
                "Should handle null middle initial without 'null' literal in name");
    }

    @Test
    void statusCodesAreExpandedCorrectly() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        LoanSummaryDto activeLoan = loans.stream()
                .filter(l -> "LN-2019-00142".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertEquals("Active", activeLoan.getStatus(), "ACT should expand to Active");
    }

    @Test
    void propertyAddressIsAssembledWithoutNullLiterals() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertNotNull(loan.getPropertyAddress());
        assertFalse(loan.getPropertyAddress().contains("null"),
                "Property address should not contain 'null' literal");
    }
}
