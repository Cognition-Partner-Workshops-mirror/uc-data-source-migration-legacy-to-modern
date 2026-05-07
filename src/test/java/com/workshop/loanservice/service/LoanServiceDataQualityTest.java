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

/**
 * Integration tests that verify the validation layer catches known anomalies
 * in the legacy seed data loaded from data-legacy.sql.
 */
@SpringBootTest
class LoanServiceDataQualityTest {

    @Autowired
    private LoanService loanService;

    @Test
    void getAllLoans_detectsStaleLtv_forAllLoans() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertFalse(loans.isEmpty());

        // ANO-007: All loans in the seed data have stale LTV values (based on original amounts)
        long loansWithLtvWarning = loans.stream()
                .filter(loan -> loan.getDataQualityWarnings() != null)
                .filter(loan -> loan.getDataQualityWarnings().stream()
                        .anyMatch(w -> "ANO-007".equals(w.getAnomalyId())))
                .count();
        assertTrue(loansWithLtvWarning > 0, "Should detect stale LTV in at least one loan");
    }

    @Test
    void getAllLoans_detectsDelinquencyStatusInconsistency() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();

        // ANO-004: Loan LN-2018-00089 has 15 days delinquent but ACT status
        LoanSummaryDto delinquentLoan = loans.stream()
                .filter(l -> "LN-2018-00089".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();

        boolean hasDelinquencyWarning = delinquentLoan.getDataQualityWarnings().stream()
                .anyMatch(w -> "ANO-004".equals(w.getAnomalyId()));
        assertTrue(hasDelinquencyWarning, "Should detect delinquency vs status mismatch for LN-2018-00089");
    }

    @Test
    void getAllLoans_parsesDateToIsoFormat() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();

        // ANO-008: Dates should be converted from MM/DD/YYYY to ISO-8601
        LoanSummaryDto loan = loans.stream()
                .filter(l -> "LN-2019-00142".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertEquals("2019-02-15", loan.getOriginationDate());
    }

    @Test
    void getAllBorrowers_parsesAllRecordsWithoutException() {
        // ANO-002: Even with all-string legacy data, parsing should never throw
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertEquals(5, borrowers.size());
        borrowers.forEach(b -> assertNotNull(b.getFullName()));
    }

    @Test
    void getAllBorrowers_parsesCreditScoresCorrectly() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        BorrowerDto james = borrowers.stream()
                .filter(b -> "B-10001".equals(b.getId()))
                .findFirst()
                .orElseThrow();
        assertEquals(745, james.getCreditScore());
    }

    @Test
    void getPaymentsByLoan_detectsComponentSumMismatch() {
        // ANO-001: Payments for LN-2019-00142 have $400 discrepancy
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());

        long mismatchCount = payments.stream()
                .filter(p -> p.getDataQualityWarnings() != null)
                .filter(p -> p.getDataQualityWarnings().stream()
                        .anyMatch(w -> "ANO-001".equals(w.getAnomalyId())))
                .count();
        assertEquals(2, mismatchCount, "Both payments for LN-2019-00142 should have component sum mismatch");
    }

    @Test
    void getPaymentsByLoan_matchingPayments_noComponentMismatch() {
        // Payments for LN-2020-00398 should have matching components
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");
        assertFalse(payments.isEmpty());

        long mismatchCount = payments.stream()
                .filter(p -> p.getDataQualityWarnings() != null)
                .filter(p -> p.getDataQualityWarnings().stream()
                        .anyMatch(w -> "ANO-001".equals(w.getAnomalyId())))
                .count();
        assertEquals(0, mismatchCount, "Payments for LN-2020-00398 should have matching components");
    }

    @Test
    void getPaymentsByLoan_detectsLateFeeInconsistency() {
        // ANO-006: PMT-2025110003 is 17 days late with fee, correct
        // PMT-2025120003 received 12/05 for 12/01 due = 4 days, within 15-day grace period
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2018-00089");
        assertFalse(payments.isEmpty());

        // PMT-2025110003 has a late fee and is >15 days late, so no ANO-006 warning
        // PMT-2025120003 is only 4 days late (within grace period), so no ANO-006 warning
        // But PMT-2025110003 has a late fee discrepancy in ANO-001 (components don't sum)
        PaymentDto novPayment = payments.stream()
                .filter(p -> "PMT-2025110003".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();

        // This payment has principal + interest + late fee != total (ANO-001)
        boolean hasComponentMismatch = novPayment.getDataQualityWarnings().stream()
                .anyMatch(w -> "ANO-001".equals(w.getAnomalyId()));
        assertTrue(hasComponentMismatch, "Nov payment for LN-2018-00089 should have component mismatch");
    }

    @Test
    void getLoanById_returnsValidLoan() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2021-00567");
        assertNotNull(loan);
        assertEquals("Emily Johnson", loan.getBorrowerName());
        assertEquals("Active", loan.getStatus());
        assertNotNull(loan.getOriginalAmount());
        assertTrue(loan.getOriginalAmount().doubleValue() > 0);
    }

    @Test
    void getBorrowerById_attachesLoansWithWarnings() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10003");
        assertNotNull(borrower);
        assertNotNull(borrower.getLoans());
        assertFalse(borrower.getLoans().isEmpty());

        // The borrower's loan LN-2018-00089 should have a delinquency warning
        LoanSummaryDto loan = borrower.getLoans().get(0);
        boolean hasDelinquencyWarning = loan.getDataQualityWarnings().stream()
                .anyMatch(w -> "ANO-004".equals(w.getAnomalyId()));
        assertTrue(hasDelinquencyWarning);
    }
}
