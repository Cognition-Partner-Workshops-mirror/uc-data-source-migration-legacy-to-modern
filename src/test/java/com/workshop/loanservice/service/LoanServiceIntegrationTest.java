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
    void getAllLoans_parsesAmountsWithoutCrashing() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertFalse(loans.isEmpty());
        assertEquals(5, loans.size());
        for (LoanSummaryDto loan : loans) {
            assertNotNull(loan.getOriginalAmount());
            assertNotNull(loan.getCurrentBalance());
            assertNotNull(loan.getInterestRate());
            assertNotNull(loan.getMonthlyPayment());
            assertTrue(loan.getOriginalAmount().compareTo(BigDecimal.ZERO) > 0);
        }
    }

    @Test
    void getAllLoans_datesParsedToIsoFormat() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        for (LoanSummaryDto loan : loans) {
            assertNotNull(loan.getOriginationDate());
            assertTrue(loan.getOriginationDate().matches("\\d{4}-\\d{2}-\\d{2}"),
                    "Expected ISO date format but got: " + loan.getOriginationDate());
        }
    }

    @Test
    void getAllLoans_delinquentLoanFlaggedWithWarning() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        LoanSummaryDto delinquentLoan = loans.stream()
                .filter(l -> "LN-2018-00089".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertNotNull(delinquentLoan.getDataQualityWarnings());
        assertFalse(delinquentLoan.getDataQualityWarnings().isEmpty());
        assertTrue(delinquentLoan.getDataQualityWarnings().stream()
                .anyMatch(w -> w.contains("delinquency days")));
    }

    @Test
    void getAllLoans_healthyLoansNoWarnings() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        LoanSummaryDto healthyLoan = loans.stream()
                .filter(l -> "LN-2020-00398".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertNull(healthyLoan.getDataQualityWarnings());
    }

    @Test
    void getAllBorrowers_parsesCreditScoresAndIncome() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertEquals(5, borrowers.size());
        for (BorrowerDto borrower : borrowers) {
            assertNotNull(borrower.getCreditScore());
            assertTrue(borrower.getCreditScore() >= 300 && borrower.getCreditScore() <= 850,
                    "Credit score out of range: " + borrower.getCreditScore());
            assertNotNull(borrower.getAnnualIncome());
            assertTrue(borrower.getAnnualIncome().compareTo(BigDecimal.ZERO) > 0);
        }
    }

    @Test
    void getBorrowerById_includesAnnualIncome() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals(new BigDecimal("92500"), borrower.getAnnualIncome());
    }

    @Test
    void getPaymentsByLoan_detectsComponentMismatch() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(2, payments.size());
        for (PaymentDto payment : payments) {
            assertNotNull(payment.getDataQualityWarnings());
            assertFalse(payment.getDataQualityWarnings().isEmpty());
            assertTrue(payment.getDataQualityWarnings().stream()
                    .anyMatch(w -> w.contains("total") && w.contains("components sum")));
        }
    }

    @Test
    void getPaymentsByLoan_balancedPaymentsNoComponentWarning() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");
        for (PaymentDto payment : payments) {
            boolean hasComponentWarning = payment.getDataQualityWarnings() != null
                    && payment.getDataQualityWarnings().stream()
                    .anyMatch(w -> w.contains("components sum"));
            assertFalse(hasComponentWarning,
                    "Expected no component mismatch warning for balanced payment");
        }
    }

    @Test
    void getPaymentsByLoan_latePaymentNoFeeWarning() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2018-00089");
        PaymentDto decPayment = payments.stream()
                .filter(p -> "PMT-2025120003".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();
        assertNotNull(decPayment.getDataQualityWarnings());
        assertTrue(decPayment.getDataQualityWarnings().stream()
                .anyMatch(w -> w.contains("no late fee")));
    }

    @Test
    void getLoanById_statusExpandedCorrectly() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("Active", loan.getStatus());
    }

    @Test
    void getLoanById_propertyTypeExpandedCorrectly() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("Single Family Residence", loan.getPropertyType());

        LoanSummaryDto condoLoan = loanService.getLoanById("LN-2020-00398");
        assertEquals("Condominium", condoLoan.getPropertyType());
    }

    @Test
    void getPaymentsByLoan_amountsParsedCorrectly() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");
        PaymentDto payment = payments.get(0);
        assertNotNull(payment.getTotalAmount());
        assertNotNull(payment.getPrincipalAmount());
        assertNotNull(payment.getInterestAmount());
        assertTrue(payment.getTotalAmount().compareTo(BigDecimal.ZERO) > 0);
    }

    @Test
    void getPaymentsByLoan_datesParsedToIsoFormat() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");
        for (PaymentDto payment : payments) {
            assertNotNull(payment.getPaymentDate());
            assertTrue(payment.getPaymentDate().matches("\\d{4}-\\d{2}-\\d{2}"),
                    "Expected ISO date but got: " + payment.getPaymentDate());
        }
    }
}
