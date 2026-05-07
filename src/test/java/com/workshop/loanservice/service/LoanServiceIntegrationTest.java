package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.validation.DataQualityWarning;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class LoanServiceIntegrationTest {

    @Autowired
    private LoanService loanService;

    @Test
    void getAllLoansDoesNotThrowOnLegacyData() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertNotNull(loans);
        assertEquals(5, loans.size());
    }

    @Test
    void getAllLoansPopulatesAmountsWithoutNullToZeroCoercion() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        for (LoanSummaryDto loan : loans) {
            assertNotNull(loan.getOriginalAmount(), "originalAmount should not be null for valid data");
            assertNotNull(loan.getCurrentBalance(), "currentBalance should not be null for valid data");
            assertNotNull(loan.getInterestRate(), "interestRate should not be null for valid data");
        }
    }

    @Test
    void getAllLoansConvertsDateToIsoFormat() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        for (LoanSummaryDto loan : loans) {
            assertNotNull(loan.getOriginationDate());
            assertTrue(loan.getOriginationDate().matches("\\d{4}-\\d{2}-\\d{2}"),
                    "Date should be in ISO format: " + loan.getOriginationDate());
        }
    }

    @Test
    void getAllBorrowersDoesNotThrowOnLegacyData() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertNotNull(borrowers);
        assertEquals(5, borrowers.size());
    }

    @Test
    void getAllBorrowersHandlesNullMiddleInitial() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        BorrowerDto robert = borrowers.stream()
                .filter(b -> b.getId().equals("B-10005"))
                .findFirst()
                .orElseThrow();
        assertEquals("Robert Williams", robert.getFullName());
        assertFalse(robert.getFullName().contains("null"));
    }

    @Test
    void getBorrowerByIdIncludesLoans() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertNotNull(borrower);
        assertNotNull(borrower.getLoans());
        assertFalse(borrower.getLoans().isEmpty());
    }

    @Test
    void getPaymentsByLoanDoesNotThrowOnLegacyData() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertNotNull(payments);
        assertEquals(2, payments.size());
    }

    @Test
    void paymentComponentMismatchIsDetected() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        PaymentDto pmt = payments.stream()
                .filter(p -> p.getPaymentId().equals("PMT-2025120001"))
                .findFirst()
                .orElseThrow();

        List<DataQualityWarning> componentWarnings = pmt.getDataQualityWarnings().stream()
                .filter(w -> w.getField().equals("paymentComponents"))
                .toList();

        assertFalse(componentWarnings.isEmpty(),
                "Should detect payment component mismatch for PMT-2025120001");
        assertEquals("CRITICAL", componentWarnings.get(0).getSeverity());
    }

    @Test
    void paymentDatesConvertedToIsoFormat() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        for (PaymentDto pmt : payments) {
            assertNotNull(pmt.getPaymentDate());
            assertTrue(pmt.getPaymentDate().matches("\\d{4}-\\d{2}-\\d{2}"),
                    "Payment date should be ISO format: " + pmt.getPaymentDate());
        }
    }

    @Test
    void matchingPaymentComponentsProduceNoMismatchWarning() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");
        PaymentDto pmt = payments.stream()
                .filter(p -> p.getPaymentId().equals("PMT-2025120002"))
                .findFirst()
                .orElseThrow();

        boolean hasMismatch = pmt.getDataQualityWarnings().stream()
                .anyMatch(w -> w.getField().equals("paymentComponents"));
        assertFalse(hasMismatch,
                "PMT-2025120002 components match total — should have no mismatch warning");
    }

    @Test
    void loanNotFoundThrowsException() {
        assertThrows(RuntimeException.class, () ->
                loanService.getLoanById("NONEXISTENT"));
    }

    @Test
    void borrowerNotFoundThrowsException() {
        assertThrows(RuntimeException.class, () ->
                loanService.getBorrowerById("NONEXISTENT"));
    }
}
