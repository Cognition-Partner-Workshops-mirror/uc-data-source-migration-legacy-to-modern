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
 * Integration tests that verify the service layer handles actual legacy seed data
 * correctly, including records with known data quality anomalies.
 *
 * These tests confirm that:
 * 1. The API does not crash on known bad data (defensive parsing)
 * 2. Valid data is parsed correctly into proper Java types
 * 3. Date fields are returned in ISO-8601 format
 * 4. Address concatenation does not produce literal "null" text
 */
@SpringBootTest
class LoanServiceIntegrationTest {

    @Autowired
    private LoanService loanService;

    @Test
    @DisplayName("getAllLoans does not throw even with known data anomalies")
    void getAllLoansDoesNotThrow() {
        // Should not throw even though the data has known quality issues
        List<LoanSummaryDto> loans = assertDoesNotThrow(() -> loanService.getAllLoans());
        assertNotNull(loans);
        assertEquals(5, loans.size());
    }

    @Test
    @DisplayName("getAllBorrowers does not throw with varied credit score formats")
    void getAllBorrowersDoesNotThrow() {
        List<BorrowerDto> borrowers = assertDoesNotThrow(() -> loanService.getAllBorrowers());
        assertNotNull(borrowers);
        assertEquals(5, borrowers.size());
    }

    @Test
    @DisplayName("Loan amounts are parsed correctly from comma-separated strings")
    void loanAmountsAreParsedCorrectly() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");

        // "285,000" → 285000
        assertEquals(new BigDecimal("285000"), loan.getOriginalAmount());
        // "271,432.56" → 271432.56
        assertEquals(new BigDecimal("271432.56"), loan.getCurrentBalance());
        // "4.750" → 4.750
        assertEquals(new BigDecimal("4.750"), loan.getInterestRate());
        // "1,487.02" → 1487.02
        assertEquals(new BigDecimal("1487.02"), loan.getMonthlyPayment());
    }

    @Test
    @DisplayName("Loan status codes are expanded correctly")
    void loanStatusCodesAreExpanded() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("Active", loan.getStatus());
    }

    @Test
    @DisplayName("Origination dates are returned in ISO-8601 format")
    void originationDatesAreIso8601() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        // "02/15/2019" → "2019-02-15"
        assertEquals("2019-02-15", loan.getOriginationDate());
    }

    @Test
    @DisplayName("Property address does not contain literal 'null' text")
    void propertyAddressDoesNotContainNull() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        for (LoanSummaryDto loan : loans) {
            assertFalse(loan.getPropertyAddress().contains("null"),
                    "Property address should not contain literal 'null': " + loan.getPropertyAddress());
        }
    }

    @Test
    @DisplayName("Borrower credit scores are parsed as integers")
    void borrowerCreditScoresAreParsed() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals(745, borrower.getCreditScore());
    }

    @Test
    @DisplayName("Borrower with null middle initial has clean name format")
    void borrowerNullMiddleInitialHandled() {
        // B-10005 Robert Williams has NULL middle initial
        BorrowerDto borrower = loanService.getBorrowerById("B-10005");
        assertEquals("Robert Williams", borrower.getFullName());
        assertFalse(borrower.getFullName().contains("null"));
    }

    @Test
    @DisplayName("Payment amounts are parsed correctly despite component mismatch")
    void paymentAmountsParsedDespiteMismatch() {
        // Loan LN-2019-00142 has known payment component mismatch (Anomaly #1)
        // The service should still return parsed values without crashing
        List<PaymentDto> payments = assertDoesNotThrow(
                () -> loanService.getPaymentsByLoan("LN-2019-00142"));

        assertNotNull(payments);
        assertEquals(2, payments.size());

        PaymentDto payment = payments.get(0);
        // Verify amounts are parsed (even if components don't sum correctly)
        assertNotNull(payment.getTotalAmount());
        assertNotNull(payment.getPrincipalAmount());
        assertNotNull(payment.getInterestAmount());
        assertNotNull(payment.getEscrowAmount());
        assertNotNull(payment.getLateFee());
    }

    @Test
    @DisplayName("Payment dates are returned in ISO-8601 format")
    void paymentDatesAreIso8601() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());

        // "12/15/2025" → "2025-12-15"
        PaymentDto firstPayment = payments.get(0);
        assertTrue(firstPayment.getPaymentDate().matches("\\d{4}-\\d{2}-\\d{2}"),
                "Payment date should be ISO-8601 format: " + firstPayment.getPaymentDate());
    }

    @Test
    @DisplayName("Payment types are expanded from code to description")
    void paymentTypesAreExpanded() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());
        assertEquals("Regular", payments.get(0).getType());
    }

    @Test
    @DisplayName("Payment statuses are expanded from code to description")
    void paymentStatusesAreExpanded() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());
        assertEquals("Posted", payments.get(0).getStatus());
    }

    @Test
    @DisplayName("getLoanById throws for non-existent loan")
    void getLoanByIdThrowsForNonExistent() {
        assertThrows(RuntimeException.class,
                () -> loanService.getLoanById("LN-DOES-NOT-EXIST"));
    }

    @Test
    @DisplayName("getBorrowerById throws for non-existent borrower")
    void getBorrowerByIdThrowsForNonExistent() {
        assertThrows(RuntimeException.class,
                () -> loanService.getBorrowerById("B-99999"));
    }

    @Test
    @DisplayName("Payments for non-existent loan returns empty list (not error)")
    void paymentsForNonExistentLoanReturnsEmpty() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-DOES-NOT-EXIST");
        assertNotNull(payments);
        assertTrue(payments.isEmpty());
    }
}
