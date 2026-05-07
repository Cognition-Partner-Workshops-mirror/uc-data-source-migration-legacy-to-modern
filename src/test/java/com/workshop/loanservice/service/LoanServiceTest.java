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
class LoanServiceTest {

    @Autowired
    LoanService loanService;

    @Test
    void getAllLoans_doesNotThrowOnLegacyData() {
        List<LoanSummaryDto> loans = assertDoesNotThrow(() -> loanService.getAllLoans());
        assertFalse(loans.isEmpty());
    }

    @Test
    void getAllBorrowers_doesNotThrowOnLegacyData() {
        List<BorrowerDto> borrowers = assertDoesNotThrow(() -> loanService.getAllBorrowers());
        assertFalse(borrowers.isEmpty());
    }

    @Test
    void getBorrowerWithNullMiddleInitial_handlesGracefully() {
        BorrowerDto dto = assertDoesNotThrow(() -> loanService.getBorrowerById("B-10005"));
        assertNotNull(dto.getFullName());
        assertTrue(dto.getFullName().contains("Robert"));
        assertTrue(dto.getFullName().contains("Williams"));
        assertFalse(dto.getFullName().contains("null"));
    }

    @Test
    void getPaymentsByLoan_LN201900142_surfacesComponentMismatchWarning() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());
        boolean hasWarning = payments.stream()
                .anyMatch(p -> !p.getWarnings().isEmpty());
        assertTrue(hasWarning, "Expected at least one payment with component mismatch warning");
    }

    @Test
    void getLoanById_parsesAmountsCorrectly() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals(new BigDecimal("285000"), loan.getOriginalAmount());
        assertEquals(new BigDecimal("271432.56"), loan.getCurrentBalance());
        assertEquals(new BigDecimal("4.750"), loan.getInterestRate());
        assertEquals(new BigDecimal("1487.02"), loan.getMonthlyPayment());
    }

    @Test
    void getAllLoans_parsesAllStatusCodes() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        for (LoanSummaryDto loan : loans) {
            assertNotEquals("Unknown", loan.getStatus(),
                    "Unexpected Unknown status for loan: " + loan.getLoanAccountNumber());
        }
    }
}
