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
 * Integration tests that verify the service layer correctly handles
 * the actual legacy seed data, including known anomalies.
 */
@SpringBootTest
class LoanServiceIntegrationTest {

    @Autowired
    private LoanService loanService;

    @Test
    @DisplayName("getAllLoans returns all 5 loans without crashing on legacy data")
    void getAllLoansHandlesLegacyData() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertEquals(5, loans.size());
        loans.forEach(loan -> {
            assertNotNull(loan.getLoanAccountNumber());
            assertNotNull(loan.getBorrowerName());
            assertFalse(loan.getBorrowerName().contains("null"), "Name should not contain literal 'null'");
            assertNotNull(loan.getOriginalAmount());
            assertNotNull(loan.getCurrentBalance());
            assertNotNull(loan.getInterestRate());
            assertNotNull(loan.getStatus());
            assertNotNull(loan.getOriginationDate());
            assertNotNull(loan.getPropertyAddress());
            assertFalse(loan.getPropertyAddress().contains("null"), "Address should not contain literal 'null'");
        });
    }

    @Test
    @DisplayName("getAllBorrowers returns all 5 borrowers with proper name formatting")
    void getAllBorrowersHandlesLegacyData() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertEquals(5, borrowers.size());
        borrowers.forEach(b -> {
            assertNotNull(b.getFullName());
            assertFalse(b.getFullName().contains("null"), "Name should not contain literal 'null'");
        });
    }

    @Test
    @DisplayName("Borrower with null middle initial is handled correctly")
    void borrowerWithNullMiddleInitial() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10005");
        assertEquals("Robert Williams", borrower.getFullName());
    }

    @Test
    @DisplayName("Borrower with middle initial formats correctly")
    void borrowerWithMiddleInitial() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals("James R. Mitchell", borrower.getFullName());
    }

    @Test
    @DisplayName("Credit scores are parsed as integers from legacy strings")
    void creditScoresParsed() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals(745, borrower.getCreditScore());
    }

    @Test
    @DisplayName("Loan amounts are parsed correctly from comma-formatted strings")
    void loanAmountsParsed() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals(new BigDecimal("285000"), loan.getOriginalAmount());
        assertEquals(new BigDecimal("271432.56"), loan.getCurrentBalance());
        assertEquals(new BigDecimal("4.750"), loan.getInterestRate());
        assertEquals(new BigDecimal("1487.02"), loan.getMonthlyPayment());
    }

    @Test
    @DisplayName("Origination dates are converted to ISO format")
    void originationDatesConverted() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("2019-02-15", loan.getOriginationDate());
    }

    @Test
    @DisplayName("Payment dates are converted to ISO format")
    void paymentDatesConverted() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());
        payments.forEach(p -> {
            assertNotNull(p.getPaymentDate());
            assertTrue(p.getPaymentDate().matches("\\d{4}-\\d{2}-\\d{2}"),
                    "Expected ISO date format but got: " + p.getPaymentDate());
        });
    }

    @Test
    @DisplayName("Payment amounts are parsed and service does not crash on sum mismatch")
    void paymentAmountsParsedDespiteSumMismatch() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(2, payments.size());
        payments.forEach(p -> {
            assertNotNull(p.getTotalAmount());
            assertNotNull(p.getPrincipalAmount());
            assertNotNull(p.getInterestAmount());
            assertNotNull(p.getEscrowAmount());
            assertNotNull(p.getLateFee());
            assertTrue(p.getTotalAmount().compareTo(BigDecimal.ZERO) > 0);
        });
    }

    @Test
    @DisplayName("Loan status codes are expanded correctly")
    void statusCodesExpanded() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("Active", loan.getStatus());
    }

    @Test
    @DisplayName("Property types are expanded correctly")
    void propertyTypesExpanded() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("Single Family Residence", loan.getPropertyType());

        LoanSummaryDto condo = loanService.getLoanById("LN-2020-00398");
        assertEquals("Condominium", condo.getPropertyType());
    }

    @Test
    @DisplayName("Property address is formatted cleanly")
    void propertyAddressFormatted() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("742 Elm Street, Springfield, IL 62701", loan.getPropertyAddress());
    }

    @Test
    @DisplayName("Payment types and statuses are expanded")
    void paymentTypesAndStatusesExpanded() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        payments.forEach(p -> {
            assertEquals("Regular", p.getType());
            assertEquals("Posted", p.getStatus());
        });
    }
}
