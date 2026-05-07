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
 * Integration tests that verify the validation layer handles
 * the actual legacy seed data without crashing.
 */
@SpringBootTest
class LoanServiceValidationTest {

    @Autowired
    private LoanService loanService;

    @Test
    void getAllLoansDoesNotThrowOnLegacyData() {
        List<LoanSummaryDto> loans = assertDoesNotThrow(() -> loanService.getAllLoans());
        assertEquals(5, loans.size());
    }

    @Test
    void loanAmountsAreParsedCorrectly() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals(new BigDecimal("285000"), loan.getOriginalAmount());
        assertEquals(new BigDecimal("271432.56"), loan.getCurrentBalance());
        assertEquals(new BigDecimal("4.750"), loan.getInterestRate());
        assertEquals(new BigDecimal("1487.02"), loan.getMonthlyPayment());
    }

    @Test
    void loanDatesAreConvertedToIso() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("2019-02-15", loan.getOriginationDate());
    }

    @Test
    void loanStatusIsExpanded() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("Active", loan.getStatus());
    }

    @Test
    void propertyTypeIsExpanded() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("Single Family Residence", loan.getPropertyType());
    }

    @Test
    void propertyAddressIsFormatted() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("742 Elm Street, Springfield, IL 62701", loan.getPropertyAddress());
    }

    @Test
    void getAllBorrowersDoesNotThrowOnLegacyData() {
        List<BorrowerDto> borrowers = assertDoesNotThrow(() -> loanService.getAllBorrowers());
        assertEquals(5, borrowers.size());
    }

    @Test
    void borrowerCreditScoreIsParsed() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals(745, borrower.getCreditScore());
    }

    @Test
    void borrowerWithNullMiddleInitialIsHandled() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10005");
        assertEquals("Robert Williams", borrower.getFullName());
        assertEquals(658, borrower.getCreditScore());
    }

    @Test
    void borrowerWithMiddleInitialIsFormatted() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals("James R. Mitchell", borrower.getFullName());
    }

    @Test
    void paymentAmountsAreParsedCorrectly() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());

        PaymentDto pmt = payments.stream()
                .filter(p -> "PMT-2025120001".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();
        assertEquals(new BigDecimal("1487.02"), pmt.getTotalAmount());
        assertEquals(new BigDecimal("456.78"), pmt.getPrincipalAmount());
        assertEquals(new BigDecimal("1074.69"), pmt.getInterestAmount());
    }

    @Test
    void paymentDatesAreConvertedToIso() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        PaymentDto pmt = payments.stream()
                .filter(p -> "PMT-2025120001".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();
        assertEquals("2025-12-15", pmt.getPaymentDate());
    }

    @Test
    void paymentTypeIsExpanded() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        PaymentDto pmt = payments.get(0);
        assertEquals("Regular", pmt.getType());
    }

    @Test
    void paymentStatusIsExpanded() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        PaymentDto pmt = payments.get(0);
        assertEquals("Posted", pmt.getStatus());
    }

    @Test
    void delinquentLoanIsStillReturned() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2018-00089");
        assertNotNull(loan);
        assertEquals("Active", loan.getStatus());
    }

    @Test
    void allLoanProductCodesResolve() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        for (LoanSummaryDto loan : loans) {
            assertNotNull(loan.getProductDescription());
            assertFalse(loan.getProductDescription().isEmpty());
        }
    }

    @Test
    void borrowerLoansAreAttached() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertNotNull(borrower.getLoans());
        assertFalse(borrower.getLoans().isEmpty());
        assertEquals("LN-2019-00142", borrower.getLoans().get(0).getLoanAccountNumber());
    }
}
