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

@SpringBootTest
class LoanServiceIntegrationTest {

    @Autowired
    private LoanService loanService;

    @Test
    void getAllLoans_returnsAllFiveLoans() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertEquals(5, loans.size());
    }

    @Test
    void getAllLoans_parsesAmountsCorrectly() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        LoanSummaryDto first = loans.stream()
                .filter(l -> "LN-2019-00142".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertEquals(new BigDecimal("285000"), first.getOriginalAmount());
        assertEquals(new BigDecimal("271432.56"), first.getCurrentBalance());
        assertEquals(new BigDecimal("4.750"), first.getInterestRate());
    }

    @Test
    void getAllLoans_buildsPropertyAddressSafely() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        LoanSummaryDto loan = loans.stream()
                .filter(l -> "LN-2019-00142".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertEquals("742 Elm Street, Springfield, IL 62701", loan.getPropertyAddress());
        assertFalse(loan.getPropertyAddress().contains("null"));
    }

    @Test
    void getAllLoans_expandsStatusCode() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        loans.forEach(loan -> assertEquals("Active", loan.getStatus()));
    }

    @Test
    void getAllLoans_formatsOriginationDateAsIso() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        LoanSummaryDto loan = loans.stream()
                .filter(l -> "LN-2019-00142".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertEquals("2019-02-15", loan.getOriginationDate());
    }

    @Test
    void getLoanById_validId() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertNotNull(loan);
        assertEquals("James Mitchell", loan.getBorrowerName());
        assertEquals("30-Year Fixed Rate Mortgage", loan.getProductDescription());
    }

    @Test
    void getLoanById_invalidIdThrows() {
        assertThrows(RuntimeException.class, () -> loanService.getLoanById("NONEXISTENT"));
    }

    @Test
    void getAllBorrowers_returnsAllFive() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertEquals(5, borrowers.size());
    }

    @Test
    void getAllBorrowers_buildsSafeFullName() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        BorrowerDto robert = borrowers.stream()
                .filter(b -> "B-10005".equals(b.getId()))
                .findFirst()
                .orElseThrow();
        assertEquals("Robert Williams", robert.getFullName());
        assertFalse(robert.getFullName().contains("null"));
    }

    @Test
    void getAllBorrowers_parsesCreditScore() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        BorrowerDto james = borrowers.stream()
                .filter(b -> "B-10001".equals(b.getId()))
                .findFirst()
                .orElseThrow();
        assertEquals(745, james.getCreditScore());
    }

    @Test
    void getBorrowerById_includesLoans() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertNotNull(borrower.getLoans());
        assertEquals(1, borrower.getLoans().size());
        assertEquals("LN-2019-00142", borrower.getLoans().get(0).getLoanAccountNumber());
    }

    @Test
    void getPaymentsByLoan_returnsPayments() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(2, payments.size());
    }

    @Test
    void getPaymentsByLoan_parsesAmounts() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");
        PaymentDto pmt = payments.get(0);
        assertNotNull(pmt.getTotalAmount());
        assertTrue(pmt.getTotalAmount().compareTo(BigDecimal.ZERO) > 0);
    }

    @Test
    void getPaymentsByLoan_expandsTypeAndStatus() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        payments.forEach(p -> {
            assertEquals("Regular", p.getType());
            assertEquals("Posted", p.getStatus());
        });
    }

    @Test
    void getPaymentsByLoan_formatsDateAsIso() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        PaymentDto pmt = payments.stream()
                .filter(p -> "PMT-2025120001".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();
        assertEquals("2025-12-15", pmt.getPaymentDate());
    }
}
