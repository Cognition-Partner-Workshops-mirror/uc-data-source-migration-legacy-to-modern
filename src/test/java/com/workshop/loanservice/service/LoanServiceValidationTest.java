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
 * Integration tests verifying that the LoanService correctly handles the
 * legacy seed data (including known anomalies) without crashing.
 * Tests that safe parsing, null guards, and validation are wired correctly.
 */
@SpringBootTest
class LoanServiceValidationTest {

    @Autowired
    private LoanService loanService;

    @Test
    @DisplayName("getAllLoans returns all loans without NumberFormatException")
    void getAllLoans_noParsingCrash() {
        // The legacy seed data has comma-separated amounts — this verifies
        // the safe parsing doesn't throw (ANO-003)
        List<LoanSummaryDto> loans = loanService.getAllLoans();

        assertNotNull(loans);
        assertEquals(5, loans.size(), "Should return all 5 seed data loans");

        // Verify amounts are parsed correctly from comma-separated strings
        LoanSummaryDto firstLoan = loans.stream()
                .filter(l -> "LN-2019-00142".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertEquals(new BigDecimal("285000"), firstLoan.getOriginalAmount());
        assertEquals(new BigDecimal("271432.56"), firstLoan.getCurrentBalance());
    }

    @Test
    @DisplayName("getAllBorrowers handles null middle initial without NPE (ANO-005)")
    void getAllBorrowers_nullMiddleInitial() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();

        assertNotNull(borrowers);
        assertEquals(5, borrowers.size());

        // B-10005 Robert Williams has NULL middle initial
        BorrowerDto robert = borrowers.stream()
                .filter(b -> "B-10005".equals(b.getId()))
                .findFirst()
                .orElseThrow();
        // Should be "Robert Williams" without "null" in the name
        assertEquals("Robert Williams", robert.getFullName());
        assertFalse(robert.getFullName().contains("null"),
                "Name should not contain literal 'null'");
    }

    @Test
    @DisplayName("getBorrowerById returns borrower with loans attached")
    void getBorrowerById_withLoans() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");

        assertNotNull(borrower);
        assertEquals("James R. Mitchell", borrower.getFullName());
        assertEquals(745, borrower.getCreditScore());
        assertNotNull(borrower.getLoans());
        assertEquals(1, borrower.getLoans().size());
    }

    @Test
    @DisplayName("getPaymentsByLoan returns payments with correctly parsed amounts")
    void getPaymentsByLoan_amountsParsed() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");

        assertNotNull(payments);
        assertEquals(2, payments.size());

        // Verify amounts are parsed even though they had comma-separated strings
        PaymentDto pmt = payments.stream()
                .filter(p -> "PMT-2025120001".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();
        assertEquals(new BigDecimal("1487.02"), pmt.getTotalAmount());
        assertEquals(new BigDecimal("456.78"), pmt.getPrincipalAmount());
        assertEquals("Regular", pmt.getType());
        assertEquals("Posted", pmt.getStatus());
    }

    @Test
    @DisplayName("Loan with delinquency days still returns with Active status (ANO-004)")
    void loanWithDelinquency_stillReturns() {
        // LN-2018-00089 has 15 delinquency days but ACT status
        // Validation should log a warning but not crash
        LoanSummaryDto loan = loanService.getLoanById("LN-2018-00089");

        assertNotNull(loan);
        assertEquals("Active", loan.getStatus());
        assertEquals("Michael Torres", loan.getBorrowerName());
    }

    @Test
    @DisplayName("Status codes are expanded correctly for all known values")
    void statusCodesExpanded() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();

        // All seed data loans are ACT → "Active"
        loans.forEach(loan ->
                assertEquals("Active", loan.getStatus(),
                        "ACT should expand to Active for " + loan.getLoanAccountNumber()));
    }

    @Test
    @DisplayName("Property types are expanded correctly")
    void propertyTypesExpanded() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();

        LoanSummaryDto townhouse = loans.stream()
                .filter(l -> "LN-2021-00567".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertEquals("Townhouse", townhouse.getPropertyType());

        LoanSummaryDto condo = loans.stream()
                .filter(l -> "LN-2020-00398".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertEquals("Condominium", condo.getPropertyType());
    }
}
